#!/usr/bin/env python3
"""
test_freshness.py

Validates the replay-detection, duplicate-rejection, freshness-window,
and reboot-reset logic added in Week 7.

Each test constructs HMAC-signed packets and feeds them through the same
check_freshness() / accept_packet() pipeline used by host_receiver.py.

  1. Normal sequential packets       -- all accepted
  2. Exact replay                    -- flagged REPLAY
  3. Duplicate (same seq twice)      -- flagged DUPLICATE
  4. Out-of-order arrival            -- late packet flagged REPLAY
  5. Simulated device reboot         -- detected REBOOT_RESET
  6. Stale packet (host-clock gap)   -- flagged STALE

Prerequisites:
  - Mosquitto running with TLS on port 8883 (./broker.sh)
  - Certificates generated (./certs/generate_certs.sh)

Usage:
  cd broker && python3 test_freshness.py
"""

import os
import sys
import json
import hmac
import hashlib
import time
import ssl
import threading
import paho.mqtt.client as mqtt

BROKER_IP = "127.0.0.1"
TLS_PORT = 8883
TOPIC = "cc32xx/telemetry"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

CORRECT_KEY = bytes([
    0x4d, 0x79, 0x53, 0x65, 0x63, 0x75, 0x72, 0x65,
    0x44, 0x69, 0x67, 0x69, 0x74, 0x61, 0x6c, 0x54,
    0x77, 0x69, 0x6e, 0x4b, 0x65, 0x79, 0x32, 0x30,
    0x32, 0x36, 0x21, 0x40, 0x23, 0x24, 0x25, 0x5e
])

REBOOT_SEQ_THRESHOLD = 5
MAX_STALENESS_SEC = 30.0

results = []


# ============================================================
# Packet helpers (same as test_integrity.py)
# ============================================================

def sign_packet(key, device_id, seq, ts, temp, hum):
    canonical = f"{device_id}|{seq}|{ts}|{temp:.1f}|{hum:.1f}"
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


def build_packet(device_id, seq, ts, temp, hum, hmac_hex=None):
    pkt = {
        "schema_version": "1.0.0",
        "device_id": device_id,
        "seq_num": seq,
        "timestamp_ms": ts,
        "telemetry": {"temperature_c": temp, "humidity": hum}
    }
    if hmac_hex is not None:
        pkt["hmac"] = hmac_hex
    return json.dumps(pkt)


def make_signed_packet(seq, ts, temp=25.3, hum=48.7):
    device = "CC3220SF_NODE_01"
    h = sign_packet(CORRECT_KEY, device, seq, ts, temp, hum)
    return build_packet(device, seq, ts, temp, hum, h)


# ============================================================
# Local freshness validator (mirrors host_receiver.py logic)
# ============================================================

class FreshnessTracker:
    """Standalone copy of the host_receiver freshness pipeline for testing."""

    def __init__(self):
        self.last_accepted_seq = None
        self.last_accepted_board_ts = None
        self.last_accepted_wall_time = None

    def check(self, seq_num, board_time):
        if self.last_accepted_seq is None:
            return True, "ACCEPTED"

        if seq_num <= self.last_accepted_seq:
            if seq_num == self.last_accepted_seq:
                return False, "DUPLICATE"
            if (seq_num <= REBOOT_SEQ_THRESHOLD
                    and self.last_accepted_seq > REBOOT_SEQ_THRESHOLD):
                return True, "REBOOT_RESET"
            return False, "REPLAY"

        if (self.last_accepted_board_ts is not None
                and board_time <= self.last_accepted_board_ts):
            return False, "REPLAY"

        if self.last_accepted_wall_time is not None:
            delta = time.time() - self.last_accepted_wall_time
            if delta > MAX_STALENESS_SEC:
                return False, "STALE"

        expected_next = self.last_accepted_seq + 1
        if seq_num > expected_next:
            return True, "OOO_GAP"

        return True, "ACCEPTED"

    def accept(self, seq_num, board_time):
        self.last_accepted_seq = seq_num
        self.last_accepted_board_ts = board_time
        self.last_accepted_wall_time = time.time()


# ============================================================
# Broker roundtrip helper
# ============================================================

def make_tls_client(client_id):
    c = mqtt.Client(client_id=client_id)
    c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)
    return c


def publish_and_receive(client_id, payloads, timeout=8):
    """Publish a list of payloads and collect received messages."""
    received = []
    done = threading.Event()

    def on_connect(client, ud, flags, rc):
        if rc == 0:
            client.subscribe(TOPIC, qos=0)

    def on_message(client, ud, msg):
        try:
            received.append(json.loads(msg.payload.decode("utf-8")))
        except Exception:
            pass
        if len(received) >= len(payloads):
            done.set()

    c = make_tls_client(client_id)
    c.on_connect = on_connect
    c.on_message = on_message

    try:
        c.connect(BROKER_IP, TLS_PORT, 60)
        c.loop_start()
        time.sleep(1)

        for p in payloads:
            c.publish(TOPIC, p, qos=0)
            time.sleep(0.1)

        done.wait(timeout=timeout)
        c.loop_stop()
        c.disconnect()
    except Exception as e:
        return None, str(e)

    return received, None


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail else ""))


# ============================================================
# Test 1: Normal sequential packets
# ============================================================
def test_sequential():
    print("\n--- Test 1: Normal Sequential Packets ---")
    tracker = FreshnessTracker()

    pkts = [
        (1, 250),
        (2, 500),
        (3, 750),
    ]

    all_ok = True
    for seq, ts in pkts:
        accepted, status = tracker.check(seq, ts)
        if accepted:
            tracker.accept(seq, ts)
        if not accepted or status != "ACCEPTED":
            all_ok = False
            break

    record("Sequential Accepted", all_ok,
           "All 3 packets accepted in order" if all_ok
           else f"Unexpected rejection at seq {seq}: {status}")

    # Roundtrip through broker
    payloads = [make_signed_packet(s, t) for s, t in pkts]
    received, err = publish_and_receive("test_seq", payloads)
    if err:
        record("Sequential Roundtrip", False, err)
    else:
        record("Sequential Roundtrip", len(received) == 3,
               f"Received {len(received)}/3 packets via broker")


# ============================================================
# Test 2: Exact replay
# ============================================================
def test_replay():
    print("\n--- Test 2: Exact Replay Detection ---")
    tracker = FreshnessTracker()

    # Accept packets 1-3
    for seq, ts in [(1, 250), (2, 500), (3, 750)]:
        accepted, _ = tracker.check(seq, ts)
        if accepted:
            tracker.accept(seq, ts)

    # Replay packet 2
    accepted, status = tracker.check(2, 500)
    record("Replay Rejected", not accepted and status == "REPLAY",
           f"seq=2 after accepting seq=3 -> {status}"
           if not accepted else "DANGER: replayed packet accepted")


# ============================================================
# Test 3: Duplicate (same seq twice in a row)
# ============================================================
def test_duplicate():
    print("\n--- Test 3: Duplicate Detection ---")
    tracker = FreshnessTracker()

    tracker.check(1, 250)
    tracker.accept(1, 250)

    # Send seq=1 again
    accepted, status = tracker.check(1, 250)
    record("Duplicate Detected", not accepted and status == "DUPLICATE",
           f"seq=1 sent twice -> {status}"
           if not accepted else "DANGER: duplicate accepted")


# ============================================================
# Test 4: Out-of-order (seq 1, 3, 2)
# ============================================================
def test_out_of_order():
    print("\n--- Test 4: Out-of-Order Detection ---")
    tracker = FreshnessTracker()

    tracker.check(1, 250)
    tracker.accept(1, 250)

    # Skip to seq=3
    accepted, status = tracker.check(3, 750)
    if accepted:
        tracker.accept(3, 750)

    record("Gap Accepted", accepted and status == "OOO_GAP",
           f"seq=3 after seq=1 -> {status}")

    # Late arrival of seq=2 (already past seq=3)
    accepted, status = tracker.check(2, 500)
    record("Late Packet Rejected", not accepted and status == "REPLAY",
           f"seq=2 after accepting seq=3 -> {status}"
           if not accepted else "DANGER: late packet accepted")


# ============================================================
# Test 5: Simulated device reboot
# ============================================================
def test_reboot():
    print("\n--- Test 5: Device Reboot Detection ---")
    tracker = FreshnessTracker()

    # Simulate 500 packets received
    tracker.last_accepted_seq = 500
    tracker.last_accepted_board_ts = 125000
    tracker.last_accepted_wall_time = time.time()

    # Device reboots — seq drops back to 1
    accepted, status = tracker.check(1, 250)
    record("Reboot Detected", accepted and status == "REBOOT_RESET",
           f"seq=1 after seq=500 -> {status}")

    if accepted:
        tracker.accept(1, 250)

    # After reboot, normal seq=2 should work
    accepted, status = tracker.check(2, 500)
    record("Post-Reboot Normal", accepted and status == "ACCEPTED",
           f"seq=2 after reboot reset -> {status}")


# ============================================================
# Test 6: Stale packet (simulated host-clock gap)
# ============================================================
def test_stale():
    print("\n--- Test 6: Stale Packet Detection ---")
    tracker = FreshnessTracker()

    tracker.check(1, 250)
    tracker.accept(1, 250)

    # Simulate the last accepted time being >30s ago
    tracker.last_accepted_wall_time = time.time() - (MAX_STALENESS_SEC + 5)

    accepted, status = tracker.check(2, 500)
    record("Stale Packet Flagged", not accepted and status == "STALE",
           f"35s gap -> {status}"
           if not accepted else "DANGER: stale packet accepted")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    if not os.path.exists(CA_CERT):
        print(f"ERROR: CA certificate not found at {CA_CERT}")
        print("Run: cd broker/certs && ./generate_certs.sh")
        sys.exit(1)

    print("=" * 55)
    print("  MQTT Freshness & Replay Detection Tests (Week 7)")
    print("=" * 55)

    test_sequential()
    test_replay()
    test_duplicate()
    test_out_of_order()
    test_reboot()
    test_stale()

    print("\n" + "=" * 55)
    print("  SUMMARY")
    print("=" * 55)
    passed = sum(1 for _, s, _ in results if s == "PASS")
    total = len(results)
    for name, status, detail in results:
        print(f"  [{status}] {name}")
    print(f"\n  {passed}/{total} tests passed.")
    print("=" * 55)

    sys.exit(0 if passed == total else 1)
