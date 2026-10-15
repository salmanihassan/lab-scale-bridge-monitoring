"""w06_package.py -- build the Week 6 manifest and the flat CpE-2 file from packet/.
Reads only the episode CSVs and JSON sidecars, so it can be re-run after any regeneration."""
import os, csv, json, glob, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__)); W6 = os.path.dirname(HERE)
OUT = sys.argv[1] if len(sys.argv) > 1 else W6
TYPE = {"A0.0": "NORMAL", "A2.1": "REPLAY_VERBATIM", "A2.2": "REPLAY_WINDOW",
        "A2.3": "REPLAY_PAYLOAD_FRESH_HEADER"}
FLAT = ["packet_id", "seq_num", "timestamp_ms", "attack_type", "attack_parameter",
        "encrypted_hex", "decrypted", "hmac", "detection_result", "notes"]

def order(p):
    b = os.path.basename(p); return (b.split("_")[1], b)

files = sorted(glob.glob(os.path.join(W6, "packet", "*.csv")), key=order)
flat = []; eps = []; tc = ta = 0
for p in files:
    rows = list(csv.DictReader(open(p, newline="")))
    sc = json.load(open(p[:-4] + ".json"))
    atk = [r for r in rows if r["attack_active"] == "True"]
    for r in rows:
        code = r["attack_code"]
        if code == "A0.0":
            param = "0"
            note = f"CpE-1 A0.0 clean carrier; episode={r['episode_id']}; receiver={r['receiver_detection_result']}"
        else:
            param = r["replay_source_seq"]
            note = (f"CpE-1 {code} {r['target_channel']} src_seq={r['replay_source_seq']}; episode={r['episode_id']}; "
                    f"injection={r['injection_point']}; receiver={r['receiver_detection_result']}")
        flat.append({"packet_id": len(flat) + 1, "seq_num": r["seq_num"], "timestamp_ms": r["timestamp_ms"],
                     "attack_type": TYPE[code], "attack_parameter": param, "encrypted_hex": r["encrypted_hex"],
                     "decrypted": r["decrypted"], "hmac": r["hmac"],
                     "detection_result": r["receiver_detection_result"], "notes": note})
    v = collections.Counter(r["receiver_detection_result"] for r in atk)
    caught = sum(n for k, n in v.items() if k in ("REPLAY", "DUPLICATE", "STALE"))
    eps.append({"file": os.path.basename(p), "episode_id": sc["episode_id"], "code": sc["attack_code"],
                "injection_point": sc["injection_point"], "packets": len(rows), "clean": len(rows) - len(atk),
                "attack": len(atk), "window": sc["parameters"].get("window_length_packets", 1),
                "receiver_verdicts": dict(v), "comm_layer_caught": caught, "sha256": sc["integrity"]["sha256"]})
    tc += len(rows) - len(atk); ta += len(atk)

man = {"week": 6, "track": "packet", "attack_family": "A2 replay", "taxonomy_version": "1.0.0",
       "carrier": "w03_A0-0_none_none_r01.csv (S20260501-02)",
       "receiver_commit": "243de71d7ec755eb46457052bfa498674952fb54",
       "episodes": eps, "totals": {"episodes": len(eps), "clean_records": tc, "attack_records": ta}}
os.makedirs(os.path.join(OUT, "cpe2_format"), exist_ok=True)
with open(os.path.join(OUT, "cpe2_format", "w06_replay_cpe2_format.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FLAT); w.writeheader(); w.writerows(flat)
json.dump(man, open(os.path.join(OUT, "w06_manifest.json"), "w"), indent=2)
print(f"{len(eps)} episodes, {tc} clean, {ta} attack, {len(flat)} flat rows")
