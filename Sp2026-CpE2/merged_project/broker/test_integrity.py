#!/usr/bin/env python3
"""
test_integrity.py

Validates AES-128-GCM AEAD message authentication (Week 11) by
publishing six tamper scenarios through the Mosquitto broker and
verifying detection on the host receiver side.

Each test exercises a distinct failure mode of the AEAD envelope:

  1. Valid envelope                  -- correct GCM tag, should pass
  2. Tampered ciphertext (1 hex flip)-- GCM InvalidTag
  3. Tampered AAD (outer seq_num)    -- GCM InvalidTag (AAD mismatch)
  4. Wrong key                       -- GCM InvalidTag
  5. Missing ciphertext field        -- envelope rejected
  6. Broker round-trip (valid)       -- end-to-end through Mosquitto

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
import time
import threading
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

BROKER_IP = "127.0.0.1"
TLS_PORT = 8883
TOPIC = "cc32xx/telemetry"
TIMEOUT = 8

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

# Week 11 upgrade: AES-128-GCM key (matches AES_KEY[] in mqtt_client_app.c)
CORRECT_KEY = b"LabKey12LabKey12"   # 16 bytes -> AES-128
WRONG_KEY   = b"WrongKey00WrongK"   # 16 bytes, intentionally different
GCM_IV_LEN = 12
GCM_TAG_LEN = 16

DEVICE_ID = "CC3220SF_NODE_01"

results = []


def build_inner_json(temp, hum, duty=None, period=None):
    """Build the inner (encrypted) JSON exactly like the firmware does."""
    telemetry = {"temperature_c": temp, "humidity": hum}
    if duty is not None:
        telemetry["pwm_duty_us"] = duty
    if period is not None:
        telemetry["pwm_period_us"] = period
    return json.dumps({
        "schema_version": "2.0.0",
        "telemetry": telemetry,
    })


def gcm_wrap(inner_json, device_id, seq, ts, key=CORRECT_KEY):
    """Encrypt + wrap into the v2.0.0 outer envelope.  Returns the
    JSON string the firmware would publish on cc32xx/telemetry."""
    iv  = os.urandom(GCM_IV_LEN)
    aad = f"{device_id}|{seq}|{ts}".encode("utf-8")
    ct  = AESGCM(key).encrypt(iv, inner_json.encode("utf-8"), aad)
    blob = (iv + ct).hex().upper()
    return json.dumps({
        "schema_version": "2.0.0",
        "device_id": device_id,
        "seq_num": seq,
        "timestamp_ms": ts,
        "ciphertext": blob,
    })


def verify_locally(envelope_json, key=CORRECT_KEY):
    """Re-verify the same way host_receiver.decrypt_gcm_envelope does."""
    try:
        env = json.loads(envelope_json)
    except json.JSONDecodeError:
        return False, "envelope_json_invalid"

    try:
        device_id = env["device_id"]
        seq = env["seq_num"]
        ts  = env["timestamp_ms"]
        hex_blob = env["ciphertext"]
    except KeyError as e:
        return False, f"missing:{e.args[0]}"

    try:
        blob = bytes.fromhex(hex_blob)
    except ValueError:
        return False, "hex_invalid"

    if len(blob) < GCM_IV_LEN + GCM_TAG_LEN:
        return False, "blob_too_short"

    iv = blob[:GCM_IV_LEN]
    ct_and_tag = blob[GCM_IV_LEN:]
    aad = f"{device_id}|{seq}|{ts}".encode("utf-8")

    try:
        AESGCM(key).decrypt(iv, ct_and_tag, aad)
    except InvalidTag:
        return False, "invalid_tag"

    return True, "ok"


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail else ""))


def make_tls_client(client_id):
    c = mqtt.Client(client_id=client_id)
    c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)
    return c


def roundtrip_test(client_id, payload_json, expect_pass):
    """Publish a payload through the broker and verify the relay."""
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

        verified, reason = verify_locally(received_data["payload"])
        return (verified == expect_pass), reason

    except Exception as e:
        return False, str(e)


# ============================================================
# Test 1: Valid envelope
# ============================================================
def test_valid_envelope():
    print("\n--- Test 1: Valid GCM Envelope ---")
    inner = build_inner_json(25.3, 48.7, duty=8000, period=10000)
    env = gcm_wrap(inner, DEVICE_ID, 9001, 2250250)

    verified, reason = verify_locally(env)
    record("Valid Envelope Accepted", verified,
           "GCM tag verified" if verified else f"Unexpected: {reason}")


# ============================================================
# Test 2: Tampered ciphertext (1 byte flipped in hex blob)
# ============================================================
def test_tampered_ciphertext():
    print("\n--- Test 2: Tampered Ciphertext Detection ---")
    inner = build_inner_json(25.3, 48.7, duty=8000, period=10000)
    env = json.loads(gcm_wrap(inner, DEVICE_ID, 9002, 2250500))

    blob = bytearray(bytes.fromhex(env["ciphertext"]))
    # Flip a byte well inside the ciphertext region (past IV).
    blob[GCM_IV_LEN + 4] ^= 0xFF
    env["ciphertext"] = blob.hex().upper()
    tampered = json.dumps(env)

    verified, reason = verify_locally(tampered)
    record("Tampered Ciphertext Detected", not verified,
           f"GCM rejected: {reason}" if not verified
           else "DANGER: tampered ciphertext passed verification")


# ============================================================
# Test 3: Tampered AAD (outer seq_num bumped)
# ============================================================
def test_tampered_aad():
    print("\n--- Test 3: Tampered AAD (outer seq_num) Detection ---")
    inner = build_inner_json(25.3, 48.7, duty=8000, period=10000)
    env = json.loads(gcm_wrap(inner, DEVICE_ID, 9003, 2250750))

    env["seq_num"] = 9999       # AAD mismatch
    tampered = json.dumps(env)

    verified, reason = verify_locally(tampered)
    record("AAD Tamper Detected", not verified,
           f"GCM rejected (AAD mismatch): {reason}" if not verified
           else "DANGER: AAD-tampered envelope passed verification")


# ============================================================
# Test 4: Wrong key
# ============================================================
def test_wrong_key():
    print("\n--- Test 4: Wrong Key Rejection ---")
    inner = build_inner_json(25.3, 48.7, duty=8000, period=10000)
    # Encrypt with WRONG_KEY -- a legitimate envelope from an
    # unauthorized source -- and try to verify with CORRECT_KEY.
    env = gcm_wrap(inner, DEVICE_ID, 9004, 2251000, key=WRONG_KEY)

    verified, reason = verify_locally(env, key=CORRECT_KEY)
    record("Wrong Key Rejected", not verified,
           f"GCM rejected: {reason}" if not verified
           else "DANGER: wrong-key envelope passed verification")


# ============================================================
# Test 5: Missing ciphertext field
# ============================================================
def test_missing_ciphertext():
    print("\n--- Test 5: Missing Ciphertext Field ---")
    env = {
        "schema_version": "2.0.0",
        "device_id": DEVICE_ID,
        "seq_num": 9005,
        "timestamp_ms": 2251250,
        # ciphertext omitted
    }
    verified, reason = verify_locally(json.dumps(env))
    record("Missing Field Flagged", not verified,
           f"Rejected: {reason}" if not verified
           else "DANGER: envelope without ciphertext passed verification")


# ============================================================
# Test 6: Broker round-trip (valid envelope survives relay)
# ============================================================
def test_broker_roundtrip():
    print("\n--- Test 6: Broker Round-Trip (valid envelope) ---")
    if not os.path.exists(CA_CERT):
        record("Broker Roundtrip", False, "CA cert not found, skipping")
        return

    inner = build_inner_json(25.3, 48.7, duty=9000, period=10000)
    env = gcm_wrap(inner, DEVICE_ID, 9006, 2251500)

    ok, detail = roundtrip_test("test_gcm_rt", env, True)
    record("Valid Envelope Roundtrip", ok,
           "Survived broker relay + GCM verified" if ok else detail)


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    if not os.path.exists(CA_CERT):
        print(f"WARNING: CA certificate not found at {CA_CERT}")
        print("Run: cd broker/certs && ./generate_certs.sh")
        print("Skipping broker round-trip test (other tests will still run).\n")

    print("=" * 55)
    print("  MQTT Data Integrity Tests (Week 11: AES-128-GCM)")
    print("=" * 55)

    test_valid_envelope()
    test_tampered_ciphertext()
    test_tampered_aad()
    test_wrong_key()
    test_missing_ciphertext()
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
