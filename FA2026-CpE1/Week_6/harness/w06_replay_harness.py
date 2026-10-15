"""
w06_replay_harness.py

Offline replay harness for CpE-1 Week 6. Drives the UNMODIFIED freshness
logic from the Spring receiver (Sp2026-CpE2/merged_project/broker/host_receiver.py)
against a victim telemetry stream into which replay episodes are injected.

The receiver module is loaded by path and its check_freshness / accept_packet /
verify_hmac functions are used as-is. Wall-clock time in the module is replaced
by a harness-controlled virtual clock so the 30 s staleness rule is exercised
deterministically. No receiver code is edited.

Attack codes modeled (attack_taxonomy.json v1.0.0, family A2):
  A2.1 packet_replay_verbatim      IP-T  old packet resent byte-identical
  A2.2 window_replay               IP-T  contiguous N-packet segment resent
  A2.3 payload_replay_fresh_header IP-F  old payload, current seq/ts, HMAC recomputed
"""
import importlib.util, os, types, hmac, hashlib

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..",
                    "lab-scale-bridge-monitoring")
RECV = os.path.join(REPO, "Sp2026-CpE2", "merged_project", "broker", "host_receiver.py")


def load_receiver(scratch):
    """Import host_receiver.py unmodified, module-level CSV writes redirected
    into a scratch dir, with a virtual clock installed for staleness math."""
    import sys
    class _Dummy:
        def __init__(self,*a,**k): pass
        def __getattr__(self,n): return lambda *a,**k: None
    fake=types.ModuleType("paho"); fakem=types.ModuleType("paho.mqtt"); fakec=types.ModuleType("paho.mqtt.client")
    fakec.Client=_Dummy; fakem.client=fakec; fake.mqtt=fakem
    sys.modules.setdefault("paho",fake); sys.modules.setdefault("paho.mqtt",fakem); sys.modules.setdefault("paho.mqtt.client",fakec)
    bdir = os.path.dirname(RECV)
    if bdir not in sys.path:
        sys.path.insert(0, bdir)
    cwd = os.getcwd()
    os.makedirs(scratch, exist_ok=True)
    os.chdir(scratch)
    try:
        spec = importlib.util.spec_from_file_location("host_receiver", RECV)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.chdir(cwd)
    clock = {"t": 0.0}
    mod.time = types.SimpleNamespace(time=lambda: clock["t"])
    mod._clock = clock
    return mod


def reset(mod):
    mod.last_accepted_seq = None
    mod.last_accepted_board_ts = None
    mod.last_accepted_wall_time = None
    for g in ("replays_detected", "duplicates_detected", "stale_detected",
              "ooo_detected", "reboots_detected", "packets_lost"):
        setattr(mod, g, 0)


def recompute_hmac(mod, device_id, seq, board_ts, temp, hum):
    """Attacker-with-key-material HMAC (models the IP-F compromised node for A2.3),
    using the receiver's own key and canonical form so the packet verifies."""
    canonical = f"{device_id}|{seq}|{board_ts}|{temp:.1f}|{hum:.1f}"
    return hmac.new(mod.HMAC_KEY, canonical.encode(), hashlib.sha256).hexdigest()


def process(mod, data, wall_time):
    """Run one packet through the receiver decision path exactly as on_message:
    HMAC verify, then check_freshness. Returns the receiver status string."""
    mod._clock["t"] = wall_time
    verified, _ = mod.verify_hmac(data)
    if not verified:
        return "HMAC_FAIL"
    seq, board = data["seq_num"], data["timestamp_ms"]
    accepted, status = mod.check_freshness(seq, board)
    if accepted:
        mod.accept_packet(seq, board)
    return status
