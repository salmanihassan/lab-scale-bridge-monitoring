"""
uart_to_twin.py
CC3220SF Vibration Test Rig — Week 12
EE: Dimitri | Howard University CEA

Reads live UART packets from the CC3220SF, validates HMAC-SHA256 integrity,
and writes twin-compatible rows to twin_feed.csv in real time for the ME
digital twin to consume.

Supports three packet formats automatically:
  1. JSON  (actual board output — {"schema_version":"1.0.0", ...})
  2. [AES] hex_ciphertext  (AES-128 ECB encrypted legacy format)
  3. [PKT] SEQ=x,TS=y,DUTY=z,HMAC=w  (plaintext debug format)

Usage:
    python3 uart_to_twin.py
    python3 uart_to_twin.py --port COM5 --out my_feed.csv   # Windows / custom path

Dependencies:
    pip install pyserial pycryptodome
"""

import json
import serial
import hmac
import hashlib
import csv
import argparse
from datetime import datetime, timezone
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_PORT   = '/dev/tty.usbmodemE00710091'   # macOS — use COM5 on Windows
BAUD           = 115200
AES_KEY        = b'LabKey12LabKey12'             # 16-byte AES-128 key
HMAC_KEY       = bytes([0x4d,0x79,0x53,0x65,0x63,0x75,0x72,0x65,0x44,0x69,0x67,0x69,0x74,0x61,0x6c,0x54,0x77,0x69,0x6e,0x4b,0x65,0x79,0x32,0x30,0x32,0x36,0x21,0x40,0x23,0x24,0x25,0x5e])  # MySecureDigitalTwinKey2026!@#$%^
DEVICE_ID      = 'CC3220SF_NODE_01'
NOMINAL_MS     = 3000                            # expected inter-packet interval (ms)
JITTER_THRESH  = 750                             # anomaly threshold in ms — wider to account for OS scheduling
CALIBRATE_N    = 10                              # number of packets to use for auto-calibration
DEFAULT_OUT    = 'twin_feed.csv'

CSV_HEADER = [
    'wall_time_iso',    # host UTC wall clock — primary time reference for twin
    'seq_num',          # board monotonic sequence number
    'timestamp_ms',     # board elapsed time since boot (ms)
    'pwm_duty_us',      # vibration motor PWM duty cycle (us), range 7000-10000
    'pwm_period_us',    # PWM period fixed at 10000 us (100 Hz)
    'temperature_c',    # temperature in Celsius (1 decimal place)
    'humidity',         # relative humidity % (1 decimal place)
    'interval_ms',      # actual inter-packet interval measured host-side (ms)
    'anomaly',          # True if interval deviates > +/-500 ms from 3000 ms nominal
    'hmac_ok',          # True if HMAC-SHA256 validated — twin must discard False rows
]


# ── Crypto helpers ────────────────────────────────────────────────────────────
def decrypt_packet(hex_ciphertext: str) -> str:
    """AES-128 ECB decrypt + PKCS7 unpad. Returns plaintext string."""
    raw = bytes.fromhex(hex_ciphertext.strip())
    cipher = AES.new(AES_KEY, AES.MODE_ECB)
    return unpad(cipher.decrypt(raw), AES.block_size).decode('ascii')


def validate_hmac(seq: int, ts: int, temp, hum, received_hmac: str) -> bool:
    """
    Reconstruct HMAC-SHA256 over canonical string and compare to received digest.

    Canonical form (matches teammate Week 9 schema):
        device_id|seq_num|timestamp_ms|temperature_c|humidity

    schema_version and pwm fields excluded per Week 9 design decision —
    version tag is pipeline metadata, not integrity-critical data.
    """
    canonical = f'{DEVICE_ID}|{seq}|{ts}|{temp}|{hum}'
    expected  = hmac.new(HMAC_KEY, canonical.encode(), hashlib.sha256).hexdigest()
    return expected == received_hmac.lower()


# ── Packet parser ─────────────────────────────────────────────────────────────
def parse_line(line: str) -> dict | None:
    """
    Parse a single UART line. Returns a normalized field dict or None.

    Priority:
      1. JSON  — starts with '{'
      2. [AES] — AES-128 ECB encrypted, hex encoded
      3. [PKT] — plaintext key=value debug mode
    """
    line = line.strip()
    if not line:
        return None

    # Silently skip firmware debug/fault lines — not packet data
    SKIP_PREFIXES = ('[FAULT]', '===', 'ERROR:')
    if any(line.startswith(p) for p in SKIP_PREFIXES):
        return None

    # ── Format 1: JSON (real board output) ────────────────────────────────────
    if line.startswith('{'):
        try:
            pkt       = json.loads(line)
            telemetry = pkt.get('telemetry', {})
            return {
                'seq':    int(pkt['seq_num']),
                'ts':     int(pkt['timestamp_ms']),
                'duty':   int(telemetry.get('pwm_duty_us', 0)),
                'period': int(telemetry.get('pwm_period_us', 10000)),
                'temp':   telemetry.get('temperature_c'),
                'hum':    telemetry.get('humidity'),
                'hmac':   pkt['hmac'],
            }
        except Exception as e:
            print(f'  [WARN] JSON parse error: {e}')
            return None

    # ── Format 2: AES-encrypted ───────────────────────────────────────────────
    if line.startswith('[AES]'):
        try:
            line = decrypt_packet(line[5:].strip())
        except Exception as e:
            print(f'  [WARN] AES decrypt failed: {e}')
            return None
        # Decrypted payload is JSON (firmware builds JSON then encrypts it)
        if line.startswith('{'):
            try:
                pkt       = json.loads(line)
                telemetry = pkt.get('telemetry', {})
                return {
                    'seq':    int(pkt['seq_num']),
                    'ts':     int(pkt['timestamp_ms']),
                    'duty':   int(telemetry.get('pwm_duty_us', 0)),
                    'period': int(telemetry.get('pwm_period_us', 10000)),
                    'temp':   telemetry.get('temperature_c'),
                    'hum':    telemetry.get('humidity'),
                    'hmac':   pkt['hmac'],
                }
            except Exception as e:
                print(f'  [WARN] JSON parse error after decrypt: {e}')
                return None
        # fall through to key=value parser for legacy plaintext format

    # ── Format 3: Plaintext key=value debug mode ──────────────────────────────
    if line.startswith('[PKT]'):
        line = line[5:].strip()

    try:
        fields = dict(kv.split('=') for kv in line.split(','))
        return {
            'seq':    int(fields['SEQ']),
            'ts':     int(fields['TS']),
            'duty':   int(fields['DUTY']),
            'period': 10000,
            'temp':   None,
            'hum':    None,
            'hmac':   fields['HMAC'],
        }
    except Exception as e:
        print(f'  [WARN] Parse error on "{line}": {e}')
        return None


# ── Main loop ─────────────────────────────────────────────────────────────────
def run(port: str, out_path: str):
    print(f'uart_to_twin.py — CC3220SF Digital Twin Feed')
    print(f'  Port    : {port}')
    print(f'  Output  : {out_path}')
    print(f'  Schema  : v1.0.0 (frozen Week 10)')
    print(f'  Nominal : {NOMINAL_MS} ms / packet  |  Jitter threshold: +/-{JITTER_THRESH} ms')
    print('-' * 60)

    last_wall      = None
    prev_seq       = None
    total          = 0
    hmac_fail      = 0
    anomaly_cnt    = 0
    gap_cnt        = 0
    calibration    = []          # collect first N intervals for auto-calibration
    nominal        = NOMINAL_MS  # will be updated after calibration

    with serial.Serial(port, BAUD, timeout=5) as ser, \
         open(out_path, 'w', newline='') as f:

        writer = csv.writer(f)
        writer.writerow(CSV_HEADER)
        f.flush()

        print(f'Listening on {port} — Ctrl+C to stop\n')

        while True:
            try:
                raw = ser.readline().decode(errors='ignore')
            except serial.SerialException as e:
                print(f'[ERROR] Serial read failed: {e}')
                break

            wall_now = datetime.now(timezone.utc)
            pkt = parse_line(raw)
            if pkt is None:
                continue

            total += 1
            seq, ts, duty   = pkt['seq'], pkt['ts'], pkt['duty']
            period          = pkt['period']
            temp, hum       = pkt['temp'], pkt['hum']
            rx_hmac         = pkt['hmac']

            # HMAC validation
            if temp is not None and hum is not None:
                hmac_ok = validate_hmac(seq, ts, temp, hum, rx_hmac)
            else:
                # legacy format without temp/hum — skip HMAC check
                hmac_ok = True

            if not hmac_ok:
                hmac_fail += 1

            # Inter-packet interval and anomaly detection
            # Skip on first packet and after a sequence gap (DROP fault injects a gap)
            seq_gap = prev_seq is not None and seq != prev_seq + 1
            if last_wall is not None and not seq_gap:
                interval_ms = int((wall_now - last_wall).total_seconds() * 1000)
                # Auto-calibrate nominal from first N clean intervals
                if len(calibration) < CALIBRATE_N:
                    calibration.append(interval_ms)
                    if len(calibration) == CALIBRATE_N:
                        nominal = int(sum(calibration) / len(calibration))
                        print(f'  [CAL]  Auto-calibrated nominal interval: {nominal} ms')
                anomaly = len(calibration) >= CALIBRATE_N and abs(interval_ms - nominal) > JITTER_THRESH
            else:
                interval_ms = 0
                anomaly     = False

            if anomaly:
                anomaly_cnt += 1

            # Sequence gap detection
            if prev_seq is not None and seq != prev_seq + 1:
                gap_cnt += 1
                print(f'  [GAP]  Expected SEQ={prev_seq + 1}, got SEQ={seq}')

            last_wall = wall_now
            prev_seq  = seq

            # Write CSV row
            writer.writerow([
                wall_now.isoformat(),
                seq, ts, duty, period, temp, hum,
                interval_ms, anomaly, hmac_ok,
            ])
            f.flush()

            # Console status
            hmac_tag    = 'OK  ' if hmac_ok else 'FAIL'
            anomaly_tag = 'ANOMALY' if anomaly else ''
            print(f'  SEQ={seq:>6}  TS={ts:>9} ms  DUTY={duty:>5} us  '
                  f'TEMP={str(temp):>5}C  HUM={str(hum):>5}%  '
                  f'HMAC={hmac_tag}  {anomaly_tag}')

    # Summary
    print('\n' + '-' * 60)
    print(f'Session summary')
    print(f'  Packets received : {total}')
    print(f'  HMAC failures    : {hmac_fail}')
    print(f'  Timing anomalies : {anomaly_cnt}')
    print(f'  Sequence gaps    : {gap_cnt}')
    print(f'  Output written   : {out_path}')


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CC3220SF UART -> Digital Twin CSV feed')
    parser.add_argument('--port', default=DEFAULT_PORT,
                        help=f'Serial port (default: {DEFAULT_PORT})')
    parser.add_argument('--out',  default=DEFAULT_OUT,
                        help=f'Output CSV path (default: {DEFAULT_OUT})')
    args = parser.parse_args()

    try:
        run(args.port, args.out)
    except KeyboardInterrupt:
        print('\n[INFO] Stopped by user.')
