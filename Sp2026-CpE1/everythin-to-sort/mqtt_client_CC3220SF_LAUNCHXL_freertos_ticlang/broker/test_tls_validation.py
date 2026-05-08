#!/usr/bin/env python3
"""
test_tls_validation.py

Validates TLS configuration for the MQTT broker by running three test scenarios:
  1. Valid TLS   -- connect with the correct CA cert on port 8883
  2. Wrong CA    -- connect with a bogus CA cert (should be rejected)
  3. No TLS      -- connect plaintext to the TLS port (should fail)

Prerequisites:
  - Mosquitto running with TLS on port 8883 (./broker.sh)
  - Certificates generated (./certs/generate_certs.sh)

Usage:
  cd broker && python3 test_tls_validation.py
"""

import paho.mqtt.client as mqtt
import ssl
import os
import sys
import json
import time
import tempfile
import threading

BROKER_IP = "127.0.0.1"
TLS_PORT = 8883
PLAINTEXT_PORT = 1883
TOPIC = "cc32xx/telemetry"
TIMEOUT = 8

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

results = []


def _make_fake_ca():
    """Generate a throwaway self-signed CA cert that did NOT sign the server cert."""
    import subprocess
    tmp_key = tempfile.NamedTemporaryFile(suffix=".key", delete=False)
    tmp_cert = tempfile.NamedTemporaryFile(suffix=".pem", delete=False)
    tmp_key.close()
    tmp_cert.close()
    subprocess.run([
        "openssl", "genrsa", "-out", tmp_key.name, "2048"
    ], capture_output=True, check=True)
    subprocess.run([
        "openssl", "req", "-x509", "-new", "-nodes",
        "-key", tmp_key.name, "-sha256", "-days", "1",
        "-out", tmp_cert.name,
        "-subj", "/CN=WRONG-CA"
    ], capture_output=True, check=True)
    return tmp_cert.name, tmp_key.name


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail else ""))


# ============================================================
# Test 1: Valid TLS connection
# ============================================================
def test_valid_tls():
    print("\n--- Test 1: Valid TLS Connection ---")
    received = threading.Event()
    payload_data = {}

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(TOPIC, qos=0)
        else:
            record("Valid TLS Connect", False, f"CONNACK rc={rc}")
            client.disconnect()

    def on_message(client, userdata, msg):
        try:
            payload_data["raw"] = msg.payload.decode("utf-8")
            payload_data["json"] = json.loads(payload_data["raw"])
            received.set()
        except Exception as e:
            payload_data["error"] = str(e)
            received.set()

    client = mqtt.Client(client_id="test_valid_tls")
    client.on_connect = on_connect
    client.on_message = on_message
    client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)

    try:
        client.connect(BROKER_IP, TLS_PORT, 60)
        client.loop_start()

        # Publish a test message through the same TLS connection
        time.sleep(1)
        test_payload = json.dumps({
            "device_id": "TLS_TEST",
            "seq_num": 0,
            "timestamp_ms": 0,
            "telemetry": {"temperature_c": 99.9, "humidity": 99.9}
        })
        client.publish(TOPIC, test_payload, qos=0)

        got_msg = received.wait(timeout=TIMEOUT)
        client.loop_stop()
        client.disconnect()

        if got_msg and "json" in payload_data:
            record("Valid TLS Connect", True, "TLS handshake succeeded")
            record("Valid TLS Decrypt", True,
                   f"Payload decrypted: device_id={payload_data['json'].get('device_id')}")
        elif got_msg and "error" in payload_data:
            record("Valid TLS Connect", True, "Connected but payload parse failed")
            record("Valid TLS Decrypt", False, payload_data["error"])
        else:
            record("Valid TLS Connect", True, "Connected")
            record("Valid TLS Decrypt", False, "No message received within timeout")
    except Exception as e:
        record("Valid TLS Connect", False, str(e))


# ============================================================
# Test 2: Wrong CA certificate
# ============================================================
def test_wrong_ca():
    print("\n--- Test 2: Wrong CA Certificate ---")
    fake_cert, fake_key = _make_fake_ca()
    connected = threading.Event()
    error_caught = {"value": False}

    def on_connect(client, userdata, flags, rc):
        connected.set()

    client = mqtt.Client(client_id="test_wrong_ca")
    client.on_connect = on_connect
    client.tls_set(ca_certs=fake_cert, tls_version=ssl.PROTOCOL_TLSv1_2)

    try:
        client.connect(BROKER_IP, TLS_PORT, 60)
        client.loop_start()
        got_conn = connected.wait(timeout=TIMEOUT)
        client.loop_stop()
        client.disconnect()

        if got_conn:
            record("Wrong CA Rejected", False,
                   "Connection SUCCEEDED with wrong CA -- broker may not verify clients")
        else:
            record("Wrong CA Rejected", True,
                   "Connection timed out (SSL handshake failed as expected)")
    except ssl.SSLError as e:
        record("Wrong CA Rejected", True, f"SSLError: {e}")
    except Exception as e:
        record("Wrong CA Rejected", True, f"Rejected: {type(e).__name__}: {e}")
    finally:
        os.unlink(fake_cert)
        os.unlink(fake_key)


# ============================================================
# Test 3: Plaintext to TLS port
# ============================================================
def test_no_tls():
    print("\n--- Test 3: Plaintext to TLS Port ---")
    connected = threading.Event()

    def on_connect(client, userdata, flags, rc):
        connected.set()

    client = mqtt.Client(client_id="test_no_tls")
    client.on_connect = on_connect

    try:
        client.connect(BROKER_IP, TLS_PORT, 60)
        client.loop_start()
        got_conn = connected.wait(timeout=TIMEOUT)
        client.loop_stop()
        client.disconnect()

        if got_conn:
            record("Plaintext Rejected", False,
                   "Plaintext connection SUCCEEDED on TLS port -- misconfiguration!")
        else:
            record("Plaintext Rejected", True,
                   "Connection timed out (protocol mismatch as expected)")
    except Exception as e:
        record("Plaintext Rejected", True, f"Rejected: {type(e).__name__}: {e}")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    if not os.path.exists(CA_CERT):
        print(f"ERROR: CA certificate not found at {CA_CERT}")
        print("Run: cd broker/certs && ./generate_certs.sh")
        sys.exit(1)

    print("=" * 55)
    print("  MQTT TLS Validation Tests")
    print("=" * 55)

    test_valid_tls()
    test_wrong_ca()
    test_no_tls()

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
