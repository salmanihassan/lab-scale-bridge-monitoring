import paho.mqtt.client as mqtt
import ssl
import json
import csv
import time
import hmac
import hashlib
import os
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from timing_monitor import TimingMonitor

# --- Configuration ---
BROKER_IP = "127.0.0.1"
BROKER_PORT = 8883
TOPIC = "cc32xx/telemetry"
CSV_FILENAME = "raw_dataset_encrypted.csv"
TIMING_CSV_FILENAME = "timing_features.csv"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

# Pre-shared key -- must match HMAC_KEY in hmac_auth.h exactly
HMAC_KEY = bytes([
    0x4d, 0x79, 0x53, 0x65, 0x63, 0x75, 0x72, 0x65,
    0x44, 0x69, 0x67, 0x69, 0x74, 0x61, 0x6c, 0x54,
    0x77, 0x69, 0x6e, 0x4b, 0x65, 0x79, 0x32, 0x30,
    0x32, 0x36, 0x21, 0x40, 0x23, 0x24, 0x25, 0x5e
])

# --- AES-128 ECB key (Week 10 merge) -------------------------------
# Must match AES_KEY[] in mqtt_client_app.c byte-for-byte.
# Firmware encrypts the JSON payload BEFORE publishing on MQTT/TLS, so
# the broker only ever sees [AES] <hex> ciphertext lines.
AES_KEY = b"LabKey12LabKey12"   # 16 bytes
AES_PREFIX = "[AES]"

# --- Freshness Configuration ---
MAX_STALENESS_SEC = 30.0
REBOOT_SEQ_THRESHOLD = 5

# --- Schema Versioning ---
# v1.0.0 -- baseline (temperature_c, humidity)
# v1.1.0 -- Week 10: adds optional pwm_duty_us, pwm_period_us inside telemetry
SUPPORTED_SCHEMA_VERSIONS = {"1.0.0", "1.1.0"}

# --- Tracking State ---
packets_received = 0
packets_accepted = 0
packets_lost = 0
hmac_pass = 0
hmac_fail = 0
aes_fail = 0
replays_detected = 0
duplicates_detected = 0
stale_detected = 0
ooo_detected = 0
reboots_detected = 0

last_accepted_seq = None
last_accepted_board_ts = None
last_accepted_wall_time = None
start_time = None
schema_version_mismatches = 0

# --- Timing Monitor ---
timing = TimingMonitor()

# Initialize CSV Files with Headers
with open(CSV_FILENAME, mode='a', newline='') as file:
    writer = csv.writer(file)
    if file.tell() == 0:
        writer.writerow(["Host_Timestamp", "Schema_Version", "Device_ID",
                         "Seq_Num", "Board_Time_ms", "Temp_C",
                         "Humidity_%", "HMAC_Verified",
                         "Freshness_Status", "Host_Delta_ms",
                         "PWM_Duty_us", "PWM_Period_us"])

with open(TIMING_CSV_FILENAME, mode='a', newline='') as file:
    writer = csv.writer(file)
    if file.tell() == 0:
        writer.writerow(["Host_Timestamp", "Seq_Num",
                         "Host_Delta_ms", "Board_Delta_ms",
                         "Host_Mean_ms", "Host_Std_ms",
                         "Host_Z_Score", "Board_Jitter_ms",
                         "Timing_Anomaly"])


def decrypt_aes_payload(payload_text):
    """
    Decode an `[AES] <hex>` line into the underlying JSON string.

    Returns the decrypted plaintext (UTF-8) on success, or None if the
    line is not in [AES] format, the hex is malformed, or AES decrypt /
    PKCS7 unpad fails (which happens whenever the firmware's CORRUPT
    fault flips a byte in ciphertext or when an attacker injects
    garbage on the broker topic).
    """
    body = payload_text.strip()
    if not body.startswith(AES_PREFIX):
        return None
    hex_str = body[len(AES_PREFIX):].strip()
    try:
        raw = bytes.fromhex(hex_str)
    except ValueError:
        return None
    try:
        cipher = AES.new(AES_KEY, AES.MODE_ECB)
        return unpad(cipher.decrypt(raw), AES.block_size).decode("utf-8")
    except (ValueError, KeyError):
        return None


def verify_hmac(data):
    """Reconstruct the canonical string and verify the HMAC tag."""
    received_hmac = data.get("hmac")
    if received_hmac is None:
        return False, "missing"

    device_id = data.get("device_id", "UNKNOWN")
    seq_num = data.get("seq_num", 0)
    board_time = data.get("timestamp_ms", 0)
    telemetry = data.get("telemetry", {})
    temp = telemetry.get("temperature_c", 0.0)
    humidity = telemetry.get("humidity", 0.0)

    canonical = f"{device_id}|{seq_num}|{board_time}|{temp:.1f}|{humidity:.1f}"
    expected = hmac.new(HMAC_KEY, canonical.encode(), hashlib.sha256).hexdigest()

    if hmac.compare_digest(expected, received_hmac):
        return True, "ok"
    return False, "mismatch"


def check_freshness(seq_num, board_time):
    """
    Validate packet freshness against the tracking state.
    Returns (accepted: bool, status: str).
    """
    global last_accepted_seq, last_accepted_board_ts, last_accepted_wall_time
    global replays_detected, duplicates_detected, stale_detected
    global ooo_detected, reboots_detected, packets_lost

    now = time.time()

    # First packet ever — always accept
    if last_accepted_seq is None:
        return True, "ACCEPTED"

    # --- Replay / Duplicate / Reboot detection ---
    if seq_num <= last_accepted_seq:
        if seq_num == last_accepted_seq:
            duplicates_detected += 1
            return False, "DUPLICATE"

        # seq_num < last_accepted_seq: could be replay or reboot
        if seq_num <= REBOOT_SEQ_THRESHOLD and last_accepted_seq > REBOOT_SEQ_THRESHOLD:
            reboots_detected += 1
            return True, "REBOOT_RESET"

        replays_detected += 1
        return False, "REPLAY"

    # --- Board timestamp monotonicity ---
    if last_accepted_board_ts is not None and board_time <= last_accepted_board_ts:
        replays_detected += 1
        return False, "REPLAY"

    # --- Host-side staleness ---
    if last_accepted_wall_time is not None:
        delta = now - last_accepted_wall_time
        if delta > MAX_STALENESS_SEC:
            stale_detected += 1
            return False, "STALE"

    # --- Gap detection (packet loss) ---
    expected_next = last_accepted_seq + 1
    if seq_num > expected_next:
        gap = seq_num - expected_next
        packets_lost += gap
        ooo_detected += 1
        print(f"  [WARNING] Packet gap detected! Lost {gap} packet(s) "
              f"(expected seq {expected_next}, got {seq_num}).")
        return True, "OOO_GAP"

    return True, "ACCEPTED"


def accept_packet(seq_num, board_time):
    """Update tracking state after accepting a packet."""
    global last_accepted_seq, last_accepted_board_ts, last_accepted_wall_time
    last_accepted_seq = seq_num
    last_accepted_board_ts = board_time
    last_accepted_wall_time = time.time()


def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Connected to Mosquitto Broker at {BROKER_IP}:{BROKER_PORT} (TLS)")
        client.subscribe(TOPIC)
        print(f"Subscribed to topic: {TOPIC}")
        print(f"CA certificate: {CA_CERT}")
        print(f"Payload format: AES-128-ECB inside MQTT/TLS (Week 10 merge)")
        print(f"Freshness window: {MAX_STALENESS_SEC}s | "
              f"Reboot threshold: seq <= {REBOOT_SEQ_THRESHOLD}")
        print(f"Timing monitor: window={timing.window_size}, "
              f"z-threshold={timing.z_threshold}")
        print(f"Supported schema versions: "
              f"{', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))} "
              f"(+ legacy)")
        print("Waiting for telemetry...\n")
    else:
        print(f"Failed to connect. Return code: {rc}")


def on_message(client, userdata, msg):
    global packets_received, packets_accepted, hmac_pass, hmac_fail, aes_fail
    global start_time, schema_version_mismatches

    now = time.time()
    if packets_received == 0:
        start_time = now

    packets_received += 1
    host_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    # --- Decode wire payload: prefer [AES] (Week 10 wire format) but
    #     fall through to plaintext JSON for backward compatibility with
    #     legacy v1.0.0 firmware and the test_*.py harnesses.
    try:
        payload = msg.payload.decode('utf-8')
    except UnicodeDecodeError:
        print(f"[DECODE FAIL] [{host_timestamp}] non-UTF8 payload -- DISCARDED")
        return

    if payload.lstrip().startswith(AES_PREFIX):
        plaintext = decrypt_aes_payload(payload)
        if plaintext is None:
            aes_fail += 1
            _log_csv(host_timestamp, "unknown", "UNKNOWN", 0, 0,
                     "N/A", "N/A", False, "AES_FAIL", 0, "", "")
            print(f"[AES FAIL] [{host_timestamp}] -- ciphertext rejected "
                  f"(corrupt or wrong key) -- DISCARDED")
            return
        payload = plaintext

    try:
        data = json.loads(payload)

        schema_version = data.get("schema_version")
        device_id = data.get("device_id", "UNKNOWN")
        seq_num = data.get("seq_num", 0)
        board_time = data.get("timestamp_ms", 0)

        telemetry = data.get("telemetry", {})
        temp = telemetry.get("temperature_c", "N/A")
        humidity = telemetry.get("humidity", "N/A")
        pwm_duty   = telemetry.get("pwm_duty_us", "")
        pwm_period = telemetry.get("pwm_period_us", "")

        # --- Schema Version Validation ---
        if schema_version is not None and schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            schema_version_mismatches += 1
            _log_csv(host_timestamp, schema_version, device_id, seq_num,
                     board_time, temp, humidity, False, "SCHEMA_UNKNOWN", 0,
                     pwm_duty, pwm_period)
            print(f"[SCHEMA UNKNOWN: {schema_version}] [{host_timestamp}] "
                  f"Seq: {seq_num} -- DISCARDED")
            return

        version_tag = ""
        if schema_version is None:
            version_tag = "[LEGACY]"
            schema_version = "legacy"

        # --- HMAC Verification ---
        verified, reason = verify_hmac(data)
        if not verified:
            hmac_fail += 1
            freshness_status = "HMAC_FAIL"
            host_delta_ms = _host_delta_ms()
            _log_csv(host_timestamp, schema_version, device_id, seq_num,
                     board_time, temp, humidity, False, freshness_status,
                     host_delta_ms, pwm_duty, pwm_period)
            print(f"[HMAC FAIL: {reason}]{version_tag} [{host_timestamp}] "
                  f"Seq: {seq_num} | Temp: {temp}°C | Hum: {humidity}% "
                  f"-- DISCARDED")
            return

        hmac_pass += 1

        # --- Freshness Validation (only for HMAC-verified packets) ---
        accepted, freshness_status = check_freshness(seq_num, board_time)
        host_delta_ms = _host_delta_ms()

        # Compute board delta before updating tracker
        board_delta_ms = 0
        if last_accepted_board_ts is not None and accepted:
            board_delta_ms = board_time - last_accepted_board_ts

        if accepted:
            accept_packet(seq_num, board_time)
            packets_accepted += 1

            # --- Timing Analysis (only for accepted packets) ---
            if freshness_status == "REBOOT_RESET":
                timing.reset()

            features = timing.record(host_delta_ms, board_delta_ms)
            _log_timing_csv(host_timestamp, seq_num, features)

            tag = "[HMAC OK]"
            suffix = ""
            if freshness_status == "REBOOT_RESET":
                tag = "[HMAC OK][REBOOT]"
                suffix = " -- device reboot detected, tracker reset"
            elif freshness_status == "OOO_GAP":
                tag = "[HMAC OK][GAP]"
                suffix = ""

            if features.anomaly:
                tag += "[TIMING]"
                suffix += f" -- TIMING ALERT z={features.host_z_score:.1f}"
        else:
            tag = f"[HMAC OK][{freshness_status}]"
            suffix = " -- DISCARDED"

        _log_csv(host_timestamp, schema_version, device_id, seq_num,
                 board_time, temp, humidity, True, freshness_status,
                 host_delta_ms, pwm_duty, pwm_period)

        pwm_suffix = ""
        if pwm_duty != "" and pwm_period != "":
            pwm_suffix = f" | Duty: {pwm_duty}us"
        print(f"{tag}{version_tag} [{host_timestamp}] Seq: {seq_num} | "
              f"Temp: {temp}°C | Hum: {humidity}%{pwm_suffix}{suffix}")

    except json.JSONDecodeError:
        print(f"Failed to parse JSON: {msg.payload}")
    except Exception as e:
        print(f"Error processing message: {e}")


def _host_delta_ms():
    """Milliseconds since last accepted packet (host wall-clock)."""
    if last_accepted_wall_time is None:
        return 0
    return int((time.time() - last_accepted_wall_time) * 1000)


def _log_csv(host_ts, schema_ver, device_id, seq, board_ts, temp, hum,
             hmac_ok, freshness, delta_ms, pwm_duty="", pwm_period=""):
    with open(CSV_FILENAME, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([host_ts, schema_ver, device_id, seq, board_ts,
                         temp, hum, hmac_ok, freshness, delta_ms,
                         pwm_duty, pwm_period])


def _log_timing_csv(host_ts, seq, features):
    with open(TIMING_CSV_FILENAME, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([host_ts, seq,
                         features.host_delta_ms, features.board_delta_ms,
                         features.host_mean_ms, features.host_std_ms,
                         features.host_z_score, features.board_jitter_ms,
                         features.anomaly])


# --- Setup MQTT Client ---
client = mqtt.Client(client_id="MacHostReceiver")
client.on_connect = on_connect
client.on_message = on_message

client.tls_set(ca_certs=CA_CERT, tls_version=ssl.PROTOCOL_TLSv1_2)

print("Starting Encrypted & Authenticated Data Ingestion Engine...")
print(f"Connecting to {BROKER_IP}:{BROKER_PORT} with TLS...")
client.connect(BROKER_IP, BROKER_PORT, 60)

try:
    client.loop_forever()
except KeyboardInterrupt:
    print("\n--- Ingestion Stopped ---")

    if start_time and packets_received > 0:
        elapsed_time = time.time() - start_time
        throughput = packets_accepted / elapsed_time if elapsed_time > 0 else 0
        total_expected = packets_accepted + packets_lost
        loss_rate = (packets_lost / total_expected) * 100 if total_expected > 0 else 0
        hmac_total = hmac_pass + hmac_fail
        integrity_rate = (hmac_pass / hmac_total) * 100 if hmac_total > 0 else 0

        print("\n--- Performance & Integrity Summary ---")
        print(f"Total Time:           {elapsed_time:.2f} seconds")
        print(f"Packets Received:     {packets_received}")
        print(f"Packets Accepted:     {packets_accepted}")
        print(f"Packets Lost (gaps):  {packets_lost}")
        print(f"Throughput:           {throughput:.2f} packets/sec")
        print(f"Packet Loss Rate:     {loss_rate:.2f}%")

        print("\n--- Authentication ---")
        print(f"HMAC Verified (pass): {hmac_pass}")
        print(f"HMAC Failed:          {hmac_fail}")
        print(f"AES Decrypt Failed:   {aes_fail}")
        print(f"Integrity Rate:       {integrity_rate:.2f}%")

        print("\n--- Freshness & Replay ---")
        print(f"Replays Detected:     {replays_detected}")
        print(f"Duplicates Detected:  {duplicates_detected}")
        print(f"Stale Packets:        {stale_detected}")
        print(f"Out-of-Order/Gaps:    {ooo_detected}")
        print(f"Reboots Detected:     {reboots_detected}")
        print(f"Schema Mismatches:    {schema_version_mismatches}")

        ts = timing.summary()
        if ts:
            print("\n--- Timing Analysis ---")
            print(f"Timing Samples:       {ts['total_samples']}")
            print(f"Timing Anomalies:     {ts['anomalies']}")
            print(f"Host IAT Mean:        {ts['host_mean_ms']:.2f} ms")
            print(f"Host IAT Std:         {ts['host_std_ms']:.2f} ms")
            print(f"Host IAT Min:         {ts['host_min_ms']:.2f} ms")
            print(f"Host IAT Max:         {ts['host_max_ms']:.2f} ms")
            print(f"Board Jitter Mean:    {ts['board_jitter_mean_ms']:.2f} ms")

        print(f"\nDatasets saved to:    {CSV_FILENAME}, {TIMING_CSV_FILENAME}")
