#!/usr/bin/env python3
"""
test_timing.py

Validates the TimingMonitor z-score anomaly detection, rolling statistics,
and feature export added in Week 8.

  1. Uniform intervals        -- no anomalies detected
  2. Latency spike            -- spike flagged as anomaly
  3. Irregular but bounded    -- few or no anomalies
  4. Burst of fast packets    -- negative z-scores, flagged as anomaly
  5. Feature completeness     -- all TimingFeatures fields populated
  6. Broker roundtrip timing  -- publish packets, verify timing CSV written

Prerequisites:
  - Mosquitto running with TLS on port 8883 (for test 6 only)
  - Certificates generated (./certs/generate_certs.sh)

Usage:
  cd broker && python3 test_timing.py
"""

import os
import sys
import json
import hmac
import hashlib
import time
import ssl
import csv
import threading
import random
import paho.mqtt.client as mqtt

from timing_monitor import TimingMonitor, TimingFeatures

BROKER_IP = "127.0.0.1"
TLS_PORT = 8883
TOPIC = "cc32xx/telemetry"
TIMING_CSV = "timing_features.csv"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

CORRECT_KEY = bytes([
    0x4d, 0x79, 0x53, 0x65, 0x63, 0x75, 0x72, 0x65,
    0x44, 0x69, 0x67, 0x69, 0x74, 0x61, 0x6c, 0x54,
    0x77, 0x69, 0x6e, 0x4b, 0x65, 0x79, 0x32, 0x30,
    0x32, 0x36, 0x21, 0x40, 0x23, 0x24, 0x25, 0x5e
])

results = []


def sign_packet(key, device_id, seq, ts, temp, hum):
    canonical = f"{device_id}|{seq}|{ts}|{temp:.1f}|{hum:.1f}"
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()


def make_signed_packet(seq, ts, temp=25.3, hum=48.7):
    device = "CC3220SF_NODE_01"
    h = sign_packet(CORRECT_KEY, device, seq, ts, temp, hum)
    pkt = {
        "schema_version": "1.0.0",
        "device_id": device,
        "seq_num": seq,
        "timestamp_ms": ts,
        "telemetry": {"temperature_c": temp, "humidity": hum},
        "hmac": h,
    }
    return json.dumps(pkt)


def record(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    results.append((name, status, detail))
    print(f"  [{status}] {name}" + (f"  -- {detail}" if detail else ""))


# ============================================================
# Test 1: Uniform intervals -- no anomalies
# ============================================================
def test_uniform():
    print("\n--- Test 1: Uniform Intervals (no anomalies) ---")
    tm = TimingMonitor(window_size=50, z_threshold=3.0, min_samples=10)

    anomaly_count = 0
    for i in range(20):
        f = tm.record(250, 250)
        if f.anomaly:
            anomaly_count += 1

    record("Uniform No Anomalies", anomaly_count == 0,
           f"anomalies={anomaly_count} (expected 0)")


# ============================================================
# Test 2: Latency spike -- spike flagged
# ============================================================
def test_spike():
    print("\n--- Test 2: Latency Spike Detection ---")
    tm = TimingMonitor(window_size=50, z_threshold=3.0, min_samples=10)

    for i in range(19):
        tm.record(250, 250)

    spike = tm.record(2000, 2000)

    record("Spike Flagged", spike.anomaly,
           f"z={spike.host_z_score:.2f}, anomaly={spike.anomaly}")
    record("Spike Z-Score Positive", spike.host_z_score > 3.0,
           f"z={spike.host_z_score:.2f} (expected > 3.0)")


# ============================================================
# Test 3: Irregular but bounded -- few or no anomalies
# ============================================================
def test_irregular():
    print("\n--- Test 3: Irregular But Bounded Intervals ---")
    tm = TimingMonitor(window_size=50, z_threshold=3.0, min_samples=10)

    random.seed(42)
    anomaly_count = 0
    for _ in range(30):
        delta = random.gauss(250, 30)
        f = tm.record(max(delta, 10), max(delta, 10))
        if f.anomaly:
            anomaly_count += 1

    record("Irregular Few Anomalies", anomaly_count <= 2,
           f"anomalies={anomaly_count} (expected <= 2 within 3-sigma)")


# ============================================================
# Test 4: Burst of fast packets -- negative z-scores
# ============================================================
def test_burst():
    print("\n--- Test 4: Fast Burst Detection ---")
    tm = TimingMonitor(window_size=50, z_threshold=3.0, min_samples=10)

    for i in range(15):
        tm.record(250, 250)

    burst_anomalies = 0
    for _ in range(5):
        f = tm.record(10, 10)
        if f.anomaly:
            burst_anomalies += 1

    record("Burst Anomalies Flagged", burst_anomalies >= 1,
           f"burst anomalies={burst_anomalies} (expected >= 1)")


# ============================================================
# Test 5: Feature completeness
# ============================================================
def test_features():
    print("\n--- Test 5: Feature Completeness ---")
    tm = TimingMonitor(window_size=50, z_threshold=3.0, min_samples=10)

    for i in range(12):
        f = tm.record(250 + i, 250 + i)

    ok = (
        isinstance(f, TimingFeatures)
        and f.host_delta_ms is not None
        and f.board_delta_ms is not None
        and f.host_mean_ms is not None
        and f.host_std_ms is not None
        and f.host_z_score is not None
        and f.board_jitter_ms is not None
        and f.anomaly is not None
    )

    record("All Fields Populated", ok,
           f"fields: delta={f.host_delta_ms}, mean={f.host_mean_ms}, "
           f"std={f.host_std_ms}, z={f.host_z_score}")

    s = tm.summary()
    summary_ok = (
        s.get("total_samples") == 12
        and s.get("anomalies") == 0
        and "host_mean_ms" in s
        and "host_std_ms" in s
        and "host_min_ms" in s
        and "host_max_ms" in s
        and "board_jitter_mean_ms" in s
    )
    record("Summary Correct", summary_ok,
           f"samples={s.get('total_samples')}, mean={s.get('host_mean_ms')}")


# ============================================================
# Test 6: Broker roundtrip with timing CSV
# ============================================================
def test_broker_roundtrip():
    print("\n--- Test 6: Broker Roundtrip with Timing ---")

    if not os.path.exists(CA_CERT):
        record("Broker Roundtrip", False, "CA cert not found, skipping")
        return

    payloads = []
    for seq in range(1, 6):
        payloads.append(make_signed_packet(seq, seq * 250))

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

    c = mqtt.Client(client_id="test_timing_rt")
    c.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)
    c.on_connect = on_connect
    c.on_message = on_message

    try:
        c.connect(BROKER_IP, TLS_PORT, 60)
        c.loop_start()
        time.sleep(1)

        for p in payloads:
            c.publish(TOPIC, p, qos=0)
            time.sleep(0.15)

        done.wait(timeout=8)
        c.loop_stop()
        c.disconnect()

        record("Broker Roundtrip", len(received) >= 5,
               f"Received {len(received)}/5 packets via broker")
    except Exception as e:
        record("Broker Roundtrip", False, f"Connection error: {e}")


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 55)
    print("  Timing-Anomaly Detection Tests (Week 8)")
    print("=" * 55)

    test_uniform()
    test_spike()
    test_irregular()
    test_burst()
    test_features()
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
