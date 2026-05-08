from Crypto.Cipher import AES
import serial
import re
from datetime import datetime
import csv

# Must match firmware key exactly
AES_KEY = bytes([
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32,
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32
])

PORT     = '/dev/tty.usbmodemE00710091'
BAUD     = 115200
CSV_FILE = 'week9_aes_log.csv'

def pkcs7_unpad(data: bytes) -> bytes:
    pad_len = data[-1]
    return data[:-pad_len]

def aes_decrypt(hex_str: str) -> str:
    try:
        raw     = bytes.fromhex(hex_str)
        cipher  = AES.new(AES_KEY, AES.MODE_ECB)
        plain   = pkcs7_unpad(cipher.decrypt(raw))
        return plain.decode('ascii')
    except Exception as e:
        return f"DECRYPT_ERROR: {e}"

with open(CSV_FILE, 'w', newline='') as f:
    csv.writer(f).writerow(['timestamp', 'encrypted_hex', 'decrypted', 'seq', 'ts_ms', 'duty_us'])

print("=== Week 9: AES-128 Decryption (TI CryptoCC32XX) ===")
print(f"Key: {AES_KEY.hex()}")
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

        hex_data  = match.group(1)
        plaintext = aes_decrypt(hex_data)
        ts        = datetime.now().strftime('%H:%M:%S.%f')[:-3]

        seq_match  = re.search(r'SEQ=(\d+)',  plaintext)
        ts_match   = re.search(r'TS=(\d+)',   plaintext)
        duty_match = re.search(r'DUTY=(\d+)', plaintext)

        seq  = seq_match.group(1)  if seq_match  else '?'
        ts_ms = ts_match.group(1) if ts_match   else '?'
        duty = duty_match.group(1) if duty_match else '?'

        print(f"[{ts}] 🔒 AES: {hex_data[:20]}... → 🔓 DEC: {plaintext}")

        with open(CSV_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([ts, hex_data, plaintext, seq, ts_ms, duty])

except KeyboardInterrupt:
    print("\n=== Test Complete ===")
    print(f"Results saved to {CSV_FILE}")
except serial.SerialException as e:
    print(f"Serial error: {e}")
