"""
w06_generate.py  --  CpE-1 Week 6 replay dataset generator (packet track).

Builds A2.1 / A2.2 / A2.3 replay episodes on the real Week 3 clean carrier
(session S20260501-02, 428 authenticated packets), runs every resulting stream
through the unmodified receiver freshness logic via w06_replay_harness, and
writes one labeled CSV + JSON sidecar per episode in the Week 4 packet format.

Ground-truth labels are set by construction (what the attacker did). The
receiver verdict is carried as a separate feature column and is never the label
(labels_schema prohibited_label_sources).
"""
import importlib.util, os, json, csv, hashlib, hmac as H, datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

HERE = os.path.dirname(os.path.abspath(__file__))
W6 = os.path.dirname(HERE)
CARRIER = os.path.join(W6, "..", "Week 3", "w03_A0-0_none_none_r01.csv")
AES_KEY = b"LabKey12LabKey12"
HMAC_KEY = bytes([0x4d,0x79,0x53,0x65,0x63,0x75,0x72,0x65,0x44,0x69,0x67,0x69,0x74,0x61,0x6c,0x54,
                  0x77,0x69,0x6e,0x4b,0x65,0x79,0x32,0x30,0x32,0x36,0x21,0x40,0x23,0x24,0x25,0x5e])

spec = importlib.util.spec_from_file_location("h", os.path.join(HERE, "w06_replay_harness.py"))
h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
MOD = h.load_receiver("/tmp/w06scratch")

OUT_HEADER = ["packet_id","session_id","host_timestamp","schema_version","device_id",
    "seq_num","timestamp_ms","temperature_c","humidity","pwm_duty_us","pwm_period_us",
    "host_delta_ms","canonical_string","hmac","decrypted","encrypted_hex",
    "receiver_detection_result","episode_id","attack_code","attack_family","attack_active",
    "injection_point","target_layer","target_channel","severity","deviation_abs",
    "ground_truth_value","duration_class","onset_class","episode_elapsed_ms",
    "label_confidence","replay_source_seq","source_row_index"]


def load_carrier():
    rows = []
    with open(CARRIER) as f:
        for r in csv.DictReader(f):
            if r["session_id"] != "S20260501-02":
                continue
            rows.append(r)
    return rows


def canon(dev, seq, board, temp, hum):
    return f"{dev}|{seq}|{board}|{temp:.1f}|{hum:.1f}"


def forge(dev, seq, board, temp, hum, pwm_duty, pwm_period, schema="1.1.0"):
    """Build a wire packet (JSON + HMAC + AES-ECB hex) that verifies at the
    receiver. Models the IP-F compromised node (has key material)."""
    c = canon(dev, seq, board, temp, hum)
    tag = H.new(HMAC_KEY, c.encode(), hashlib.sha256).hexdigest()
    obj = {"schema_version": schema, "device_id": dev, "seq_num": seq,
           "timestamp_ms": board,
           "telemetry": {"temperature_c": temp, "humidity": hum,
                         "pwm_duty_us": int(pwm_duty), "pwm_period_us": int(pwm_period)},
           "hmac": tag}
    pt = json.dumps(obj, separators=(",", ":"))
    ct = AES.new(AES_KEY, AES.MODE_ECB).encrypt(pad(pt.encode(), 16)).hex().upper()
    return c, tag, pt, ct


def datadict(dev, seq, board, temp, hum):
    return {"schema_version": "1.1.0", "device_id": dev, "seq_num": seq,
            "timestamp_ms": board,
            "telemetry": {"temperature_c": temp, "humidity": hum,
                          "pwm_duty_us": 7000, "pwm_period_us": 10000}}


def base_row_from_carrier(cr):
    """A clean carrier packet as an output row template (verbatim wire bytes)."""
    return dict(session_id="S20260501-02", schema_version=cr["schema_version"],
        device_id=cr["device_id"], seq_num=int(cr["seq_num"]),
        timestamp_ms=int(cr["timestamp_ms"]), temperature_c=float(cr["temperature_c"]),
        humidity=float(cr["humidity"]), pwm_duty_us=int(cr["pwm_duty_us"]),
        pwm_period_us=int(cr["pwm_period_us"]), host_delta_ms=int(cr["host_delta_ms"]),
        canonical_string=cr["canonical_string"], hmac=cr["hmac"],
        decrypted=cr["decrypted"], encrypted_hex=cr["encrypted_hex"],
        source_row_index=cr["source_row_index"])


def dur_class(n):
    return "D0" if n == 1 else "D1" if n <= 10 else "D2" if n <= 100 else "D3"


def emit(rows, meta, out_dir):
    """Write one episode CSV + JSON sidecar; fill sha256 into the sidecar."""
    base = "w06_" + meta["attack_code"].replace(".", "-") + "_" + meta["chan"] + "_" + meta["sev"] + "_r" + meta["run"]
    csv_path = os.path.join(out_dir, base + ".csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_HEADER); w.writeheader()
        for i, r in enumerate(rows, 1):
            r["packet_id"] = i
            w.writerow({k: r.get(k, "") for k in OUT_HEADER})
    sha = hashlib.sha256(open(csv_path, "rb").read()).hexdigest()
    meta["sidecar"]["integrity"]["sha256"] = sha
    json.dump(meta["sidecar"], open(os.path.join(out_dir, base + ".json"), "w"), indent=2)
    return base, csv_path, sha


def run_stream(events):
    """events: list of (row_dict, wall_time, is_attack). Runs each through the
    receiver in order and stamps receiver_detection_result. Returns rows."""
    h.reset(MOD)
    out = []
    for row, wt, _ in events:
        d = datadict(row["device_id"], row["seq_num"], row["timestamp_ms"],
                     row["temperature_c"], row["humidity"])
        # verbatim carrier rows already carry a valid hmac; forged rows too.
        d["hmac"] = row["hmac"]
        status = h.process(MOD, d, wt)
        row["receiver_detection_result"] = status
        out.append(row)
    return out


def label_clean(row, wt):
    row.update(episode_id="CPE1-F26-W06-A0.0-R00", attack_code="A0.0", attack_family="A0",
        attack_active=False, injection_point="none", target_layer="none",
        target_channel="none", severity="none", deviation_abs="", ground_truth_value="",
        duration_class="none", onset_class="none", episode_elapsed_ms="",
        label_confidence="certain", replay_source_seq="")
    return row


CARR = load_carrier()
DEV = "CC3220SF_NODE_01"
FW = "post-hoc"
RECV_COMMIT = "243de71d7ec755eb46457052bfa498674952fb54"


def wall_times(events):
    """Assign monotone virtual wall times (s) from per-row host_delta_ms."""
    t = 0.0; out = []
    for row, is_atk, dt_ms in events:
        t += dt_ms / 1000.0
        out.append((row, t, is_atk))
    return out


def sidecar(code, ip, chan_layer, params, note, nclean, natk, limitations, onset="abrupt"):
    return {"episode_id": None, "taxonomy_version": "1.0.0", "attack_code": code,
        "attack_code_set": [code], "injection_point": ip, "operator": "CpE-1 Fall 2026 (Bruce)",
        "capture": {"start_utc": "2026-05-01T13:10:47.483Z", "packet_count": nclean + natk,
            "attacked_packet_count": natk, "schema_version": "1.1.0", "firmware_commit": FW,
            "receiver_commit": RECV_COMMIT, "nominal_publish_interval_ms": 204,
            "carrier": "w03_A0-0_none_none_r01.csv (S20260501-02)"},
        "physical_conditions": {"beam_configuration": "not_instrumented",
            "excitation_period_us": 10000, "payload_is_physical": False, "note": note},
        "parameters": params,
        "benign_anomalies_present": ["N1.1", "N1.2", "N1.3"],
        "class_balance": {"clean_records": nclean, "attack_records": natk,
            "benign_anomaly_records": 0, "ambiguous_records": 0},
        "integrity": {"hmac_recomputed": True, "sha256": None,
            "note": "Carrier packets carry their original valid HMAC. A2.3 forged packets "
                    "carry a freshly computed valid HMAC over the replayed payload (models the "
                    "IP-F compromised node). Every row verifies under host_receiver logic."},
        "known_limitations": limitations}


LIMITS_IPT = [
 "Carrier sensor values are the firmware rand() stub (payload_is_physical false). This episode "
 "demonstrates the transport-layer freshness response to replay, which is independent of payload "
 "content and therefore valid on the stub.",
 "receiver_detection_result is the receiver verdict, carried as a feature. The ground-truth label "
 "is attack_code, set by construction. Do not train on the verdict (labels_schema prohibited_label_sources)."]
LIMITS_IPF = [
 "Carrier sensor values are the firmware rand() stub. A2.3 defeats every crypto and freshness check, "
 "so at the packet layer the replayed rows are indistinguishable from clean by construction: recall at "
 "the communication layer is zero. Separating them requires physical plausibility against the concurrent "
 "load condition, which needs the real sensor channels (deferred until sensor integration).",
 "deviation_abs and ground_truth_value are the temperature difference from the true concurrent carrier "
 "value; humidity is replayed in the same rows. These are provided for later twin scoring, not as a "
 "packet-layer discriminator.",
 "receiver_detection_result is the receiver verdict, carried as a feature, never the label."]


def mk_clean(cr):
    return base_row_from_carrier(cr)


def build_A21(out_dir, run, mode):
    """Single verbatim replay (D0). mode in {reboot,regress,dup}."""
    P = 40                      # clean prefix length
    events = [(mk_clean(CARR[i]), False, int(CARR[i]["host_delta_ms"])) for i in range(P)]
    last = CARR[P-1]
    if mode == "reboot":
        src = CARR[0]           # original seq 1  -> reboot-range
        chan, note = "packet", "Verbatim replay of a captured low-sequence packet. Receiver reboot heuristic (seq<=5) accepts it and resets tracking."
    elif mode == "regress":
        src = CARR[5]           # a mid seq that regresses below current
        chan, note = "packet", "Verbatim replay of an earlier captured packet whose sequence regresses below the last accepted. Receiver flags REPLAY."
    else:
        src = last              # exact duplicate of current last accepted
        chan, note = "packet", "Verbatim replay (exact duplicate) of the most recently accepted packet. Receiver flags DUPLICATE."
    inj = mk_clean(src)
    ev_inj = (inj, True, 10)    # injected ~immediately after prefix
    events.append(ev_inj)
    for i in range(P, P+8):     # short clean suffix
        events.append((mk_clean(CARR[i]), False, int(CARR[i]["host_delta_ms"])))
    events = wall_times(events)
    rows = run_stream(events)
    natk = 0
    for (row, wt, is_atk) in [(r, e[1], e[2]) for r, e in zip(rows, events)]:
        pass
    # label
    e0 = events[0][1]
    for idx, (row, wt, is_atk) in enumerate(zip(rows, [e[1] for e in events], [e[2] for e in events])):
        if is_atk:
            natk += 1
            row.update(episode_id=f"CPE1-F26-W06-A2.1-R{run}", attack_code="A2.1",
                attack_family="A2", attack_active=True, injection_point="IP-T",
                target_layer="L3", target_channel="packet", severity="none",
                deviation_abs="", ground_truth_value="", duration_class="D0",
                onset_class="abrupt", episode_elapsed_ms=0, label_confidence="certain",
                replay_source_seq=int(src["seq_num"]))
        else:
            label_clean(row, wt)
    nclean = len(rows) - natk
    params = {"mode": mode, "source_seq_range": [int(src["seq_num"]), int(src["seq_num"])],
              "replay_offset_ms": 10, "window_length_packets": 1}
    sc = sidecar("A2.1", "IP-T", "L3", params, note, nclean, natk, LIMITS_IPT)
    sc["episode_id"] = f"CPE1-F26-W06-A2.1-R{run}"
    return emit(rows, {"attack_code": "A2.1", "chan": chan, "sev": "S0", "run": run, "sidecar": sc}, out_dir)


def build_A22(out_dir, run, W):
    """Window replay (IP-T): contiguous captured segment starting at the safe
    start of the session (reboot-range seq) replayed mid-stream."""
    P = 60
    events = [(mk_clean(CARR[i]), False, int(CARR[i]["host_delta_ms"])) for i in range(P)]
    seg = [mk_clean(CARR[i]) for i in range(0, W)]       # captured window from session start
    for s in seg:
        events.append((s, True, 205))
    for i in range(P, P+10):
        events.append((mk_clean(CARR[i]), False, int(CARR[i]["host_delta_ms"])))
    events = wall_times(events)
    rows = run_stream(events)
    natk = 0; t0 = None
    for row, wt, is_atk in [(r, e[1], e[2]) for r, e in zip(rows, events)]:
        if is_atk:
            if t0 is None: t0 = wt
            natk += 1
            row.update(episode_id=f"CPE1-F26-W06-A2.2-R{run}", attack_code="A2.2",
                attack_family="A2", attack_active=True, injection_point="IP-T",
                target_layer="L3", target_channel="packet", severity="none",
                deviation_abs="", ground_truth_value="", duration_class=dur_class(W),
                onset_class="abrupt", episode_elapsed_ms=int((wt-t0)*1000),
                label_confidence="certain", replay_source_seq=int(row["seq_num"]))
        else:
            label_clean(row, wt)
    nclean = len(rows) - natk
    note = (f"Window replay of a {W}-packet contiguous segment captured at session start "
            f"(reboot-range starting sequence). The first replayed packet trips the reboot heuristic; "
            f"the remainder are accepted as a fresh stream.")
    params = {"window_length_packets": W, "capture_condition": "session_start_safe",
              "injection_condition": "mid_stream_live", "source_seq_range": [int(seg[0]["seq_num"]), int(seg[-1]["seq_num"])]}
    sc = sidecar("A2.2", "IP-T", "L3", params, note, nclean, natk, LIMITS_IPT)
    sc["episode_id"] = f"CPE1-F26-W06-A2.2-R{run}"
    return emit(rows, {"attack_code": "A2.2", "chan": "packet", "sev": "S0", "run": run, "sidecar": sc}, out_dir)


def build_A23(out_dir, run, W):
    """Payload replay under fresh header (IP-F): live seqs continue increasing,
    telemetry copied from an earlier safe segment, HMAC+ciphertext reforged."""
    P = 60
    events = [(mk_clean(CARR[i]), False, int(CARR[i]["host_delta_ms"])) for i in range(P)]
    src_seg = [CARR[i] for i in range(0, W)]             # stale safe payloads
    last_seq = int(CARR[P-1]["seq_num"]); last_ts = int(CARR[P-1]["timestamp_ms"])
    forged = []
    for k in range(W):
        seq = last_seq + 1 + k
        ts = last_ts + 205 * (k + 1)
        true_row = CARR[P + k]                            # concurrent clean packet (ground truth)
        s = src_seg[k]
        temp = float(s["temperature_c"]); hum = float(s["humidity"])
        c, tag, pt, ct = forge(DEV, seq, ts, temp, hum, 7000, 10000)
        row = dict(session_id="S20260501-02", schema_version="1.1.0", device_id=DEV,
            seq_num=seq, timestamp_ms=ts, temperature_c=temp, humidity=hum,
            pwm_duty_us=7000, pwm_period_us=10000, host_delta_ms=205,
            canonical_string=c, hmac=tag, decrypted=pt, encrypted_hex=ct,
            source_row_index=s["source_row_index"],
            _true_temp=float(true_row["temperature_c"]))
        forged.append((row, True, 205))
    events += forged
    for i in range(P+W, P+W+10):                         # clean suffix (live continues)
        events.append((mk_clean(CARR[i]), False, int(CARR[i]["host_delta_ms"])))
    events = wall_times(events)
    rows = run_stream(events)
    natk = 0; t0 = None
    for row, wt, is_atk in [(r, e[1], e[2]) for r, e in zip(rows, events)]:
        if is_atk:
            if t0 is None: t0 = wt
            natk += 1
            dev = round(row["temperature_c"] - row.pop("_true_temp"), 3)
            row.update(episode_id=f"CPE1-F26-W06-A2.3-R{run}", attack_code="A2.3",
                attack_family="A2", attack_active=True, injection_point="IP-F",
                target_layer="L3", target_channel="multi", severity="PENDING",
                deviation_abs=dev, ground_truth_value=round(row["temperature_c"]-dev, 3),
                duration_class=dur_class(W), onset_class="abrupt",
                episode_elapsed_ms=int((wt-t0)*1000), label_confidence="certain",
                replay_source_seq=int(src_seg[natk-1]["seq_num"]))
        else:
            row.pop("_true_temp", None); label_clean(row, wt)
    nclean = len(rows) - natk
    note = (f"Fresh-header payload replay of a {W}-packet stale safe segment. Sequence and timestamp "
            f"advance normally and the HMAC is recomputed, so every packet is ACCEPTED. Cyber-valid, "
            f"physically stale.")
    params = {"window_length_packets": W, "source_seq_range": [int(src_seg[0]["seq_num"]), int(src_seg[-1]["seq_num"])]}
    sc = sidecar("A2.3", "IP-F", "L3", params, note, nclean, natk, LIMITS_IPF)
    sc["episode_id"] = f"CPE1-F26-W06-A2.3-R{run}"
    return emit(rows, {"attack_code": "A2.3", "chan": "multi", "sev": "PENDING", "run": run, "sidecar": sc}, out_dir)


def main():
    out = os.path.join(W6, "packet")
    made = []
    for run, mode in zip(("01", "02", "03"), ("reboot", "regress", "dup")):
        made.append(("A2.1", mode, build_A21(out, run, mode)))
    for run, W in zip(("01", "02", "03", "04"), (1, 5, 20, 60)):
        made.append(("A2.2", W, build_A22(out, run, W)))
    for run, W in zip(("01", "02", "03", "04"), (1, 5, 20, 60)):
        made.append(("A2.3", W, build_A23(out, run, W)))
    for code, p, (base, path, sha) in made:
        print(f"{code:5} {str(p):8} {base:32} sha {sha[:12]}")
    return made


if __name__ == "__main__":
    main()
