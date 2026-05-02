import paho.mqtt.client as mqtt
import ssl
import json
import csv
import time
import os
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from timing_monitor import TimingMonitor

# --- Configuration ---
BROKER_IP = "127.0.0.1"
BROKER_PORT = 8883
TOPIC = "cc32xx/telemetry"
CSV_FILENAME = "raw_dataset_encrypted.csv"
TIMING_CSV_FILENAME = "timing_features.csv"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CA_CERT = os.path.join(SCRIPT_DIR, "certs", "ca-cert.pem")

# --- AES-128-GCM key (Week 11 upgrade) ----------------------------------
# Must match AES_KEY[] in mqtt_client_app.c byte-for-byte.  The CC3220SF
# DTHE hardware crypto block encrypts each telemetry payload with this
# key and a fresh 12-byte nonce sourced from the NWP TRNG.  The 16-byte
# GCM authentication tag binds both the inner ciphertext and the AAD
# canonical "device_id|seq_num|timestamp_ms" to the published envelope.
AES_KEY = b"LabKey12LabKey12"   # 16 bytes -> AES-128
GCM_IV_LEN = 12
GCM_TAG_LEN = 16

# --- Freshness Configuration ---
MAX_STALENESS_SEC = 30.0
REBOOT_SEQ_THRESHOLD = 5

# --- Schema Versioning ---
# v1.0.0 -- baseline (temperature_c, humidity)
# v1.1.0 -- Week 10: adds optional pwm_duty_us, pwm_period_us inside telemetry
# v2.0.0 -- Week 11: AES-128-GCM AEAD, outer/inner envelope split.
#                    v1.x packets are NO LONGER ACCEPTED on the wire.
SUPPORTED_SCHEMA_VERSIONS = {"2.0.0"}

# --- Tracking State ---
packets_received = 0
packets_accepted = 0
packets_lost = 0
gcm_pass = 0
gcm_fail = 0
inner_parse_fail = 0
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
                         "Humidity_%", "GCM_Verified",
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


def decrypt_gcm_envelope(envelope):
    """
    Decrypt the inner JSON from a v2.0.0 outer envelope dict.

    Returns the inner plaintext (UTF-8 string) on success, or None if
    any step fails (missing field, malformed hex, GCM InvalidTag, AAD
    mismatch).  AAD is reconstructed identically to the firmware:
        f"{device_id}|{seq_num}|{timestamp_ms}".encode("utf-8")
    so any tampering with those outer fields fails verification.
    """
    if not isinstance(envelope, dict):
        return None
    try:
        device_id = envelope["device_id"]
        seq_num = envelope["seq_num"]
        timestamp_ms = envelope["timestamp_ms"]
        hex_blob = envelope["ciphertext"]
    except (KeyError, TypeError):
        return None

    try:
        blob = bytes.fromhex(hex_blob)
    except (ValueError, TypeError):
        return None

    if len(blob) < GCM_IV_LEN + GCM_TAG_LEN:
        return None

    iv = blob[:GCM_IV_LEN]
    ct_and_tag = blob[GCM_IV_LEN:]

    aad = f"{device_id}|{seq_num}|{timestamp_ms}".encode("utf-8")

    try:
        plaintext = AESGCM(AES_KEY).decrypt(iv, ct_and_tag, aad)
    except InvalidTag:
        return None
    except Exception:
        return None

    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError:
        return None


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
        print("Payload format: AES-128-GCM AEAD inside MQTT/TLS (Week 11 upgrade)")
        print(f"  AAD = device_id|seq_num|timestamp_ms (bound to GCM tag)")
        print(f"Freshness window: {MAX_STALENESS_SEC}s | "
              f"Reboot threshold: seq <= {REBOOT_SEQ_THRESHOLD}")
        print(f"Timing monitor: window={timing.window_size}, "
              f"z-threshold={timing.z_threshold}")
        print(f"Supported schema versions: "
              f"{', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}")
        print("Waiting for telemetry...\n")
    else:
        print(f"Failed to connect. Return code: {rc}")


def on_message(client, userdata, msg):
    global packets_received, packets_accepted
    global gcm_pass, gcm_fail, inner_parse_fail
    global start_time, schema_version_mismatches

    now = time.time()
    if packets_received == 0:
        start_time = now

    packets_received += 1
    host_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

    # --- Decode wire payload: every v2.0.0 publish is a JSON envelope.
    try:
        envelope_str = msg.payload.decode('utf-8')
    except UnicodeDecodeError:
        print(f"[DECODE FAIL] [{host_timestamp}] non-UTF8 payload -- DISCARDED")
        return

    try:
        envelope = json.loads(envelope_str)
    except json.JSONDecodeError:
        print(f"[ENVELOPE FAIL] [{host_timestamp}] not valid JSON -- DISCARDED")
        return

    schema_version = envelope.get("schema_version")
    device_id = envelope.get("device_id", "UNKNOWN")
    seq_num = envelope.get("seq_num", 0)
    board_time = envelope.get("timestamp_ms", 0)

    # --- Schema Version Validation ---
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        schema_version_mismatches += 1
        _log_csv(host_timestamp, schema_version, device_id, seq_num,
                 board_time, "N/A", "N/A", False, "SCHEMA_UNKNOWN", 0,
                 "", "")
        print(f"[SCHEMA UNKNOWN: {schema_version}] [{host_timestamp}] "
              f"Seq: {seq_num} -- DISCARDED")
        return

    # --- AES-128-GCM Authenticated Decryption ---
    plaintext = decrypt_gcm_envelope(envelope)
    if plaintext is None:
        gcm_fail += 1
        _log_csv(host_timestamp, schema_version, device_id, seq_num,
                 board_time, "N/A", "N/A", False, "GCM_FAIL", 0, "", "")
        print(f"[GCM FAIL] [{host_timestamp}] Seq: {seq_num} "
              f"-- envelope rejected (corrupt ciphertext, AAD mismatch, "
              f"or wrong key) -- DISCARDED")
        return

    gcm_pass += 1

    try:
        inner = json.loads(plaintext)
    except json.JSONDecodeError:
        # GCM tag verified but inner JSON is corrupted (e.g. firmware
        # CORRUPT fault flipped a byte before encryption).
        inner_parse_fail += 1
        _log_csv(host_timestamp, schema_version, device_id, seq_num,
                 board_time, "N/A", "N/A", True, "INNER_PARSE_FAIL", 0,
                 "", "")
        print(f"[JSON FAIL] [{host_timestamp}] Seq: {seq_num} "
              f"-- inner JSON parse failed (GCM-verified but corrupt) "
              f"-- DISCARDED")
        return

    telemetry = inner.get("telemetry", {})
    temp = telemetry.get("temperature_c", "N/A")
    humidity = telemetry.get("humidity", "N/A")
    pwm_duty = telemetry.get("pwm_duty_us", "")
    pwm_period = telemetry.get("pwm_period_us", "")

    # --- Freshness Validation (only for GCM-verified packets) ---
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

        tag = "[GCM OK]"
        suffix = ""
        if freshness_status == "REBOOT_RESET":
            tag = "[GCM OK][REBOOT]"
            suffix = " -- device reboot detected, tracker reset"
        elif freshness_status == "OOO_GAP":
            tag = "[GCM OK][GAP]"
            suffix = ""

        if features.anomaly:
            tag += "[TIMING]"
            suffix += f" -- TIMING ALERT z={features.host_z_score:.1f}"
    else:
        tag = f"[GCM OK][{freshness_status}]"
        suffix = " -- DISCARDED"

    _log_csv(host_timestamp, schema_version, device_id, seq_num,
             board_time, temp, humidity, True, freshness_status,
             host_delta_ms, pwm_duty, pwm_period)

    pwm_suffix = ""
    if pwm_duty != "" and pwm_period != "":
        pwm_suffix = f" | Duty: {pwm_duty}us"
    print(f"{tag} [{host_timestamp}] Seq: {seq_num} | "
          f"Temp: {temp}\u00b0C | Hum: {humidity}%{pwm_suffix}{suffix}")


def _host_delta_ms():
    """Milliseconds since last accepted packet (host wall-clock)."""
    if last_accepted_wall_time is None:
        return 0
    return int((time.time() - last_accepted_wall_time) * 1000)


def _log_csv(host_ts, schema_ver, device_id, seq, board_ts, temp, hum,
             gcm_ok, freshness, delta_ms, pwm_duty="", pwm_period=""):
    with open(CSV_FILENAME, mode='a', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([host_ts, schema_ver, device_id, seq, board_ts,
                         temp, hum, gcm_ok, freshness, delta_ms,
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
        gcm_total = gcm_pass + gcm_fail
        integrity_rate = (gcm_pass / gcm_total) * 100 if gcm_total > 0 else 0

        print("\n--- Performance & Integrity Summary ---")
        print(f"Total Time:           {elapsed_time:.2f} seconds")
        print(f"Packets Received:     {packets_received}")
        print(f"Packets Accepted:     {packets_accepted}")
        print(f"Packets Lost (gaps):  {packets_lost}")
        print(f"Throughput:           {throughput:.2f} packets/sec")
        print(f"Packet Loss Rate:     {loss_rate:.2f}%")

        print("\n--- Authentication (AES-128-GCM AEAD) ---")
        print(f"GCM Verified (pass):  {gcm_pass}")
        print(f"GCM Failed:           {gcm_fail}")
        print(f"Inner JSON Failed:    {inner_parse_fail}")
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
