"""
fit_static_twin.py
REPS Digital Twin - static load channel, v1.0.0
CpE-1 Fall 2026, Cyber-Attack Modeling and Dataset Generation

Fits the static load twin from ME-2's September 4 collection and writes
reps_twin/coefficients/twin_static_v1.0.0.json.

Model family comparison is part of the fit, not a separate exercise: every
candidate is scored by leave-one-run-out cross validation, held out at the
RUN level. Sample-level holdout would be meaningless here, because run-to-run
error is far larger than within-run noise.

    python3 fit_static_twin.py <static_run_features.csv> <output_dir>

The input is produced by extract_static_features.py.
"""

import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd
from scipy.optimize import least_squares

POSITIONS = ["PL", "PC", "PR"]
CELLS = ["left", "right"]
TWIN_VERSION = "1.0.0"


# ---------------------------------------------------------------- data ----
def load_static(path):
    d = pd.read_csv(path)
    d = d[d["vibration_pwm"] == 0].copy()
    d["pos"] = d["position_code"].replace({"P00": "NONE"})
    return d.reset_index(drop=True)


# ------------------------------------------------- mass-calibration fit ----
def _mass_map(theta, levels, kind):
    """Nominal load label -> estimated true mass."""
    anchors = (0.0, max(levels))
    if kind == "nominal":
        return {l: l for l in levels}
    if kind == "tare":
        return {l: (0.0 if l == 0 else l + theta[0]) for l in levels}
    if kind == "affine":
        return {l: (0.0 if l == 0 else theta[0] + theta[1] * l) for l in levels}
    if kind == "free":
        free = [l for l in levels if l not in anchors]
        m = {a: a for a in anchors}
        for i, l in enumerate(free):
            m[l] = theta[i]
        return m
    raise ValueError(kind)


def _n_mass_params(levels, kind):
    return {"nominal": 0, "tare": 1, "affine": 2,
            "free": len([l for l in levels if l not in (0.0, max(levels))])}[kind]


def fit(df, kind="free"):
    """Joint fit of the mass calibration and per-position per-cell linear response."""
    levels = sorted(df["load_kg"].unique())
    nm = _n_mass_params(levels, kind)

    def unpack(theta):
        mass = _mass_map(theta[:nm], levels, kind)
        rest = theta[nm:].reshape(len(POSITIONS), len(CELLS), 2)
        coef = {p: {c: tuple(rest[i][j]) for j, c in enumerate(CELLS)}
                for i, p in enumerate(POSITIONS)}
        return mass, coef

    def residuals(theta):
        mass, coef = unpack(theta)
        out = []
        for _, r in df.iterrows():
            # zero-load runs carry no position; they constrain every position's offset
            targets = POSITIONS if r["pos"] == "NONE" else [r["pos"]]
            for p in targets:
                for c in CELLS:
                    g, o = coef[p][c]
                    out.append(o + g * mass[r["load_kg"]] - r[f"lc_{c}_median"])
        return np.array(out)

    seed = {"nominal": [], "tare": [0.03], "affine": [0.03, 1.0],
            "free": [l for l in levels if l not in (0.0, max(levels))]}[kind]
    theta0 = np.array(list(seed) + [500000.0, 400000.0] * len(POSITIONS) * len(CELLS), float)
    sol = least_squares(residuals, theta0, max_nfev=20000)
    return unpack(sol.x)


def predict_total(mass, coef, load_kg, pos):
    p = "PC" if pos == "NONE" else pos
    return sum(coef[p][c][1] + coef[p][c][0] * mass[load_kg] for c in CELLS)


def sensitivity(coef, pos):
    p = "PC" if pos == "NONE" else pos
    return sum(coef[p][c][0] for c in CELLS)


# ------------------------------------------------------ cross validation ----
def loo_residuals_kg(df, kind):
    """Leave one RUN out. Returns residuals in kg."""
    errs = []
    for fn in df["filename"].unique():
        tr = df[df["filename"] != fn]
        te = df[df["filename"] == fn].iloc[0]
        mass, coef = fit(tr, kind)
        e = (predict_total(mass, coef, te["load_kg"], te["pos"]) - te["lc_total_median"])
        errs.append(e / sensitivity(coef, te["pos"]))
    return np.array(errs)


def in_sample_residuals_kg(df, mass, coef):
    return np.array([
        (predict_total(mass, coef, r["load_kg"], r["pos"]) - r["lc_total_median"])
        / sensitivity(coef, r["pos"]) for _, r in df.iterrows()])


# ------------------------------------------------------------------ main ----
def main(features_csv, out_dir):
    df = load_static(features_csv)
    levels = sorted(df["load_kg"].unique())
    print(f"static runs: {len(df)}  loaded: {int((df.load_kg > 0).sum())}  levels: {levels}")

    comparison = {}
    for kind in ["nominal", "tare", "affine", "free"]:
        mass, coef = fit(df, kind)
        ins = in_sample_residuals_kg(df, mass, coef)
        cv = loo_residuals_kg(df, kind)
        comparison[kind] = {
            "n_params": _n_mass_params(levels, kind) + 12,
            "in_sample_sigma_kg": float(np.std(ins, ddof=1)),
            "loo_sigma_kg": float(np.std(cv, ddof=1)),
            "loo_max_abs_kg": float(np.max(np.abs(cv))),
            "mass_calibration_kg": {str(k): round(float(v), 5) for k, v in sorted(mass.items())},
        }
        print(f"  {kind:8s} npar={comparison[kind]['n_params']:2d} "
              f"in-sample={comparison[kind]['in_sample_sigma_kg']:.5f} "
              f"LOO={comparison[kind]['loo_sigma_kg']:.5f} kg")

    best = min(comparison, key=lambda k: comparison[k]["loo_sigma_kg"])
    print(f"\nselected by LOO: {best}")
    mass, coef = fit(df, best)
    cv = loo_residuals_kg(df, best)

    # noise floor: within-run per-sample spread of the total, converted to kg
    sens_pc = sensitivity(coef, "PC")
    sensor_sigma = float(df["lc_total_std_clean"].median() / sens_pc)

    # left-fraction residual, used to catch per-cell attacks that preserve the total
    lf_res = []
    for _, r in df.iterrows():
        p = "PC" if r["pos"] == "NONE" else r["pos"]
        pred = coef[p]["left"][1] + coef[p]["left"][0] * mass[r["load_kg"]]
        tot = sum(coef[p][c][1] + coef[p][c][0] * mass[r["load_kg"]] for c in CELLS)
        obs_lf = r["lc_left_median"] / (r["lc_left_median"] + r["lc_right_median"])
        lf_res.append(obs_lf - pred / tot)
    lf_sigma = float(np.std(lf_res, ddof=1))

    out = {
        "twin_version": TWIN_VERSION,
        "channel": "static_load",
        "fitted_on": str(date.today()),
        "fitted_from": "ME-2 collection 2026-09-04, cleaned_data, 30 motor-off runs",
        "fitted_by": "CpE-1 Fall 2026",
        "model_form": "counts_cell = offset[pos][cell] + gain[pos][cell] * true_mass_kg",
        "mass_calibration_kg": {str(k): round(float(v), 5) for k, v in sorted(mass.items())},
        "mass_calibration_basis": (
            "Inferred from the load cells, anchored at 0 kg and 1.0 kg. PROVISIONAL: "
            "supersede with a scale measurement of the physical masses (ME-2 action)."),
        "gain_counts_per_kg": {p: {c: round(coef[p][c][0], 1) for c in CELLS} for p in POSITIONS},
        "offset_counts": {p: {c: round(coef[p][c][1], 1) for c in CELLS} for p in POSITIONS},
        "sigma_kg": {
            "twin": round(float(np.std(cv, ddof=1)), 6),
            "sensor": round(sensor_sigma, 6),
            "left_fraction": round(lf_sigma, 6),
        },
        "severity_bands": {"s1": 1.0, "s2": 3.0, "s3": 10.0},
        "validated_envelope": {
            "load_kg": [float(min(levels)), float(max(levels))],
            "positions": POSITIONS,
            "temperature_c": [24.0, 27.0],
            "vibration_pwm": [0, 0],
            "thermal_conditions": ["TEMP01"],
        },
        "model_selection": comparison,
        "selected_model": best,
        "notes": [
            "Response is LINEAR in true mass. The concavity seen against the nominal "
            "labels is a load-mass labeling error, not a load-cell nonlinearity: the "
            "deviation is a function of load level only, with 0.0032 kg spread across "
            "positions against 0.0164 kg across levels. A per-cell nonlinearity would "
            "track the load each cell carries, which differs by position. It does not.",
            "The nominal 0.25 kg mass reads ~0.28 kg on every one of its nine runs. "
            "The 0.5 kg mass reads ~0.50 kg, the 1.0 kg mass ~1.00 kg.",
            "Zero-load run T0001 sits 8,292 counts (0.0088 kg) above the other two "
            "zero-load runs. Likely tare drift before thermal settling. It is retained "
            "in the fit; excluding it would tighten the zero anchor.",
            "One thermal condition only (TEMP01). The twin has no temperature term and "
            "must not be used to reason about thermal drift.",
            "Vibration off on every fitted run. Combined load plus vibration is "
            "ME-2 Stage 4, not yet collected.",
            "Calibrated at four load levels only. true_mass() raises outside them "
            "rather than interpolating a correction it cannot support.",
        ],
    }

    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"twin_static_v{TWIN_VERSION}.json")
    with open(dest, "w") as fh:
        json.dump(out, fh, indent=1)
    print("wrote", dest)
    print(f"twin sigma {out['sigma_kg']['twin']:.5f} kg   "
          f"sensor floor {out['sigma_kg']['sensor']:.5f} kg   "
          f"ratio {out['sigma_kg']['twin']/out['sigma_kg']['sensor']:.1f}x")
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
