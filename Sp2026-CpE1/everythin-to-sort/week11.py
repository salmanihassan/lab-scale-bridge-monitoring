import serial
import re
import csv
import time
import random
from datetime import datetime
from Crypto.Cipher import AES

# === Configuration ===
PORT     = '/dev/tty.usbmodemE00710091'
BAUD     = 115200
CSV_FILE = 'week11_fault_injection_log.csv'

AES_KEY = bytes([
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32,
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32
])

# === Fault injection rates ===
DROP_RATE   = 0.10  # 10% packet drop
NOISE_RATE  = 0.10  # 10% noise injection
MALFORM_RATE = 0.05 # 5% malformed packets

# === Stats ===
stats = {
    'total': 0, 'dropped': 0, 'noised': 0,
    'malformed': 0, 'accepted': 0, 'decrypt_errors': 0
}

def pkcs7_unpad(data):
    pad_len = data[-1]
    if pad_len > 16 or pad_len == 0:
        raise ValueError("Bad padding")
    return data[:-pad_len]

def aes_decrypt(hex_str):
    try:
        raw    = bytes.fromhex(hex_str)
        cipher = AES.new(AES_KEY, AES.MODE_ECB)
        plain  = pkcs7_unpad(cipher.decrypt(raw))
        return plain.decode('ascii'), True
    except Exception as e:
        return f"DECRYPT_ERROR: {e}", False

def inject_noise(hex_str):
    """Flip random bytes in the hex ciphertext"""
    raw = bytearray(bytes.fromhex(hex_str))
    num_flips = random.randint(1, 3)
    for _ in range(num_flips):
        idx = random.randint(0, len(raw)-1)
        raw[idx] ^= random.randint(1, 255)
    return raw.hex().upper()

def inject_malform():
    """Return completely garbage hex data"""
    return ''.join([f'{random.randint(0,255):02X}' for _ in range(32)])

# === Setup CSV ===
with open(CSV_FILE, 'w', newline='') as f:
    csv.writer(f).writerow([
        'timestamp', 'fault_type', 'original_hex',
        'modified_hex', 'decrypted', 'decrypt_ok', 'outcome'
    ])

def log_row(ts, fault, orig, modified, decrypted, ok, outcome):
    with open(CSV_FILE, 'a', newline='') as f:
        csv.writer(f).writerow([ts, fault, orig[:20]+'...', modified[:20]+'...', decrypted, ok, outcome])

print("=== Week 11: Fault Injection & Robustness Testing ===")
print(f"Drop rate: {DROP_RATE*100:.0f}% | Noise rate: {NOISE_RATE*100:.0f}% | Malform rate: {MALFORM_RATE*100:.0f}%")
print(f"Listening on {PORT} at {BAUD} baud...")
print("Press Ctrl+C to stop\n")

try:
    ser = serial.Serial(PORT, BAUD, timeout=2)
    ser.reset_input_buffer()

    while True:
        line = ser.readline().decode('utf-8', errors='ignore').strip()
        if '[AES]' not in line:
            continue

        match = re.search(r'\[AES\]\s+([0-9A-Fa-f]+)', line)
        if not match:
            continue

        orig_hex = match.group(1)
        stats['total'] += 1
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        r  = random.random()

        # === Fault 1: Packet Drop ===
        if r < DROP_RATE:
            stats['dropped'] += 1
            print(f"[{ts}] 🗑️  DROP     | SEQ dropped — simulating packet loss")
            log_row(ts, 'DROP', orig_hex, orig_hex, 'N/A', 'N/A', 'DROPPED')
            continue

        # === Fault 2: Noise Injection ===
        elif r < DROP_RATE + NOISE_RATE:
            stats['noised'] += 1
            noised_hex = inject_noise(orig_hex)
            decrypted, ok = aes_decrypt(noised_hex)
            outcome = 'NOISE_DETECTED' if not ok else 'NOISE_UNDETECTED'
            stats['decrypt_errors'] += (0 if ok else 1)
            print(f"[{ts}] ⚡ NOISE    | orig={orig_hex[:12]}... noised={noised_hex[:12]}... → {'✅ caught' if not ok else '⚠️ missed'}")
            log_row(ts, 'NOISE', orig_hex, noised_hex, decrypted, ok, outcome)

        # === Fault 3: Malformed Packet ===
        elif r < DROP_RATE + NOISE_RATE + MALFORM_RATE:
            stats['malformed'] += 1
            malformed_hex = inject_malform()
            decrypted, ok = aes_decrypt(malformed_hex)
            # Even if decrypt succeeds, check if parsed fields are valid
            valid_fields = bool(re.search(r'SEQ=\d+,TS=\d+,DUTY=\d+', decrypted)) if ok else False
            outcome = 'MALFORM_DETECTED' if not valid_fields else 'MALFORM_UNDETECTED'
            print(f"[{ts}] 💀 MALFORM  | garbage={malformed_hex[:12]}... → {'✅ caught' if not valid_fields else '⚠️ missed'}")
            log_row(ts, 'MALFORM', orig_hex, malformed_hex, decrypted, ok, outcome)

	# === Normal packet ===
        else:
            decrypted, ok = aes_decrypt(orig_hex)
            if ok:
                stats['accepted'] += 1
                print(f"[{ts}] ✅ NORMAL   | {decrypted}")
                log_row(CSV_FILE, ts, 'NONE', orig_hex, decrypted, ok, 'ACCEPTED')
            else:
                stats['decrypt_errors'] += 1
                print(f"[{ts}] ⚠️  FW_FAULT  | Firmware-corrupted packet detected: {decrypted}")
                log_row(CSV_FILE, ts, 'FW_CORRUPT', orig_hex, decrypted, ok, 'FW_FAULT_DETECTED')

except KeyboardInterrupt:
    print("\n=== Fault Injection Test Complete ===")
    print(f"Total packets : {stats['total']}")
    print(f"Accepted      : {stats['accepted']}")
    print(f"Dropped       : {stats['dropped']}")
    print(f"Noised        : {stats['noised']}")
    print(f"Malformed     : {stats['malformed']}")
    print(f"Decrypt errors: {stats['decrypt_errors']}")
    print(f"Results saved : {CSV_FILE}")
except serial.SerialException as e:
    print(f"Serial error: {e}")
