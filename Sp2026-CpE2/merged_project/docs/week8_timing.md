# Timing-Anomaly Monitoring -- Week 8

This document describes the timing-anomaly detection module added in Week 8,
which measures packet inter-arrival times, detects abnormal jitter and latency
spikes via z-score analysis, and exports timing features for future AI/ML use.

## 1. Problem Statement

Even after authenticated integrity (Week 6) and freshness validation (Week 7),
an attacker can still disrupt the digital-twin pipeline through **timing-based
attacks**:

| Attack               | Description                                           |
|----------------------|-------------------------------------------------------|
| Delay injection      | Holding valid packets and releasing them after a pause |
| Burst flooding       | Replaying packets at abnormally high rates             |
| Jitter manipulation  | Introducing variable latency to destabilize control    |
| Denial of service    | Dropping packets to create large inter-arrival gaps    |

These attacks produce measurable deviations in inter-arrival timing that
statistical methods can flag in real time.

## 2. Solution Overview

A standalone `TimingMonitor` class maintains a **rolling window** of
inter-arrival times and computes a **z-score** for each new sample. When the
z-score exceeds a configurable threshold, the packet is flagged as a timing
anomaly.

```
                     ┌─────────────────┐
  Accepted Packet ──>│  TimingMonitor   │──> TimingFeatures (namedtuple)
                     │  - rolling window│         │
                     │  - mean / std    │         ├──> timing_features.csv
                     │  - z-score check │         ├──> [TIMING ALERT] console
                     └─────────────────┘         └──> Ctrl+C summary
```

## 3. Timing Features

Each accepted packet produces a `TimingFeatures` record with the following
fields, which serve as the ML feature vector for future anomaly-detection
models:

| Feature           | Type   | Description                                        |
|-------------------|--------|----------------------------------------------------|
| `host_delta_ms`   | int    | Host wall-clock milliseconds since last packet     |
| `board_delta_ms`  | int    | MCU-side interval (board timestamps)               |
| `host_mean_ms`    | float  | Rolling mean of host inter-arrival times            |
| `host_std_ms`     | float  | Rolling standard deviation of host IATs             |
| `host_z_score`    | float  | Z-score of current host delta                      |
| `board_jitter_ms` | float  | Absolute deviation of board delta from board mean   |
| `anomaly`         | bool   | True if \|z-score\| > threshold                    |

## 4. Z-Score Anomaly Detection

The z-score measures how many standard deviations a sample is from the rolling
mean:

```
z = (delta - mean) / std
```

Under the assumption of approximately normally distributed inter-arrival
times:

- |z| < 2: ~95% of normal traffic
- |z| < 3: ~99.7% of normal traffic
- **|z| > 3**: flagged as anomaly (default threshold)

Both positive (large delay) and negative (burst) z-scores trigger alerts.

A **minimum sample requirement** (default: 10) prevents false positives during
the warm-up period when the standard deviation estimate is unstable.

## 5. Configuration Parameters

| Parameter                 | Default | Description                                     |
|---------------------------|---------|-------------------------------------------------|
| `WINDOW_SIZE`             | 50      | Number of samples in the rolling window         |
| `JITTER_Z_THRESHOLD`     | 3.0     | Z-score threshold for anomaly flagging          |
| `MIN_SAMPLES_FOR_BASELINE`| 10     | Minimum samples before z-score detection begins |

These are defined at the top of `broker/timing_monitor.py` and can be tuned
based on the specific deployment environment.

## 6. Integration with Host Receiver

The `TimingMonitor` is instantiated as a global in `host_receiver.py` and
called after each accepted packet:

1. Compute `board_delta_ms` from consecutive board timestamps
2. Call `timing.record(host_delta_ms, board_delta_ms)`
3. If `features.anomaly` is True, print a `[TIMING ALERT]` with the z-score
4. Write features to `timing_features.csv`
5. On device reboot (`REBOOT_RESET`), call `timing.reset()` to clear the window

### CSV Output

Two CSV files are produced:

| File                        | Content                     | Purpose             |
|-----------------------------|-----------------------------|---------------------|
| `raw_dataset_encrypted.csv` | Full telemetry + HMAC/fresh | Weeks 5-7 dataset   |
| `timing_features.csv`       | Timing features per packet  | Week 8+ ML features |

### Enhanced Ctrl+C Summary

The shutdown report now includes a "Timing Analysis" section:

```
--- Timing Analysis ---
Timing Samples:       120
Timing Anomalies:     2
Host IAT Mean:        251.34 ms
Host IAT Std:         12.87 ms
Host IAT Min:         238.00 ms
Host IAT Max:         1842.00 ms
Board Jitter Mean:    3.21 ms
```

## 7. Test Suite

The test suite (`broker/test_timing.py`) validates the `TimingMonitor` class
with six test scenarios:

| #  | Scenario                   | Expected Result                            |
|----|----------------------------|--------------------------------------------|
| 1  | 20 uniform intervals       | No anomalies detected                      |
| 2  | 19 uniform + 1 spike       | Spike flagged, z > 3.0                     |
| 3  | Irregular but bounded      | Few or no anomalies (within 3-sigma)       |
| 4  | Burst of fast packets      | Negative z-scores, flagged as anomaly      |
| 5  | Feature completeness       | All TimingFeatures fields non-None         |
| 6  | Broker roundtrip           | 5 packets relayed, timing CSV written      |

### Running the tests

```bash
cd broker
python3 test_timing.py
```

### Expected output

```
=======================================================
  Timing-Anomaly Detection Tests (Week 8)
=======================================================

--- Test 1: Uniform Intervals (no anomalies) ---
  [PASS] Uniform No Anomalies  -- anomalies=0 (expected 0)

--- Test 2: Latency Spike Detection ---
  [PASS] Spike Flagged  -- z=4.36, anomaly=True
  [PASS] Spike Z-Score Positive  -- z=4.36 (expected > 3.0)

--- Test 3: Irregular But Bounded Intervals ---
  [PASS] Irregular Few Anomalies  -- anomalies=1 (expected <= 2)

--- Test 4: Fast Burst Detection ---
  [PASS] Burst Anomalies Flagged  -- burst anomalies=1 (expected >= 1)

--- Test 5: Feature Completeness ---
  [PASS] All Fields Populated
  [PASS] Summary Correct

--- Test 6: Broker Roundtrip with Timing ---
  [PASS] Broker Roundtrip  -- Received 5/5 packets via broker

=======================================================
  SUMMARY
=======================================================
  9/9 tests passed.
=======================================================
```

## 8. How Timing Features Feed Into Future ML Pipeline

The `timing_features.csv` file is designed as a ready-to-use ML dataset.
Each row is a labeled sample where:

- **Features**: `host_delta_ms`, `board_delta_ms`, `host_mean_ms`,
  `host_std_ms`, `host_z_score`, `board_jitter_ms`
- **Label**: `anomaly` (boolean ground truth from z-score detection)

In Week 9+, these features will be used to:

1. Train a supervised classifier (e.g., Random Forest, SVM) to distinguish
   attack patterns from normal network variation
2. Build an unsupervised anomaly detector (e.g., Isolation Forest) that can
   catch novel attack types not captured by z-score alone
3. Combine timing features with integrity/freshness labels for a multi-signal
   anomaly detection model

## 9. Files Changed

| File                            | Change                                          |
|---------------------------------|-------------------------------------------------|
| `broker/timing_monitor.py`      | **New** -- standalone TimingMonitor class        |
| `broker/host_receiver.py`       | Integrated timing monitor, timing CSV, summary  |
| `broker/test_timing.py`         | **New** -- 6 timing anomaly test scenarios       |
| `docs/week8_timing.md`          | **New** -- this document                        |
| `docs/integrity_authentication.md` | Updated threat table (timing = done)         |

## 10. Limitations and Future Work

| Limitation                          | Impact                                       | Planned fix              |
|-------------------------------------|----------------------------------------------|--------------------------|
| Assumes roughly normal distribution | Non-Gaussian traffic may cause false alarms  | ML model in Week 9       |
| Fixed z-threshold                   | Not adaptive to changing network conditions  | Online learning          |
| Window resets on reboot             | Brief warm-up gap after device reboot        | Persist baseline to disk |
| Host-clock only                     | NTP drift could affect host delta accuracy   | Board-side RTT analysis  |
