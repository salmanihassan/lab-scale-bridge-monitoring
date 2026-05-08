import serial
import hmac
import hashlib
import csv
import time
import re
from datetime import datetime
from collections import deque

# === Configuration ===
PORT = '/dev/tty.usbmodemE00710091'  # change to COM5 if on Windows
BAUD = 115200
CSV_FILE = 'week8_timing_monitor_log.csv'

HMAC_KEY = b'CC3220SF_v1.0.0_vibration_rig'
DEVICE_ID = 'CC3220SF_NODE_01'

# === Replay Detection Config ===
FRESHNESS_WINDOW_MS  = 5000
MAX_SEQ_HISTORY      = 100

# === Week 8 Timing Config ===
EXPECTED_INTERVAL_MS = 3000
JITTER_THRESHOLD_MS  = 1000

# State
seen_seq_nums  = set()
replay_buffer  = deque(maxlen=10)
last_packet_ts = None  # host-side timestamp of last received packet

def compute_hmac(packet_data: dict) -> str:
    msg = f"{packet_data['device_id']}|{packet_data['seq_num']}|{packet_data['duty_us']}|{packet_data['timestamp']}"
    return hmac.new(HMAC_KEY, msg.encode(), hashlib.sha256).hexdigest()

def verify_packet(packet: dict) -> bool:
    received = packet.pop('hmac', None)
    expected = compute_hmac(packet)
    packet['hmac'] = received
    return hmac.compare_digest(received, expected)

def check_freshness(packet: dict) -> bool:
    now_ms = int(time.time() * 1000)
    return (now_ms - packet['timestamp']) <= FRESHNESS_WINDOW_MS

def check_replay(packet: dict) -> bool:
    if packet['seq_num'] in seen_seq_nums:
        return False
    seen_seq_nums.add(packet['seq_num'])
    if len(seen_seq_nums) > MAX_SEQ_HISTORY:
        seen_seq_nums.pop()
    return True

def parse_uart_line(line: str) -> dict:
    # Matches: [PKT] seq=1 ts=3000 duty=7000 us
    match = re.search(r'\[PKT\]\s+seq=(\d+)\s+ts=(\d+)\s+duty=(\d+)\s+us', line)
    if not match:
        return None
    seq_num  = int(match.group(1))
    board_ts = int(match.group(2))
    duty_us  = int(match.group(3))

    packet = {
        'device_id': DEVICE_ID,
        'firmware':  'v1.0.0',
        'seq_num':   seq_num,
        'duty_us':   duty_us,
        'board_ts':  board_ts,
        'timestamp': int(time.time() * 1000)
    }
    packet['hmac'] = compute_hmac(packet)
    return packet

def log_row(csv_file, row):
    with open(csv_file, 'a', newline='') as f:
        csv.writer(f).writerow(row)

# === Setup CSV ===
with open(CSV_FILE, 'w', newline='') as f:
    csv.writer(f).writerow([
        'host_timestamp', 'seq_num', 'duty_us', 'board_ts_ms',
        'host_interval_ms', 'jitter_ms', 'timing_anomaly',
        'hmac_valid', 'fresh', 'seq_valid', 'attack_type'
    ])

print("=== Week 6+7+8: HMAC + Replay Detection + Timing Monitor ===")
print(f"Expected interval: {EXPECTED_INTERVAL_MS}ms | Jitter threshold: {JITTER_THRESHOLD_MS}ms")
print(f"Listening on {PORT} at {BAUD} baud...")
print("Press Ctrl+C to stop\n")

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if '[PKT]' not in line:
            continue

        packet = parse_uart_line(line)
        if not packet:
            continue

        # === Week 8: Host-side timing monitor ===
        now = int(time.time() * 1000)
        if last_packet_ts is None:
            interval_ms = EXPECTED_INTERVAL_MS
        else:
            interval_ms = now - last_packet_ts
        last_packet_ts = now

        jitter_ms      = abs(interval_ms - EXPECTED_INTERVAL_MS)
        timing_anomaly = jitter_ms > JITTER_THRESHOLD_MS

        # === Week 6: HMAC verify ===
        hmac_valid = verify_packet(packet)

        # === Week 7: Freshness + replay ===
        fresh     = check_freshness(packet)
        seq_valid = check_replay(packet)

        accepted = hmac_valid and fresh and seq_valid
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]

        timing_str = f"⚠️ ANOMALY jitter={jitter_ms}ms" if timing_anomaly else f"jitter={jitter_ms}ms"
        status     = '✅ ACCEPTED' if accepted else '❌ REJECTED'

        print(f"[{ts}] SEQ {packet['seq_num']:04d} | duty={packet['duty_us']}us | "
              f"interval={interval_ms}ms {timing_str} | "
              f"HMAC:{'✅' if hmac_valid else '❌'} Fresh:{'✅' if fresh else '❌'} SeqOK:{'✅' if seq_valid else '❌'} | {status}")

        if timing_anomaly:
            print(f"  [TIMING ANOMALY] SEQ {packet['seq_num']} interval={interval_ms}ms exceeds threshold!")

        replay_buffer.append(packet.copy())

        log_row(CSV_FILE, [
            ts, packet['seq_num'], packet['duty_us'], packet['board_ts'],
            interval_ms, jitter_ms, timing_anomaly,
            hmac_valid, fresh, seq_valid, 'none'
        ])

        # === Replay simulation every 10th packet ===
        seq_count = packet['seq_num']
        if seq_count % 10 == 0 and len(replay_buffer) >= 5:
            old = replay_buffer[0].copy()
            r_hmac  = verify_packet(old)
            r_fresh = check_freshness(old)
            r_seq   = old['seq_num'] not in seen_seq_nums
            r_ok    = r_hmac and r_fresh and r_seq
            print(f"[{ts}] SEQ {old['seq_num']:04d} | ⚠️  REPLAY ATTACK | "
                  f"HMAC:{'✅' if r_hmac else '❌'} Fresh:{'✅' if r_fresh else '❌'} SeqOK:{'✅' if r_seq else '❌'} | "
                  f"{'✅ ACCEPTED' if r_ok else '❌ REJECTED'}")
            log_row(CSV_FILE, [
                ts, old['seq_num'], old['duty_us'], old['board_ts'],
                interval_ms, 0, False,
                r_hmac, r_fresh, r_seq, 'replay'
            ])

except KeyboardInterrupt:
    print("\n=== Test Complete ===")
    print(f"Results saved to {CSV_FILE}")
except serial.SerialException as e:
    print(f"Serial error: {e}")
