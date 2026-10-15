"""
test_static_twin.py
Self-checks for the static load twin. Run with: python3 test_static_twin.py
No external test framework required.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reps_twin import load_default                       # noqa: E402
from reps_twin.static_twin import TwinError              # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


def main(features_csv):
    twin = load_default()
    print(f"twin v{twin.version}\n")

    print("structure")
    check("positions fitted", twin.positions() == ["PC", "PL", "PR"], twin.positions())
    check("sigma ordering: twin above sensor floor",
          twin.sigma("twin") > twin.sigma("sensor"))
    check("unknown position rejected",
          _raises(lambda: twin.predict_total(0.25, "PX")))
    check("uncalibrated load rejected in strict mode",
          _raises(lambda: twin.predict_total(0.4, "PC")))
    check("uncalibrated load allowed when strict=False",
          np.isfinite(twin.predict_total(0.4, "PC", strict=False)))

    print("\nmonotonicity and physics")
    for p in twin.positions():
        check(f"{p}: total increases with load",
              twin.predict_total(0.0, p) < twin.predict_total(0.25, p)
              < twin.predict_total(0.5, p) < twin.predict_total(1.0, p))
    lf = {p: twin.predict_left_fraction(1.0, p) for p in ["PL", "PC", "PR"]}
    check("left fraction falls as the load moves right",
          lf["PL"] > lf["PC"] > lf["PR"], lf)
    check("zero-load prediction is position-independent to within 0.01 kg",
          max(abs(twin.predict_total(0.0, a) - twin.predict_total(0.0, b))
              / twin.sensitivity(a) for a in twin.positions() for b in twin.positions()) < 0.01)

    print("\ninverse consistency")
    for p in twin.positions():
        for L in [0.0, 0.25, 0.5, 1.0]:
            got = twin.infer_mass(twin.predict_total(L, p), p)
            check(f"{p} L={L}: infer_mass inverts predict_total",
                  abs(got - twin.true_mass(L)) < 1e-6, f"{got} vs {twin.true_mass(L)}")

    print("\nseverity banding")
    p = "PC"
    exp = twin.predict_total(0.5, p)
    s = twin.sensitivity(p)
    for mult, want in [(0.5, "S0"), (2.0, "S1"), (5.0, "S2"), (20.0, "S3")]:
        obs = exp + mult * twin.sigma("twin") * s
        check(f"{mult} sigma -> {want}", twin.severity(obs, 0.5, p) == want,
              twin.severity(obs, 0.5, p))
    check("sign symmetric",
          twin.severity(exp + 5 * twin.sigma("twin") * s, 0.5, p)
          == twin.severity(exp - 5 * twin.sigma("twin") * s, 0.5, p))

    print("\nenvelope guards")
    check("vibration rejected", twin.in_envelope(0.5, "PC", vibration_pwm=128)[0] is False)
    check("out-of-range temperature rejected",
          twin.in_envelope(0.5, "PC", temperature_c=45.0)[0] is False)
    check("nominal conditions accepted",
          twin.in_envelope(0.5, "PC", temperature_c=25.5)[0] is True)

    if features_csv and os.path.exists(features_csv):
        print("\nagainst the fitted data")
        d = pd.read_csv(features_csv)
        d = d[d["vibration_pwm"] == 0].copy()
        d["pos"] = d["position_code"].replace({"P00": "NONE"})
        res = []
        for _, r in d.iterrows():
            p = "PC" if r["pos"] == "NONE" else r["pos"]
            res.append(twin.residual_kg(r["lc_total_median"], r["load_kg"], p))
        res = np.array(res)
        check("in-sample residual sigma below the quoted twin sigma",
              np.std(res, ddof=1) <= twin.sigma("twin") * 1.05,
              f"{np.std(res, ddof=1):.5f} vs {twin.sigma('twin'):.5f}")
        check("no run exceeds 3x the twin sigma",
              np.max(np.abs(res)) < 3 * twin.sigma("twin"),
              f"max {np.max(np.abs(res)):.5f}")
        check("every clean run bands S0 or S1",
              all(twin.bands.band(x / twin.sigma("twin")) in ("S0", "S1") for x in res))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        return 1
    print("all checks passed")
    return 0


def _raises(fn):
    try:
        fn()
    except TwinError:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ""))
