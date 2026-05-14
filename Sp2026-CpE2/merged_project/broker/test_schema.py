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
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

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

# Week 10 merge: AES-128 ECB key (matches AES_KEY[] in mqtt_client_app.c)
AES_KEY_BYTES = b"LabKey12LabKey12"

SUPPORTED_SCHEMA_VERSIONS = {"1.0.0", "1.1.0"}

results = []


def aes_wrap(json_str: str) -> str:
    """Encode plaintext JSON as raw uppercase hex ciphertext -- the
    Week 10 wire format used by mqtt_client_app.c after the prefix
    cleanup."""
    cipher = AES.new(AES_KEY_BYTES, AES.MODE_ECB)
    raw = cipher.encrypt(pad(json_str.encode("utf-8"), AES.block_size))
    return raw.hex().upper()


def sign_packet(key, device_id, seq, ts, temp, hum):
    canonical = f"{device_id}|{seq}|{ts}|{temp:.1f}|{hum:.1f}"
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


def build_packet(device_id, seq, ts, temp, hum, hmac_hex=None,
                 schema_version="1.0.0", include_version=True,
                 pwm_duty_us=None, pwm_period_us=None):
    pkt = {}
    if include_version and schema_version is not None:
        pkt["schema_version"] = schema_version
    telemetry = {"temperature_c": temp, "humidity": hum}
    if pwm_duty_us is not None:
        telemetry["pwm_duty_us"] = pwm_duty_us
    if pwm_period_us is not None:
        telemetry["pwm_period_us"] = pwm_period_us
    pkt.update({
        "device_id": device_id,
        "seq_num": seq,
        "timestamp_ms": ts,
        "telemetry": telemetry,
    })
    if hmac_hex is not None:
        pkt["hmac"] = hmac_hex
    return json.dumps(pkt)


def make_signed_packet(seq, ts, temp=25.3, hum=48.7,
                       schema_version="1.0.0", include_version=True,
                       pwm_duty_us=None, pwm_period_us=None):
    device = "CC3220SF_NODE_01"
    # HMAC canonical string is unchanged across v1.0.0 and v1.1.0:
    # PWM fields are intentionally excluded from the HMAC.
    h = sign_packet(CORRECT_KEY, device, seq, ts, temp, hum)
    return build_packet(device, seq, ts, temp, hum, h,
                        schema_version=schema_version,
                        include_version=include_version,
                        pwm_duty_us=pwm_duty_us,
                        pwm_period_us=pwm_period_us)


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
# Test 3b: v1.1.0 packet accepted (Week 10 merge)
# ============================================================
def test_v110_accepted():
    print("\n--- Test 3b: v1.1.0 Packet (with PWM fields) Accepted ---")
    pkt_json = make_signed_packet(31, 800,
                                  schema_version="1.1.0",
                                  pwm_duty_us=8000,
                                  pwm_period_us=10000)
    data = json.loads(pkt_json)

    accepted, status = check_version(data)
    record("v1.1.0 Accepted", accepted and status == "1.1.0",
           f"status={status}")

    telemetry = data.get("telemetry", {})
    record("PWM Fields Present",
           telemetry.get("pwm_duty_us") == 8000
           and telemetry.get("pwm_period_us") == 10000,
           f"pwm_duty_us={telemetry.get('pwm_duty_us')}, "
           f"pwm_period_us={telemetry.get('pwm_period_us')}")

    # Confirm v1.0.0 HMAC contract is preserved (PWM excluded from HMAC).
    canonical = (f"{data['device_id']}|{data['seq_num']}|{data['timestamp_ms']}"
                 f"|{telemetry['temperature_c']:.1f}|{telemetry['humidity']:.1f}")
    expected = hmac.new(CORRECT_KEY, canonical.encode(),
                        hashlib.sha256).hexdigest()
    record("v1.1.0 HMAC Contract Stable",
           hmac.compare_digest(expected, data["hmac"]),
           "PWM fields excluded from HMAC, v1.0.0 contract preserved")


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
# Test 5: AES-wrapped v1.1.0 broker roundtrip (Week 10 merge)
# ============================================================
def test_aes_v110_roundtrip():
    print("\n--- Test 5: AES-Wrapped v1.1.0 Broker Roundtrip ---")

    if not os.path.exists(CA_CERT):
        record("AES v1.1.0 Roundtrip", False, "CA cert not found, skipping")
        return

    pkt_json = make_signed_packet(5, 1500,
                                  schema_version="1.1.0",
                                  pwm_duty_us=9000,
                                  pwm_period_us=10000)
    aes_payload = aes_wrap(pkt_json)

    received = []
    done = threading.Event()

    def on_connect(client, ud, flags, rc):
        if rc == 0:
            client.subscribe(TOPIC, qos=0)

    def on_message(client, ud, msg):
        try:
            received.append(msg.payload.decode("utf-8"))
        except Exception:
            pass
        if len(received) >= 1:
            done.set()

    c = mqtt.Client(client_id="test_schema_aes_rt")
    c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)
    c.on_connect = on_connect
    c.on_message = on_message

    try:
        c.connect(BROKER_IP, TLS_PORT, 60)
        c.loop_start()
        time.sleep(1)

        c.publish(TOPIC, aes_payload, qos=0)
        done.wait(timeout=8)
        c.loop_stop()
        c.disconnect()

        if len(received) == 0:
            record("AES v1.1.0 Roundtrip", False, "No message received")
            return

        relayed = received[0]
        if not all(c in "0123456789ABCDEF" for c in relayed):
            record("AES v1.1.0 Roundtrip", False,
                   "Broker relayed non-hex payload")
            return

        cipher = AES.new(AES_KEY_BYTES, AES.MODE_ECB)
        raw = bytes.fromhex(relayed)
        decrypted = cipher.decrypt(raw)
        pad_byte = decrypted[-1]
        plain = decrypted[:-pad_byte].decode("utf-8")
        data = json.loads(plain)

        sv = data.get("schema_version")
        duty = data.get("telemetry", {}).get("pwm_duty_us")
        record("AES v1.1.0 Roundtrip",
               sv == "1.1.0" and duty == 9000,
               f"schema={sv}, pwm_duty_us={duty}")

    except Exception as e:
        record("AES v1.1.0 Roundtrip", False, f"Connection error: {e}")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 55)
    print("  Schema Version Validation Tests (Weeks 9 + 10)")
    print("=" * 55)

    test_versioned_accepted()
    test_legacy_accepted()
    test_unknown_rejected()
    test_v110_accepted()
    test_broker_roundtrip()
    test_aes_v110_roundtrip()

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
