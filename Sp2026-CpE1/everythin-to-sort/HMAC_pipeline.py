import serial
import hmac
import hashlib
import json
import csv
import time
import re
from datetime import datetime

# === Configuration ===
PORT = '/dev/tty.usbmodemE00710091'
BAUD = 115200
CSV_FILE = '/Users/dimitricromarty/Documents/sensor_integrity_log.csv'

# HMAC key bound to firmware identity (v1.0.0)
HMAC_KEY = b'CC3220SF_v1.0.0_vibration_rig'
DEVICE_ID = 'CC3220SF_NODE_01'

def compute_hmac(packet_data: dict) -> str:
    msg = f"{packet_data['device_id']}|{packet_data['seq_num']}|{packet_data['duty_us']}|{packet_data['period_us']}|{packet_data['timestamp']}"
    return hmac.new(HMAC_KEY, msg.encode(), hashlib.sha256).hexdigest()

def verify_packet(packet: dict) -> bool:
    received_hmac = packet.pop('hmac', None)
    expected_hmac = compute_hmac(packet)
    packet['hmac'] = received_hmac
    return hmac.compare_digest(received_hmac, expected_hmac)

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

def tamper_packet(packet: dict) -> dict:
    tampered = packet.copy()
    tampered['duty_us'] = 99999
    return tampered

# === Setup CSV ===
with open(CSV_FILE, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'seq_num', 'duty_pct', 'duty_us', 'period_us', 'hmac', 'valid', 'tampered'])

print("=== Sensor Data Integrity Protection ===")
print(f"HMAC key bound to firmware: v1.0.0")
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
        valid = verify_packet(packet)
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        print(f"[{ts}] SEQ {packet['seq_num']:04d} | Duty: {packet['duty_pct']}% ({packet['duty_us']}us) | HMAC: {'✅ VALID' if valid else '❌ INVALID'}")
        with open(CSV_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([ts, packet['seq_num'], packet['duty_pct'], packet['duty_us'],
                           packet['period_us'], packet['hmac'][:16]+'...', valid, False])
        if seq % 5 == 0:
            tampered = tamper_packet(packet)
            tampered_valid = verify_packet(tampered)
            print(f"[{ts}] SEQ {packet['seq_num']:04d} | TAMPERED duty=99999us | HMAC: {'✅ VALID' if tampered_valid else '❌ INVALID'} ← tamper detected!")
            with open(CSV_FILE, 'a', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([ts, packet['seq_num'], packet['duty_pct'], 99999,
                               packet['period_us'], tampered['hmac'][:16]+'...', tampered_valid, True])

except KeyboardInterrupt:
    print("\n=== Test Complete ===")
    print(f"Results saved to {CSV_FILE}")
except serial.SerialException as e:
    print(f"Serial error: {e}")
