"""
timing_monitor.py

Standalone timing-anomaly detection module for the IoT Digital Twin host
receiver.  Tracks inter-arrival statistics over a rolling window, computes
z-scores, and flags anomalous latency spikes or bursts.

Designed to be imported by host_receiver.py and tested independently.
"""

from collections import deque, namedtuple
import math

# --- Configuration ---
WINDOW_SIZE = 50
JITTER_Z_THRESHOLD = 3.0
MIN_SAMPLES_FOR_BASELINE = 10

TimingFeatures = namedtuple("TimingFeatures", [
    "host_delta_ms",
    "board_delta_ms",
    "host_mean_ms",
    "host_std_ms",
    "host_z_score",
    "board_jitter_ms",
    "anomaly",
])


class TimingMonitor:
    """Rolling-window timing analysis with z-score anomaly detection."""

    def __init__(self, window_size=WINDOW_SIZE, z_threshold=JITTER_Z_THRESHOLD,
                 min_samples=MIN_SAMPLES_FOR_BASELINE):
        self.window_size = window_size
        self.z_threshold = z_threshold
        self.min_samples = min_samples

        self._host_deltas = deque(maxlen=window_size)
        self._board_deltas = deque(maxlen=window_size)

        self.anomalies_detected = 0
        self.total_recorded = 0

        self._lifetime_host_sum = 0.0
        self._lifetime_host_sq_sum = 0.0
        self._lifetime_host_min = float("inf")
        self._lifetime_host_max = 0.0
        self._lifetime_board_jitter_sum = 0.0

    def record(self, host_delta_ms, board_delta_ms):
        """
        Record a new inter-arrival sample and return computed features.
        Call once per accepted packet.
        """
        self._host_deltas.append(host_delta_ms)
        self._board_deltas.append(board_delta_ms)
        self.total_recorded += 1

        self._lifetime_host_sum += host_delta_ms
        self._lifetime_host_sq_sum += host_delta_ms ** 2
        if host_delta_ms < self._lifetime_host_min:
            self._lifetime_host_min = host_delta_ms
        if host_delta_ms > self._lifetime_host_max:
            self._lifetime_host_max = host_delta_ms

        n = len(self._host_deltas)
        host_mean = _mean(self._host_deltas)
        host_std = _std(self._host_deltas, host_mean)

        board_mean = _mean(self._board_deltas)
        board_jitter = abs(board_delta_ms - board_mean)
        self._lifetime_board_jitter_sum += board_jitter

        if n >= self.min_samples and host_std > 0:
            z_score = (host_delta_ms - host_mean) / host_std
        else:
            z_score = 0.0

        anomaly = abs(z_score) > self.z_threshold
        if anomaly:
            self.anomalies_detected += 1

        return TimingFeatures(
            host_delta_ms=host_delta_ms,
            board_delta_ms=board_delta_ms,
            host_mean_ms=round(host_mean, 2),
            host_std_ms=round(host_std, 2),
            host_z_score=round(z_score, 3),
            board_jitter_ms=round(board_jitter, 2),
            anomaly=anomaly,
        )

    def summary(self):
        """Return a dict of lifetime statistics for the shutdown report."""
        n = self.total_recorded
        if n == 0:
            return {}

        lifetime_mean = self._lifetime_host_sum / n
        variance = (self._lifetime_host_sq_sum / n) - (lifetime_mean ** 2)
        lifetime_std = math.sqrt(max(variance, 0))

        board_jitter_mean = self._lifetime_board_jitter_sum / n

        return {
            "total_samples": n,
            "anomalies": self.anomalies_detected,
            "host_mean_ms": round(lifetime_mean, 2),
            "host_std_ms": round(lifetime_std, 2),
            "host_min_ms": round(self._lifetime_host_min, 2),
            "host_max_ms": round(self._lifetime_host_max, 2),
            "board_jitter_mean_ms": round(board_jitter_mean, 2),
        }

    def reset(self):
        """Clear all state (e.g. on device reboot)."""
        self._host_deltas.clear()
        self._board_deltas.clear()


def _mean(dq):
    n = len(dq)
    if n == 0:
        return 0.0
    return sum(dq) / n


def _std(dq, mean_val):
    n = len(dq)
    if n < 2:
        return 0.0
    variance = sum((x - mean_val) ** 2 for x in dq) / n
    return math.sqrt(variance)
