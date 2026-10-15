"""
extract_static.py
REPS Digital Twin - CpE-1 Fall 2026

Builds a per-run static feature table from ME-2's 9/4/26 collection.
Robust (MAD-based) dropout rejection, per-cell medians, within-run spread.
"""
import glob, json, os, re
import numpy as np
import pandas as pd

MAD_K = 10.0
LOAD_MAP = {"L00": 0.0, "L01": 0.25, "L02": 0.5, "L03": 1.0}
POS_MAP = {"PL": 0.25, "PC": 0.50, "PR": 0.75}
FNAME_RE = re.compile(
    r"ME2_(?P<test>T\d+[a-z]?)_(?P<load>L\d\d)_+(?P<pos>P[LCR]|P00|F\d\d)_V(?P<vib>\d\d)_TEMP(?P<temp>\d\d)")

def robust_stats(x, k=MAD_K):
    x = np.asarray(x, dtype=float); x = x[np.isfinite(x)]
    med = np.median(x); mad = np.median(np.abs(x - med)); sigma = 1.4826 * mad
    keep = np.ones_like(x, dtype=bool) if sigma <= 0 else np.abs(x - med) <= k * sigma
    xs = x[keep]
    return {"median": float(np.median(xs)), "mean_raw": float(np.mean(x)),
            "mean_clean": float(np.mean(xs)),
            "std_clean": float(np.std(xs, ddof=1)) if xs.size > 1 else np.nan,
            "mad_sigma": float(sigma), "n_raw": int(x.size), "n_kept": int(xs.size),
            "n_dropped": int(x.size - xs.size)}

def parse_name(path):
    base = os.path.basename(path)
    m = FNAME_RE.search(base)
    if not m: return None
    g = m.groupdict(); pos = g["pos"]
    return {"test_id": g["test"], "load_code": g["load"], "load_kg": LOAD_MAP.get(g["load"], np.nan),
            "position_code": pos, "position_norm": POS_MAP.get(pos, np.nan),
            "vibration_pwm": int(g["vib"]), "temp_code": "TEMP" + g["temp"], "filename": base}

def build(cleaned_dir):
    rows = []
    for path in sorted(glob.glob(os.path.join(cleaned_dir, "*_clean.csv"))):
        meta = parse_name(path)
        if meta is None:
            print("SKIP (unparsed name):", os.path.basename(path)); continue
        d = pd.read_csv(path); rec = dict(meta)
        rec["duration_ms"] = float(d["time_s"].iloc[-1] - d["time_s"].iloc[0])
        rec["n_samples"] = int(len(d))
        motor = d["motor_state"].dropna().unique().tolist()
        rec["motor_state_values"] = "|".join(sorted(str(m) for m in motor))
        for side, col in (("left","loadcell_left_raw"),("right","loadcell_right_raw")):
            for k,v in robust_stats(d[col]).items(): rec[f"lc_{side}_{k}"] = v
        tot = d["loadcell_left_raw"].astype(float) + d["loadcell_right_raw"].astype(float)
        for k,v in robust_stats(tot).items(): rec[f"lc_total_{k}"] = v
        for side, col in (("left","temp_left_C"),("center","temp_center_C"),("right","temp_right_C")):
            rec[f"temp_{side}_mean_C"] = float(pd.to_numeric(d[col], errors="coerce").mean())
        acc = pd.to_numeric(d["accel_mag_g"], errors="coerce").dropna()
        rec["accel_mag_mean_g"] = float(acc.mean())
        rec["accel_mag_std_g"] = float(acc.std(ddof=1)) if acc.size > 1 else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)

if __name__ == "__main__":
    import sys
    src = sys.argv[1]; out = sys.argv[2]
    df = build(src).sort_values("test_id").reset_index(drop=True)
    df.to_csv(out, index=False)
    print("runs parsed:", len(df))
    static = df[df["vibration_pwm"] == 0]
    print("static runs:", len(static))
    print(static.groupby(["load_code","position_code"]).size().to_string())
    print("\nmotor_state vs vib:")
    print(df.groupby(["vibration_pwm","motor_state_values"]).size().to_string())
    print("\ndropouts:")
    print(df[["test_id","load_code","position_code","vibration_pwm","lc_total_n_raw","lc_total_n_dropped","lc_left_n_dropped","lc_right_n_dropped"]].to_string(index=False))
