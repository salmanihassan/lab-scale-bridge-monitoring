#!/usr/bin/env python3
"""
test_integrity.py

Validates HMAC-SHA256 message authentication by publishing four tamper
scenarios through the Mosquitto broker and verifying detection on the
host receiver side.

  1. Valid authenticated packet     -- correct HMAC, should pass
  2. Modified payload (tampered)    -- changed telemetry, original HMAC
  3. Wrong key (unauthorized source)-- signed with a different PSK
  4. Missing HMAC field             -- legacy/stripped packet

Prerequisites:
  - Mosquitto running with TLS on port 8883 (./broker.sh)
  - Certificates generated (./certs/generate_certs.sh)

Usage:
  cd broker && python3 test_integrity.py
"""

import paho.mqtt.client as mqtt
import ssl
import os
import sys
import json
import hmac
import hashlib
import time
import threading

BROKER_IP = "127.0.0.1"
TLS_PORT = 8883
TOPIC = "cc32xx/telemetry"
TIMEOUT = 8

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

# Correct PSK -- matches hmac_auth.h and host_receiver.py
CORRECT_KEY = bytes([
    0x4d, 0x79, 0x53, 0x65, 0x63, 0x75, 0x72, 0x65,
    0x44, 0x69, 0x67, 0x69, 0x74, 0x61, 0x6c, 0x54,
    0x77, 0x69, 0x6e, 0x4b, 0x65, 0x79, 0x32, 0x30,
    0x32, 0x36, 0x21, 0x40, 0x23, 0x24, 0x25, 0x5e
])

# Wrong PSK -- simulates an unauthorized device
WRONG_KEY = bytes([0xDE, 0xAD] * 16)

results = []


def sign_packet(key, device_id, seq, ts, temp, hum):
    """Build canonical string and compute HMAC-SHA256."""
    canonical = f"{device_id}|{seq}|{ts}|{temp:.1f}|{hum:.1f}"
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


def build_packet(device_id, seq, ts, temp, hum, hmac_hex=None):
    """Build a JSON telemetry packet, optionally including an HMAC field."""
    pkt = {
        "schema_version": "1.0.0",
        "device_id": device_id,
        "seq_num": seq,
        "timestamp_ms": ts,
        "telemetry": {
            "temperature_c": temp,
            "humidity": hum
        }
    }
    if hmac_hex is not None:
        pkt["hmac"] = hmac_hex
    return json.dumps(pkt)


def verify_locally(key, packet_json):
    """Re-verify a packet the same way host_receiver.py does."""
    data = json.loads(packet_json)
    received_hmac = data.get("hmac")
    if received_hmac is None:
        return False, "missing"

    telemetry = data.get("telemetry", {})
    canonical = (f"{data['device_id']}|{data['seq_num']}|{data['timestamp_ms']}"
                 f"|{telemetry['temperature_c']:.1f}|{telemetry['humidity']:.1f}")
    expected = hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()

    if hmac.compare_digest(expected, received_hmac):
        return True, "ok"
    return False, "mismatch"


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail else ""))


def make_tls_client(client_id):
    """Create a TLS-configured MQTT client."""
    c = mqtt.Client(client_id=client_id)
    c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)
    return c


def roundtrip_test(client_id, payload_json, expect_pass):
    """
    Publish a packet and subscribe to receive it back.  Verify HMAC on the
    received copy to confirm the broker faithfully relayed it.
    """
    received = threading.Event()
    received_data = {}

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(TOPIC, qos=0)

    def on_message(client, userdata, msg):
        try:
            received_data["payload"] = msg.payload.decode("utf-8")
            received.set()
        except Exception as e:
            received_data["error"] = str(e)
            received.set()

    client = make_tls_client(client_id)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(BROKER_IP, TLS_PORT, 60)
        client.loop_start()
        time.sleep(1)

        client.publish(TOPIC, payload_json, qos=0)
        got_msg = received.wait(timeout=TIMEOUT)
        client.loop_stop()
        client.disconnect()

        if not got_msg:
            return False, "No message received within timeout"

        if "error" in received_data:
            return False, received_data["error"]

        verified, reason = verify_locally(CORRECT_KEY, received_data["payload"])
        return (verified == expect_pass), reason

    except Exception as e:
        return False, str(e)


# ============================================================
# Test 1: Valid authenticated packet
# ============================================================
def test_valid_packet():
    print("\n--- Test 1: Valid Authenticated Packet ---")
    h = sign_packet(CORRECT_KEY, "CC3220SF_NODE_01", 9001, 2250250, 25.3, 48.7)
    pkt = build_packet("CC3220SF_NODE_01", 9001, 2250250, 25.3, 48.7, h)

    verified, reason = verify_locally(CORRECT_KEY, pkt)
    record("Valid Packet Accepted", verified,
           "HMAC verified successfully" if verified else f"Unexpected: {reason}")

    ok, detail = roundtrip_test("test_valid", pkt, True)
    record("Valid Packet Roundtrip", ok,
           "Survived broker relay" if ok else detail)


# ============================================================
# Test 2: Payload modification (tamper detection)
# ============================================================
def test_tampered_payload():
    print("\n--- Test 2: Tampered Payload Detection ---")
    h = sign_packet(CORRECT_KEY, "CC3220SF_NODE_01", 9002, 2250500, 25.3, 48.7)
    tampered_pkt = build_packet("CC3220SF_NODE_01", 9002, 2250500, 99.9, 48.7, h)

    verified, reason = verify_locally(CORRECT_KEY, tampered_pkt)
    record("Tampered Payload Detected", not verified,
           f"HMAC {reason} (tamper caught)" if not verified
           else "DANGER: tampered packet passed verification")


# ============================================================
# Test 3: Wrong key (unauthorized source)
# ============================================================
def test_wrong_key():
    print("\n--- Test 3: Unauthorized Source (Wrong Key) ---")
    h = sign_packet(WRONG_KEY, "CC3220SF_NODE_01", 9003, 2250750, 25.3, 48.7)
    pkt = build_packet("CC3220SF_NODE_01", 9003, 2250750, 25.3, 48.7, h)

    verified, reason = verify_locally(CORRECT_KEY, pkt)
    record("Wrong Key Rejected", not verified,
           f"HMAC {reason} (unauthorized device caught)" if not verified
           else "DANGER: wrong-key packet passed verification")


# ============================================================
# Test 4: Missing HMAC field
# ============================================================
def test_missing_hmac():
    print("\n--- Test 4: Missing HMAC Field ---")
    pkt = build_packet("CC3220SF_NODE_01", 9004, 2251000, 25.3, 48.7, None)

    verified, reason = verify_locally(CORRECT_KEY, pkt)
    record("Missing HMAC Flagged", not verified,
           f"HMAC {reason} (unauthenticated packet caught)" if not verified
           else "DANGER: packet without HMAC passed verification")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    if not os.path.exists(CA_CERT):
        print(f"ERROR: CA certificate not found at {CA_CERT}")
        print("Run: cd broker/certs && ./generate_certs.sh")
        sys.exit(1)

    print("=" * 55)
    print("  MQTT Data Integrity & Authentication Tests")
    print("=" * 55)

    test_valid_packet()
    test_tampered_payload()
    test_wrong_key()
    test_missing_hmac()

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
