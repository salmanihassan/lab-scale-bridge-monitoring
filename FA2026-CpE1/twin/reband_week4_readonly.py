"""Read-only: what the Week 4 physical episodes would band as under twin v1.0.0.
Week 4 files are NOT modified."""
import glob, json, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.join(os.environ["HOME"],
    "mnt/dot-lab/lab-scale-bridge-monitoring/FA2026-CpE1/twin"))
from reps_twin import load_default

twin = load_default()
SIG_T = twin.sigma("twin")
rows = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "*_phys.csv"))):
    d = pd.read_csv(f)
    pos = d["position_code"].replace({"P00": "PC"})
    exp = np.array([twin.predict_total(l, p) for l, p in zip(d["applied_load_kg"], pos)])
    sens = np.array([twin.sensitivity(p) for p in pos])
    res_kg = (d["lc_total_tx"].values - exp) / sens
    band = [twin.bands.band(x / SIG_T) for x in res_kg]
    old_sensor = d["severity"].value_counts().to_dict()
    old_lin = d["severity_twin_linear"].value_counts().to_dict()
    new = pd.Series(band).value_counts().to_dict()
    rows.append({
        "episode": os.path.basename(f).replace("_phys.csv", ""),
        "attack_code": d["attack_code"].iloc[0],
        "target_severity": d["episode_id"].iloc[0].split("-")[4] if False else "",
        "deviation_abs_kg": float(pd.to_numeric(d["deviation_abs"], errors="coerce").abs().max()),
        "sev_sensor_ref": json.dumps({k: int(v) for k, v in sorted(old_sensor.items())}),
        "sev_twin_linear": json.dumps({k: int(v) for k, v in sorted(old_lin.items())}),
        "sev_twin_v1": json.dumps({k: int(v) for k, v in sorted(new.items())}),
        "mean_abs_residual_kg_v1": float(np.mean(np.abs(res_kg))),
        "detectable_S2plus_pct_v1": float(100 * np.mean([b in ("S2", "S3") for b in band])),
        "detectable_S2plus_pct_linear": float(
            100 * (d["severity_twin_linear"].isin(["S2", "S3"]).mean())),
    })
t = pd.DataFrame(rows)
t.to_csv(sys.argv[2], index=False)
pd.set_option("display.width", 250)
print(t[["episode", "attack_code", "deviation_abs_kg", "sev_twin_linear",
         "sev_twin_v1", "detectable_S2plus_pct_linear", "detectable_S2plus_pct_v1"]].to_string(index=False))
print("\ntwin v1 sigma %.5f kg vs linear twin sigma 0.01440 kg (%.1fx tighter)"
      % (SIG_T, 0.0144 / SIG_T))
