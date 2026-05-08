#!/usr/bin/env python3
"""
test_schema.py

Validates the schema-version handling in the v2.0.0 GCM wire format
(Week 11 upgrade).  After the AES-128-GCM AEAD migration, only the
v2.0.0 envelope is accepted on the wire -- legacy v1.x packets are
rejected because they lack the AAD-bound outer envelope structure.

  1. v2.0.0 envelope accepted              -- version present and recognized
  2. Unknown version rejected               -- unsupported version string
  3. v2.0.0 inner JSON includes telemetry   -- decrypt + parse OK
  4. Broker roundtrip (versioned)           -- v2.0.0 envelope survives relay

Prerequisites:
  - Mosquitto running with TLS on port 8883 (for test 4 only)
  - Certificates generated (./certs/generate_certs.sh)

Usage:
  cd broker && python3 test_schema.py
"""

import os
import sys
import json
import time
import ssl
import threading
import paho.mqtt.client as mqtt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

BROKER_IP = "127.0.0.1"
TLS_PORT = 8883
TOPIC = "cc32xx/telemetry"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

# Week 11 upgrade: AES-128-GCM key (matches AES_KEY[] in mqtt_client_app.c)
AES_KEY_BYTES = b"LabKey12LabKey12"
GCM_IV_LEN = 12
GCM_TAG_LEN = 16

DEVICE_ID = "CC3220SF_NODE_01"
SUPPORTED_SCHEMA_VERSIONS = {"2.0.0"}

results = []


def gcm_wrap(inner_json, device_id, seq, ts, key=AES_KEY_BYTES,
             schema_version="2.0.0"):
    """Encrypt + wrap into a v2.0.0 outer envelope (test helper)."""
    iv  = os.urandom(GCM_IV_LEN)
    aad = f"{device_id}|{seq}|{ts}".encode("utf-8")
    ct  = AESGCM(key).encrypt(iv, inner_json.encode("utf-8"), aad)
    blob = (iv + ct).hex().upper()
    return json.dumps({
        "schema_version": schema_version,
        "device_id": device_id,
        "seq_num": seq,
        "timestamp_ms": ts,
        "ciphertext": blob,
    })


def build_inner(temp, hum, duty=None, period=None,
                schema_version="2.0.0"):
    telemetry = {"temperature_c": temp, "humidity": hum}
    if duty is not None:
        telemetry["pwm_duty_us"] = duty
    if period is not None:
        telemetry["pwm_period_us"] = period
    return json.dumps({"schema_version": schema_version,
                       "telemetry": telemetry})


def make_envelope(seq, ts, temp=25.3, hum=48.7, duty=None, period=None,
                  schema_version="2.0.0", outer_schema_override=None):
    """Build a complete envelope.  `outer_schema_override` lets a test
    publish a wire-level mismatched schema_version while keeping the
    inner JSON consistent."""
    inner = build_inner(temp, hum, duty, period, schema_version)
    outer_sv = outer_schema_override if outer_schema_override is not None \
        else schema_version
    return gcm_wrap(inner, DEVICE_ID, seq, ts, schema_version=outer_sv)


def check_version(data):
    """Mirror host_receiver.py schema version validation logic."""
    sv = data.get("schema_version")
    if sv in SUPPORTED_SCHEMA_VERSIONS:
        return True, sv
    return False, f"SCHEMA_UNKNOWN:{sv}"


def decrypt_envelope(env_dict, key=AES_KEY_BYTES):
    """Standalone copy of host_receiver.decrypt_gcm_envelope() logic."""
    try:
        device_id = env_dict["device_id"]
        seq = env_dict["seq_num"]
        ts  = env_dict["timestamp_ms"]
        hex_blob = env_dict["ciphertext"]
    except KeyError:
        return None
    try:
        blob = bytes.fromhex(hex_blob)
    except ValueError:
        return None
    if len(blob) < GCM_IV_LEN + GCM_TAG_LEN:
        return None
    iv = blob[:GCM_IV_LEN]
    ct_and_tag = blob[GCM_IV_LEN:]
    aad = f"{device_id}|{seq}|{ts}".encode("utf-8")
    try:
        return AESGCM(key).decrypt(iv, ct_and_tag, aad).decode("utf-8")
    except InvalidTag:
        return None


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail else ""))


# ============================================================
# Test 1: v2.0.0 envelope accepted
# ============================================================
def test_versioned_accepted():
    print("\n--- Test 1: v2.0.0 Envelope Accepted ---")
    env_json = make_envelope(1, 250)
    data = json.loads(env_json)

    accepted, status = check_version(data)
    record("v2.0.0 Accepted", accepted and status == "2.0.0",
           f"status={status}")

    sv = data.get("schema_version")
    record("Version Field Present", sv == "2.0.0",
           f"schema_version={sv}")


# ============================================================
# Test 2: Unknown version rejected
# ============================================================
def test_unknown_rejected():
    print("\n--- Test 2: Unknown Version Rejected ---")
    env_json = make_envelope(2, 500, outer_schema_override="9.9.9")
    data = json.loads(env_json)

    accepted, status = check_version(data)
    record("Unknown Version Rejected", not accepted,
           f"status={status}")


# ============================================================
# Test 3: Inner JSON contains telemetry + PWM fields
# ============================================================
def test_inner_payload_shape():
    print("\n--- Test 3: Inner Telemetry Decrypts and Parses ---")
    env_json = make_envelope(3, 750, duty=8000, period=10000)
    data = json.loads(env_json)

    plaintext = decrypt_envelope(data)
    record("Inner Decrypt OK", plaintext is not None,
           "GCM tag verified" if plaintext else "Decrypt failed")

    if plaintext:
        inner = json.loads(plaintext)
        telemetry = inner.get("telemetry", {})
        record("Inner Telemetry Fields",
               telemetry.get("pwm_duty_us") == 8000
               and telemetry.get("pwm_period_us") == 10000,
               f"duty={telemetry.get('pwm_duty_us')}, "
               f"period={telemetry.get('pwm_period_us')}")
        record("Inner Schema Version",
               inner.get("schema_version") == "2.0.0",
               f"inner_schema={inner.get('schema_version')}")


# ============================================================
# Test 4: Broker roundtrip
# ============================================================
def test_broker_roundtrip():
    print("\n--- Test 4: Broker Roundtrip (v2.0.0 envelope) ---")

    if not os.path.exists(CA_CERT):
        record("Broker Roundtrip", False, "CA cert not found, skipping")
        return

    env_json = make_envelope(4, 1000, duty=9000, period=10000)
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

        c.publish(TOPIC, env_json, qos=0)
        done.wait(timeout=8)
        c.loop_stop()
        c.disconnect()

        if len(received) == 0:
            record("Broker Roundtrip", False, "No message received")
            return

        sv = received[0].get("schema_version")
        record("Broker Schema Survived", sv == "2.0.0",
               f"Received schema_version={sv}")

        plain = decrypt_envelope(received[0])
        record("Broker Roundtrip Decrypts",
               plain is not None,
               "GCM verified after relay" if plain else "Decrypt failed")
        if plain:
            inner = json.loads(plain)
            duty = inner.get("telemetry", {}).get("pwm_duty_us")
            record("Broker PWM Field Survived", duty == 9000,
                   f"pwm_duty_us={duty}")

    except Exception as e:
        record("Broker Roundtrip", False, f"Connection error: {e}")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 55)
    print("  Schema Version Validation Tests (Week 11: GCM)")
    print("=" * 55)

    test_versioned_accepted()
    test_unknown_rejected()
    test_inner_payload_shape()
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
