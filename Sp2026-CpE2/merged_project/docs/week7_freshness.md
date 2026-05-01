# Timestamping & Freshness Guarantees -- Week 7

This document covers the replay detection and freshness validation layer added
on top of the HMAC-SHA256 authentication established in Week 6.

## 1. Problem Statement

Week 6 introduced HMAC-SHA256 to detect tampering and unauthorized sources.
However, a valid HMAC-signed packet could be captured and re-sent (replayed)
without detection.  An attacker with access to the TLS-encrypted channel (e.g.
a compromised broker or man-in-the-middle at the application layer) could:

- **Replay** a previously valid packet to inject stale data
- **Duplicate** a packet to inflate telemetry counts
- **Delay** a packet and deliver it long after it was generated
- **Reorder** packets to confuse time-series analysis

All of these attacks pass HMAC verification because the packet itself is
unmodified.

## 2. Solution Overview

A multi-stage freshness validation pipeline on the host receiver that rejects
any HMAC-verified packet failing sequence, monotonicity, or timing checks.

### Validation flow

```
Incoming Packet
      |
      v
[HMAC Verification] --- FAIL ---> Log & discard
      |
      | PASS
      v
[Sequence Check] --- seq < last_accepted ---> REPLAY (discard)
      |              --- seq == last_accepted --> DUPLICATE (discard)
      |              --- seq near 0, last was high --> REBOOT (reset & accept)
      |
      | seq > last_accepted
      v
[Board Timestamp Monotonicity] --- ts <= last_ts ---> REPLAY (discard)
      |
      | ts > last_ts
      v
[Host Freshness Window] --- wall_delta > 30s ---> STALE (discard)
      |
      | within window
      v
[Gap Detection] --- seq > expected_next ---> OOO_GAP (accept, log loss)
      |
      | seq == expected_next
      v
ACCEPTED (update tracker)
```

### Key design decisions

1. **HMAC-gated tracking** -- Only HMAC-verified packets update the sequence
   tracker.  A tampered packet cannot corrupt the freshness state.

2. **Reboot heuristic** -- If `seq_num <= 5` and `last_accepted_seq` was high
   (> 5), the host treats this as a device reboot rather than a replay, resets
   the tracker, and accepts the packet.

3. **Staleness threshold** -- 30 seconds (configurable via `MAX_STALENESS_SEC`).
   Any HMAC-valid packet arriving more than 30 seconds after the last accepted
   packet is flagged as stale and discarded.  This catches delayed/buffered
   packets without rejecting legitimate gaps from packet loss.

4. **Board timestamp monotonicity** -- `timestamp_ms` must strictly increase
   between accepted packets.  A valid HMAC with a non-increasing timestamp
   indicates replay or reorder.

## 3. MCU-Side Changes

### Real monotonic timestamp

The synthetic `g_timestamp_ms += 250` counter was replaced with a real
FreeRTOS tick-based timestamp:

```c
g_timestamp_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
```

This provides millisecond-resolution monotonic time derived from the RTOS
scheduler tick.  It wraps at ~49.7 days (`uint32_t` overflow at ~4.29 billion
ms), which is acceptable for our use case.

The `seq_num` counter remains a simple `++` increment, starting from 1 on each
boot.

### HMAC coverage

Both `seq_num` and `timestamp_ms` remain part of the HMAC canonical string:

```
CC3220SF_NODE_01|<seq_num>|<timestamp_ms>|<temp>|<humidity>
```

An attacker cannot modify either field without invalidating the HMAC.

## 4. Host Receiver Changes (`host_receiver.py`)

### New state variables

| Variable                 | Type   | Purpose                                  |
|--------------------------|--------|------------------------------------------|
| `last_accepted_seq`      | int    | Highest accepted sequence number         |
| `last_accepted_board_ts` | int    | Last accepted `timestamp_ms` value       |
| `last_accepted_wall_time`| float  | Host `time.time()` at last acceptance    |
| `replays_detected`       | int    | Counter: seq < last_accepted             |
| `duplicates_detected`    | int    | Counter: seq == last_accepted            |
| `stale_detected`         | int    | Counter: host delta > MAX_STALENESS_SEC  |
| `ooo_detected`           | int    | Counter: gaps in sequence                |
| `reboots_detected`       | int    | Counter: seq reset to near-zero          |

### New CSV columns

| Column            | Description                                        |
|-------------------|----------------------------------------------------|
| `Freshness_Status`| One of: ACCEPTED, REPLAY, DUPLICATE, STALE, REBOOT_RESET, OOO_GAP, HMAC_FAIL |
| `Host_Delta_ms`   | Milliseconds since the last accepted packet (host wall-clock) |

### Enhanced Ctrl+C summary

The shutdown summary now includes a dedicated "Freshness & Replay" section
reporting all anomaly counters alongside the existing HMAC and throughput stats.

## 5. Freshness Configuration

| Parameter              | Value  | Rationale                                  |
|------------------------|--------|--------------------------------------------|
| `MAX_STALENESS_SEC`    | 30.0   | Allows for WiFi reconnects and brief outages without false positives |
| `REBOOT_SEQ_THRESHOLD` | 5      | seq <= 5 after a high seq indicates device reboot, not replay |

Both are defined as constants at the top of `host_receiver.py` and
`test_freshness.py`.

## 6. Replay Scenario Analysis

### Scenario A: Classic replay

An attacker captures packet `{seq: 42, ts: 10500, hmac: "abc..."}` and
re-sends it after packet 50 has been accepted.

- **seq_num (42) < last_accepted (50)** --> classified as REPLAY
- Packet is discarded; `replays_detected` incremented

### Scenario B: Duplicate injection

A network glitch or malicious actor delivers packet 42 twice in succession.

- First delivery: accepted normally
- Second delivery: **seq_num (42) == last_accepted (42)** --> DUPLICATE
- Packet is discarded; `duplicates_detected` incremented

### Scenario C: Delayed delivery

A packet is buffered for 45 seconds before reaching the host.

- HMAC passes (packet is unmodified)
- Sequence check passes (seq is advancing)
- **Host delta (45s) > MAX_STALENESS_SEC (30s)** --> STALE
- Packet is discarded; `stale_detected` incremented

### Scenario D: Device reboot

The MCU reboots and seq resets to 1.

- **seq_num (1) <= REBOOT_SEQ_THRESHOLD (5)** and **last_accepted > 5**
- Classified as REBOOT_RESET; tracker resets; packet accepted
- `reboots_detected` incremented

## 7. Test Suite (`test_freshness.py`)

### Test scenarios

| # | Test                        | Method                                       | Expected           |
|---|-----------------------------|----------------------------------------------|---------------------|
| 1 | Normal sequential packets   | Feed seq 1,2,3 with increasing timestamps    | All ACCEPTED        |
| 1b| Sequential roundtrip        | Publish 3 packets through broker              | 3 received via TLS  |
| 2 | Exact replay                | Accept seq 1-3, then re-check seq 2           | REPLAY              |
| 3 | Duplicate                   | Accept seq 1, then re-check seq 1             | DUPLICATE           |
| 4a| Out-of-order gap            | Accept seq 1, skip to seq 3                   | OOO_GAP (accepted)  |
| 4b| Late arrival                | Check seq 2 after seq 3 was accepted           | REPLAY              |
| 5a| Reboot detection            | Set last_accepted=500, then check seq 1        | REBOOT_RESET        |
| 5b| Post-reboot normal          | After reboot reset, check seq 2                | ACCEPTED            |
| 6 | Stale packet                | Set last_accepted_wall_time to 35s ago          | STALE               |

### Running the tests

```bash
cd broker
python3 test_freshness.py
```

### Expected output

```
=======================================================
  MQTT Freshness & Replay Detection Tests (Week 7)
=======================================================

--- Test 1: Normal Sequential Packets ---
  [PASS] Sequential Accepted  -- All 3 packets accepted in order
  [PASS] Sequential Roundtrip  -- Received 3/3 packets via broker

--- Test 2: Exact Replay Detection ---
  [PASS] Replay Rejected  -- seq=2 after accepting seq=3 -> REPLAY

--- Test 3: Duplicate Detection ---
  [PASS] Duplicate Detected  -- seq=1 sent twice -> DUPLICATE

--- Test 4: Out-of-Order Detection ---
  [PASS] Gap Accepted  -- seq=3 after seq=1 -> OOO_GAP
  [PASS] Late Packet Rejected  -- seq=2 after accepting seq=3 -> REPLAY

--- Test 5: Device Reboot Detection ---
  [PASS] Reboot Detected  -- seq=1 after seq=500 -> REBOOT_RESET
  [PASS] Post-Reboot Normal  -- seq=2 after reboot reset -> ACCEPTED

--- Test 6: Stale Packet Detection ---
  [PASS] Stale Packet Flagged  -- 35s gap -> STALE

=======================================================
  SUMMARY
=======================================================
  [PASS] Sequential Accepted
  [PASS] Sequential Roundtrip
  [PASS] Replay Rejected
  [PASS] Duplicate Detected
  [PASS] Gap Accepted
  [PASS] Late Packet Rejected
  [PASS] Reboot Detected
  [PASS] Post-Reboot Normal
  [PASS] Stale Packet Flagged

  9/9 tests passed.
=======================================================
```

## 8. Limitations and Future Work

| Limitation                       | Impact                                            | Planned fix             |
|----------------------------------|---------------------------------------------------|-------------------------|
| No wall-clock sync (NTP)         | Board timestamp is relative, not absolute          | Acceptable; monotonicity is sufficient |
| Reboot heuristic is simple       | Edge case: exactly 5 packets sent before crash     | Could add boot counter in NVS |
| Staleness window is fixed        | 30s may be too strict or too lenient for some deployments | Make configurable per-deployment |
| uint32_t timestamp wraps at ~49d | Long-running deployments could see wrap-around     | Reset on reboot; 49d is acceptable |
| No inter-packet timing analysis  | Anomalous packet rates not yet flagged             | Week 8: timing monitoring |

The freshness layer completes the **sequence + replay protection** planned for
Week 7.  Week 8 will add inter-arrival time monitoring and anomaly detection
on top of this validated packet stream.
