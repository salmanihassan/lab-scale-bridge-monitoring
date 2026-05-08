#!/usr/bin/env python3
"""
test_schema.py

Validates the schema-version handling added in Week 9.

  1. v1.0.0 packet accepted       -- version present and recognized
  2. Legacy packet accepted        -- no schema_version field
  3. Unknown version rejected      -- unsupported version string
  4. Broker roundtrip (versioned)  -- v1.0.0 packet survives relay

Prerequisites:
  - Mosquitto running with TLS on port 8883 (for test 4 only)
  - Certificates generated (./certs/generate_certs.sh)

Usage:
  cd broker && python3 test_schema.py
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

SUPPORTED_SCHEMA_VERSIONS = {"1.0.0"}

results = []


def sign_packet(key, device_id, seq, ts, temp, hum):
    canonical = f"{device_id}|{seq}|{ts}|{temp:.1f}|{hum:.1f}"
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


def build_packet(device_id, seq, ts, temp, hum, hmac_hex=None,
                 schema_version="1.0.0", include_version=True):
    pkt = {}
    if include_version and schema_version is not None:
        pkt["schema_version"] = schema_version
    pkt.update({
        "device_id": device_id,
        "seq_num": seq,
        "timestamp_ms": ts,
        "telemetry": {"temperature_c": temp, "humidity": hum},
    })
    if hmac_hex is not None:
        pkt["hmac"] = hmac_hex
    return json.dumps(pkt)


def make_signed_packet(seq, ts, temp=25.3, hum=48.7,
                       schema_version="1.0.0", include_version=True):
    device = "CC3220SF_NODE_01"
    h = sign_packet(CORRECT_KEY, device, seq, ts, temp, hum)
    return build_packet(device, seq, ts, temp, hum, h,
                        schema_version=schema_version,
                        include_version=include_version)


def check_version(data):
    """Mirror the host_receiver.py schema version validation logic."""
    sv = data.get("schema_version")
    if sv is None:
        return True, "LEGACY"
    if sv in SUPPORTED_SCHEMA_VERSIONS:
        return True, sv
    return False, f"SCHEMA_UNKNOWN:{sv}"


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail else ""))


# ============================================================
# Test 1: v1.0.0 packet accepted
# ============================================================
def test_versioned_accepted():
    print("\n--- Test 1: Versioned Packet (v1.0.0) Accepted ---")
    pkt_json = make_signed_packet(1, 250)
    data = json.loads(pkt_json)

    accepted, status = check_version(data)
    record("v1.0.0 Accepted", accepted and status == "1.0.0",
           f"status={status}")

    sv = data.get("schema_version")
    record("Version Field Present", sv == "1.0.0",
           f"schema_version={sv}")


# ============================================================
# Test 2: Legacy packet accepted (no schema_version)
# ============================================================
def test_legacy_accepted():
    print("\n--- Test 2: Legacy Packet (no version) Accepted ---")
    pkt_json = make_signed_packet(2, 500, include_version=False)
    data = json.loads(pkt_json)

    accepted, status = check_version(data)
    record("Legacy Accepted", accepted and status == "LEGACY",
           f"status={status}")

    sv = data.get("schema_version")
    record("No Version Field", sv is None,
           f"schema_version={sv}")


# ============================================================
# Test 3: Unknown version rejected
# ============================================================
def test_unknown_rejected():
    print("\n--- Test 3: Unknown Version Rejected ---")
    pkt_json = make_signed_packet(3, 750, schema_version="2.0.0")
    data = json.loads(pkt_json)

    accepted, status = check_version(data)
    record("Unknown Version Rejected", not accepted,
           f"status={status}")


# ============================================================
# Test 4: Broker roundtrip with versioned packet
# ============================================================
def test_broker_roundtrip():
    print("\n--- Test 4: Broker Roundtrip (versioned) ---")

    if not os.path.exists(CA_CERT):
        record("Broker Roundtrip", False, "CA cert not found, skipping")
        return

    pkt_json = make_signed_packet(4, 1000)
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
        if len(received) >= 1:
            done.set()

    c = mqtt.Client(client_id="test_schema_rt")
    c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)
    c.on_connect = on_connect
    c.on_message = on_message

    try:
        c.connect(BROKER_IP, TLS_PORT, 60)
        c.loop_start()
        time.sleep(1)

        c.publish(TOPIC, pkt_json, qos=0)
        done.wait(timeout=8)
        c.loop_stop()
        c.disconnect()

        if len(received) == 0:
            record("Broker Roundtrip", False, "No message received")
            return

        sv = received[0].get("schema_version")
        record("Broker Roundtrip", sv == "1.0.0",
               f"Received schema_version={sv}")

    except Exception as e:
        record("Broker Roundtrip", False, f"Connection error: {e}")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 55)
    print("  Schema Version Validation Tests (Week 9)")
    print("=" * 55)

    test_versioned_accepted()
    test_legacy_accepted()
    test_unknown_rejected()
    test_broker_roundtrip()

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
