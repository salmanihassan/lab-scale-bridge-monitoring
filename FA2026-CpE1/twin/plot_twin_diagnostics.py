"""
plot_twin_diagnostics.py
Diagnostic figures for the static load twin, v1.0.0.
    python3 plot_twin_diagnostics.py <static_run_features.csv> <out_dir>
"""
import json, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reps_twin import load_default

# categorical slots 1-3, validated all-pairs, light surface
C = {"PL": "#2a78d6", "PC": "#eb6834", "PR": "#1baf7a"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#dcdcd8", "#fcfcfb"
POSL = ["PL", "PC", "PR"]
LABEL = {"PL": "PL  load at 0.25 span", "PC": "PC  load at 0.50 span",
         "PR": "PR  load at 0.75 span"}


def style(ax):
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=9, length=0)


def head(fig, title, subtitle, y=0.975):
    fig.text(0.012, y, title, fontsize=13.5, color=INK, ha="left", va="top")
    fig.text(0.012, y - 0.062, subtitle, fontsize=9.5, color=INK2, ha="left", va="top")


def fig1(d, twin, out):
    """The finding, shown as a deviation so it is visible at all."""
    fig, ax = plt.subplots(figsize=(7.8, 4.8), facecolor=SURFACE)
    style(ax)
    ax.axhline(0, color=INK2, linewidth=1.4)
    ax.annotate("label is correct", (0.15, 0), textcoords="offset points",
                xytext=(2, 7), fontsize=9.5, color=INK2, ha="left")
    jit = {"PL": -0.018, "PC": 0.0, "PR": 0.018}
    for p in POSL:
        sub = d[d.position_code == p]
        dev = [twin.infer_mass(r.lc_total_median, p) - r.load_kg for _, r in sub.iterrows()]
        ax.scatter(sub.load_kg + jit[p], dev, s=70, color=C[p],
                   edgecolor=SURFACE, linewidth=1.8, zorder=3, label=LABEL[p])
    cal = twin._mass_cal
    for l in sorted(cal):
        if l == 0:
            continue
        ax.plot([l - 0.035, l + 0.035], [cal[l] - l] * 2, color=INK, linewidth=2.6, zorder=4)
    ax.annotate("nominal 0.25 kg mass is\nheavy by 0.035 kg (14%)", (0.25, cal[0.25] - 0.25),
                textcoords="offset points", xytext=(22, -4), fontsize=10, color=INK,
                va="center", ha="left")
    ax.annotate("0.5 kg and 1.0 kg labels are sound\nto within 0.005 kg", (0.62, 0.0135),
                textcoords="offset points", xytext=(0, 0), fontsize=10, color=INK2,
                va="center", ha="center")
    ax.set_xticks([0.25, 0.5, 1.0])
    ax.set_xlim(0.13, 1.12)
    ax.set_xlabel("Nominal load label recorded by ME-2 (kg)", color=INK2, fontsize=10)
    ax.set_ylabel("Mass implied by the load cells,\nminus the nominal label (kg)",
                  color=INK2, fontsize=10)
    ax.set_ylim(-0.006, 0.047)
    ax.legend(frameon=False, fontsize=9.5, loc="center right", labelcolor=INK2,
              bbox_to_anchor=(1.0, 0.56))
    head(fig, "The 0.25 kg mass reads 0.28 kg on all nine of its runs",
         "Deviation from the recorded label, every loaded static run of the\n"
         "2026-09-04 collection. The black bar is the twin v1 calibration.")
    fig.tight_layout(rect=(0, 0, 1, 0.86))
    fig.savefig(os.path.join(out, "w05_fig1_implied_mass_vs_label.png"), dpi=170,
                facecolor=SURFACE)
    plt.close(fig)


def fig2(d, twin, out):
    fig, axes = plt.subplots(1, 2, figsize=(9.8, 5.0), facecolor=SURFACE, sharey=True)
    lev = sorted(d.load_kg.unique())
    lin = {p: np.polyfit(d[(d.position_code == p) | (d.position_code == "P00")].load_kg,
                         d[(d.position_code == p) | (d.position_code == "P00")].lc_total_median, 1)
           for p in POSL}
    panels = [
        ("Per-position linear twin on the nominal labels",
         lambda r, p: (r.lc_total_median - np.polyval(lin[p], r.load_kg)) / lin[p][0]),
        ("Twin v1.0.0, same model plus the mass calibration",
         lambda r, p: twin.residual_kg(r.lc_total_median, r.load_kg, p)),
    ]
    handles = None
    for ax, (title, fn) in zip(axes, panels):
        style(ax)
        allres = []
        for p in POSL:
            sub = d[d.position_code == p]
            res = [fn(r, p) for _, r in sub.iterrows()]
            allres += res
            ax.scatter(sub.load_kg, res, s=62, color=C[p], edgecolor=SURFACE,
                       linewidth=1.8, zorder=3, label=LABEL[p])
        z = d[d.position_code == "P00"]
        zr = [fn(r, "PC") for _, r in z.iterrows()]
        allres += zr
        ax.scatter([0] * len(zr), zr, s=62, color=INK2, edgecolor=SURFACE,
                   linewidth=1.8, zorder=3, label="no load applied")
        s = float(np.std(allres, ddof=1))
        ax.axhspan(-s, s, color=INK, alpha=0.06, zorder=1)
        ax.axhline(0, color=INK2, linewidth=1.3, zorder=2)
        ax.set_title(title, color=INK, fontsize=11, pad=8, loc="left")
        ax.text(0.5, 0.035, f"1 sigma  {s:.4f} kg", transform=ax.transAxes,
                fontsize=12, color=INK, ha="center", va="bottom")
        ax.set_xlabel("Nominal load (kg)", color=INK2, fontsize=10)
        ax.set_xticks(lev)
        ax.set_xlim(-0.08, 1.08)
        handles = ax.get_legend_handles_labels()
    axes[0].set_ylabel("Observed minus twin expectation (kg)", color=INK2, fontsize=10)
    fig.legend(*handles, frameon=False, fontsize=9.5, ncol=4, loc="lower center",
               bbox_to_anchor=(0.5, -0.005), labelcolor=INK2)
    head(fig, "Correcting the mass labels removes two thirds of the twin error",
         "Shaded band is 1 sigma of the residual. Both panels use the same per-position "
         "linear response model.")
    fig.tight_layout(rect=(0, 0.07, 1, 0.85))
    fig.savefig(os.path.join(out, "w05_fig2_residual_before_after.png"), dpi=170,
                facecolor=SURFACE)
    plt.close(fig)


def fig3(coeffs, twin, out):
    ms = coeffs["model_selection"]
    order = ["nominal", "tare", "affine", "free"]
    name = {"nominal": "Nominal labels\nno correction",
            "tare": "Constant tare\n1 extra parameter",
            "affine": "Affine in load\n2 extra parameters",
            "free": "Per-level calibration\n2 extra parameters, SELECTED"}
    loo = [ms[k]["loo_sigma_kg"] for k in order]
    ins = [ms[k]["in_sample_sigma_kg"] for k in order]
    fig, ax = plt.subplots(figsize=(8.6, 4.8), facecolor=SURFACE)
    style(ax)
    y = np.arange(len(order))
    h = 0.22
    ax.barh(y - h / 2 - 0.015, loo, height=h, color="#2a78d6", zorder=3,
            label="Held out, leave one run out")
    ax.barh(y + h / 2 + 0.015, ins, height=h, color="#eb6834", zorder=3,
            label="In sample")
    for i, (a, b) in enumerate(zip(loo, ins)):
        ax.text(a + 0.0003, i - h / 2 - 0.015, f"{a:.4f}", va="center", fontsize=9.5, color=INK)
        ax.text(b + 0.0003, i + h / 2 + 0.015, f"{b:.4f}", va="center", fontsize=9.5, color=INK2)
    floor = twin.sigma("sensor")
    ax.axvline(floor, color="#1baf7a", linewidth=2.2, zorder=4)
    ax.annotate(f"sensor noise floor  {floor:.4f} kg",
                xy=(floor, 0.5), xycoords=("data", "axes fraction"),
                textcoords="offset points", xytext=(10, 0), fontsize=10,
                color="#0f7d57", va="center", ha="left", rotation=90)
    ax.set_yticks(y)
    ax.set_yticklabels([name[k] for k in order], fontsize=9.5, color=INK2)
    ax.invert_yaxis()
    ax.set_xlim(0, max(loo) * 1.14)
    ax.set_xlabel("Twin residual, 1 sigma (kg)", color=INK2, fontsize=10)
    ax.legend(frameon=False, fontsize=9.5, loc="lower right", labelcolor=INK2,
              bbox_to_anchor=(1.0, 0.02))
    head(fig, "A per-level mass calibration wins, and no nonlinear term was needed",
         "All four candidates share the same per-position linear response model and differ "
         "only in how the load labels are corrected.")
    fig.tight_layout(rect=(0, 0, 1, 0.85))
    fig.savefig(os.path.join(out, "w05_fig3_model_selection.png"), dpi=170,
                facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    feats, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    twin = load_default()
    coeffs = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "reps_twin/coefficients/twin_static_v1.0.0.json")))
    d = pd.read_csv(feats)
    d = d[d.vibration_pwm == 0].copy()
    fig1(d[d.load_kg > 0], twin, out)
    fig2(d, twin, out)
    fig3(coeffs, twin, out)
    print("wrote 3 figures to", out)
