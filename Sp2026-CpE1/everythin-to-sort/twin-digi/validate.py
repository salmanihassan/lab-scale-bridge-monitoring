"""
validate_twin_feed.py
CC3220SF Vibration Test Rig — Week 12
EE: Dimitri | Howard University CEA

Offline validator for twin_feed.csv. Checks every row for:
  - HMAC failures         (rows the twin must discard)
  - Sequence gaps         (dropped packets between board and host)
  - Timing anomalies      (board timestamp_ms delta outside ±750 ms of auto-calibrated nominal)
  - Out-of-range DUTY     (outside 7000–10000 µs spec)
  - Duplicate SEQ numbers (replay or logging bug)

Produces a pass/fail report and an annotated twin_feed_validated.csv with
an extra 'issue' column describing any problems found per row.

Usage:
    python3 validate_twin_feed.py
    python3 validate_twin_feed.py --input my_feed.csv --out report.csv
"""

import csv
import argparse
from collections import Counter

# ── Configuration ─────────────────────────────────────────────────────────────
DEFAULT_INPUT  = 'twin_feed.csv'
DEFAULT_OUT    = 'twin_feed_validated.csv'
NOMINAL_MS     = 3000   # fallback only — overridden by auto-calibration
JITTER_THRESH  = 750    # wider to account for OS scheduling variance
CALIBRATE_N    = 10     # rows used to compute real nominal from CSV
DUTY_MIN       = 7000
DUTY_MAX       = 10000

REQUIRED_COLS  = {
    'wall_time_iso', 'seq_num', 'timestamp_ms',
    'pwm_duty_us', 'interval_ms', 'anomaly', 'hmac_ok'
}


# ── Validators ────────────────────────────────────────────────────────────────
def check_hmac_ok(row: dict) -> str | None:
    if row['hmac_ok'].strip().lower() == 'false':
        return 'HMAC_FAIL'
    return None

def check_duty_range(row: dict) -> str | None:
    try:
        duty = int(row['pwm_duty_us'])
        if not (DUTY_MIN <= duty <= DUTY_MAX):
            return f'DUTY_OUT_OF_RANGE({duty})'
    except ValueError:
        return 'DUTY_PARSE_ERROR'
    return None

def check_timing(ts_delta: int, nominal: int) -> str | None:
    # ts_delta is board timestamp_ms difference between consecutive packets
    # This is immune to host-side buffering/backlog issues
    if ts_delta > 0 and abs(ts_delta - nominal) > JITTER_THRESH:
        return f'TIMING_ANOMALY(ts_delta={ts_delta}ms,nominal={nominal}ms)'
    return None

def check_ts_monotonic(prev_ts: int | None, row: dict) -> str | None:
    try:
        ts = int(row['timestamp_ms'])
        if prev_ts is not None and ts <= prev_ts:
            return f'TS_NOT_MONOTONIC(prev={prev_ts},cur={ts})'
    except ValueError:
        return 'TS_PARSE_ERROR'
    return None


# ── Main validation ───────────────────────────────────────────────────────────
def validate(input_path: str, out_path: str):
    print(f'validate_twin_feed.py — CC3220SF Schema v1.0.0')
    print(f'  Input  : {input_path}')
    print(f'  Output : {out_path}')
    print('─' * 60)

    # Counters
    total          = 0
    hmac_failures  = 0
    duty_errors    = 0
    timing_errors  = 0
    seq_gaps       = 0
    ts_errors      = 0
    duplicates     = 0
    clean_rows     = 0

    seen_seqs      = Counter()
    prev_seq       = None
    prev_ts        = None
    calibration    = []          # first N valid intervals for auto-calibration
    nominal        = NOMINAL_MS  # updated once calibration complete

    rows_out    = []

    with open(input_path, newline='') as f:
        reader = csv.DictReader(f)

        # Column check
        missing = REQUIRED_COLS - set(reader.fieldnames or [])
        if missing:
            print(f'[ERROR] Missing required columns: {missing}')
            return

        for row in reader:
            total += 1
            issues = []

            seq = None
            try:
                seq = int(row['seq_num'])
                seen_seqs[seq] += 1
                if seen_seqs[seq] > 1:
                    issues.append(f'DUPLICATE_SEQ({seq})')
                    duplicates += 1
            except ValueError:
                issues.append('SEQ_PARSE_ERROR')

            # Sequence gap
            seq_gap = False
            if prev_seq is not None and seq is not None:
                if seq != prev_seq + 1:
                    gap = seq - prev_seq - 1
                    issues.append(f'SEQ_GAP(missing={gap},expected={prev_seq+1})')
                    seq_gaps += 1
                    seq_gap = True

            # Compute board-side timestamp delta (immune to host buffering)
            try:
                cur_ts  = int(row['timestamp_ms'])
                ts_delta = (cur_ts - prev_ts) if prev_ts is not None else 0
            except ValueError:
                cur_ts   = None
                ts_delta = 0

            # Auto-calibrate nominal from first N plausible board ts deltas
            # Reject: 0 (first packet), <1000ms, >8000ms (fault delays)
            if not seq_gap and 1000 <= ts_delta <= 8000:
                if len(calibration) < CALIBRATE_N:
                    calibration.append(ts_delta)
                    if len(calibration) == CALIBRATE_N:
                        nominal = int(sum(calibration) / len(calibration))
                        print(f'  [CAL]  Auto-calibrated nominal: {nominal} ms (from board timestamps)')

            # Individual field checks
            h = check_hmac_ok(row)
            if h:
                issues.append(h)
                hmac_failures += 1

            d = check_duty_range(row)
            if d:
                issues.append(d)
                duty_errors += 1

            t = check_timing(ts_delta, nominal)
            if t and not seq_gap:   # don't flag timing on gap rows
                issues.append(t)
                timing_errors += 1

            ts = check_ts_monotonic(prev_ts, row)
            if ts:
                issues.append(ts)
                ts_errors += 1

            row['issue'] = '; '.join(issues) if issues else 'OK'
            rows_out.append(row)

            if not issues:
                clean_rows += 1

            if seq is not None:
                prev_seq = seq
            if cur_ts is not None:
                prev_ts = cur_ts

    # Write annotated output
    if rows_out:
        fieldnames = list(rows_out[0].keys())
        with open(out_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_out)

    # ── Report ────────────────────────────────────────────────────────────────
    print(f'\nValidation Report')
    print(f'  Calibrated nominal : {nominal} ms')
    print(f'  Total rows         : {total}')
    print(f'  Clean rows (OK)    : {clean_rows}  ({100*clean_rows//total if total else 0}%)')
    print(f'  HMAC failures      : {hmac_failures}')
    print(f'  Sequence gaps      : {seq_gaps}')
    print(f'  Duplicate SEQs     : {duplicates}')
    print(f'  Timing anomalies   : {timing_errors}')
    print(f'  DUTY out of range  : {duty_errors}')
    print(f'  Timestamp errors   : {ts_errors}')
    print()

    overall = (hmac_failures + seq_gaps + duplicates + duty_errors + ts_errors) == 0
    if overall:
        print('  RESULT: PASS — data stream is twin-compatible')
    else:
        print('  RESULT: FAIL — issues found, see annotated output')

    print(f'\n  Annotated CSV: {out_path}')
    print('─' * 60)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Validate twin_feed.csv for ME digital twin compatibility')
    parser.add_argument('--input', default=DEFAULT_INPUT, help=f'Input CSV (default: {DEFAULT_INPUT})')
    parser.add_argument('--out',   default=DEFAULT_OUT,   help=f'Annotated output CSV (default: {DEFAULT_OUT})')
    args = parser.parse_args()

    validate(args.input, args.out)
