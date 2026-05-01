import serial
import hmac
import hashlib
import csv
import time
import re
from datetime import datetime
from collections import deque

# === Configuration ===
PORT = 'COM5'
BAUD = 115200
CSV_FILE = 'replay_detection_log.csv'

# HMAC key bound to firmware identity (v1.0.0)
HMAC_KEY = b'CC3220SF_v1.0.0_vibration_rig'
DEVICE_ID = 'CC3220SF_NODE_01'

# === Replay Detection Config ===
FRESHNESS_WINDOW_MS = 5000   # reject packets older than 5 seconds
MAX_SEQ_HISTORY    = 100     # remember last 100 sequence numbers

# State
seen_seq_nums = set()
replay_buffer = deque(maxlen=10)  # stores recent packets for replay simulation

def compute_hmac(packet_data: dict) -> str:
    msg = f"{packet_data['device_id']}|{packet_data['seq_num']}|{packet_data['duty_us']}|{packet_data['period_us']}|{packet_data['timestamp']}"
    return hmac.new(HMAC_KEY, msg.encode(), hashlib.sha256).hexdigest()

def verify_packet(packet: dict) -> bool:
    received_hmac = packet.pop('hmac', None)
    expected_hmac = compute_hmac(packet)
    packet['hmac'] = received_hmac
    return hmac.compare_digest(received_hmac, expected_hmac)

def check_freshness(packet: dict) -> bool:
    """Reject packets older than FRESHNESS_WINDOW_MS milliseconds."""
    now_ms = int(time.time() * 1000)
    age_ms = now_ms - packet['timestamp']
    return age_ms <= FRESHNESS_WINDOW_MS

def check_replay(packet: dict) -> bool:
    """Reject packets with a sequence number we've already seen."""
    if packet['seq_num'] in seen_seq_nums:
        return False  # replay detected
    seen_seq_nums.add(packet['seq_num'])
    if len(seen_seq_nums) > MAX_SEQ_HISTORY:
        seen_seq_nums.pop()
    return True

def parse_uart_line(line: str, seq_num: int) -> dict:
    match = re.search(r'Duty:\s+(\d+)%\s+\((\d+)\s+us\).*Period:\s+(\d+)\s+us', line)
    if not match:
        return None
    packet = {
        'device_id': DEVICE_ID,
        'firmware': 'v1.0.0',
        'seq_num': seq_num,
        'duty_pct': int(match.group(1)),
        'duty_us': int(match.group(2)),
        'period_us': int(match.group(3)),
        'timestamp': int(time.time() * 1000)
    }
    packet['hmac'] = compute_hmac(packet)
    return packet

def log(csv_file, ts, seq, duty_pct, duty_us, period_us, hmac_tag, hmac_valid, fresh, seq_valid, attack_type):
    with open(csv_file, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([ts, seq, duty_pct, duty_us, period_us,
                        hmac_tag[:16]+'...', hmac_valid, fresh, seq_valid, attack_type])

# === Setup CSV ===
with open(CSV_FILE, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'seq_num', 'duty_pct', 'duty_us', 'period_us',
                    'hmac', 'hmac_valid', 'fresh', 'seq_valid', 'attack_type'])

print("=== Week 7: Timestamping & Replay Detection ===")
print(f"Freshness window: {FRESHNESS_WINDOW_MS}ms")
print(f"Listening on {PORT} at {BAUD} baud...")
print("Press Ctrl+C to stop\n")

seq = 0
try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if '[PWM]' not in line:
            continue

        packet = parse_uart_line(line, seq)
        if not packet:
            continue
        seq += 1

        # Store packet in replay buffer for later simulation
        replay_buffer.append(packet.copy())

        # === Check 1: HMAC integrity ===
        hmac_valid = verify_packet(packet)

        # === Check 2: Freshness ===
        fresh = check_freshness(packet)

        # === Check 3: Replay (sequence number) ===
        seq_valid = check_replay(packet)

        # Overall verdict
        accepted = hmac_valid and fresh and seq_valid
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]

        status = '✅ ACCEPTED' if accepted else '❌ REJECTED'
        print(f"[{ts}] SEQ {packet['seq_num']:04d} | Duty: {packet['duty_pct']}% | HMAC: {'✅' if hmac_valid else '❌'} | Fresh: {'✅' if fresh else '❌'} | SeqOK: {'✅' if seq_valid else '❌'} | {status}")

        log(CSV_FILE, ts, packet['seq_num'], packet['duty_pct'], packet['duty_us'],
            packet['period_us'], packet['hmac'], hmac_valid, fresh, seq_valid, 'none')

        # === Replay Attack Simulation (every 10th packet) ===
        if seq % 10 == 0 and len(replay_buffer) >= 5:
            # Grab an old packet from buffer and re-send it
            old_packet = replay_buffer[0].copy()
            ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]

            # Check 1: HMAC still valid (attacker didn't modify data)
            replay_hmac_valid = verify_packet(old_packet)

            # Check 2: Freshness — timestamp is old so this fails
            replay_fresh = check_freshness(old_packet)

            # Check 3: Seq num already seen — this also fails
            replay_seq_valid = old_packet['seq_num'] not in seen_seq_nums

            replay_accepted = replay_hmac_valid and replay_fresh and replay_seq_valid

            print(f"[{ts}] SEQ {old_packet['seq_num']:04d} | ⚠️  REPLAY ATTACK | HMAC: {'✅' if replay_hmac_valid else '❌'} | Fresh: {'✅' if replay_fresh else '❌'} | SeqOK: {'✅' if replay_seq_valid else '❌'} | {'✅ ACCEPTED' if replay_accepted else '❌ REJECTED'}")

            log(CSV_FILE, ts, old_packet['seq_num'], old_packet['duty_pct'], old_packet['duty_us'],
                old_packet['period_us'], old_packet['hmac'], replay_hmac_valid, replay_fresh, replay_seq_valid, 'replay')

except KeyboardInterrupt:
    print("\n=== Test Complete ===")
    print(f"Results saved to {CSV_FILE}")
except serial.SerialException as e:
    print(f"Serial error: {e}")
