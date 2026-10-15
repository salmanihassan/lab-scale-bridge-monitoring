# REPS digital twin, static load channel

Python behavioral reference for the two load cells under static load.
Fall 2026 CpE-1, Cyber-Attack Modeling and Dataset Generation.

The twin answers one question: given a commanded load and its position on the
span, what should each load cell read, and how far off is the observation. That
residual is what the attack severity scale is banded against, so the twin's
accuracy sets the smallest attack the dataset can meaningfully label.

## Layout

    reps_twin/
        static_twin.py                          the model and its API
        coefficients/twin_static_v1.0.0.json    fitted coefficients, versioned
    extract_static_features.py                  ME-2 cleaned runs to a feature table
    fit_static_twin.py                          fits the coefficients, selects the model
    plot_twin_diagnostics.py                    the three diagnostic figures
    test_static_twin.py                         self-checks, no test framework needed
    reband_week4_readonly.py                    scores Week 4 episodes, writes nothing back

## Use

    from reps_twin import load_default
    twin = load_default()

    twin.predict_total(0.25, "PC")                  expected total counts
    twin.predict_cells(0.25, "PC")                  per cell
    twin.predict_left_fraction(0.25, "PC")          expected load split
    twin.residual_kg(observed_total, 0.25, "PC")    observed minus expected, kg
    twin.severity(observed_total, 0.25, "PC")       S0 / S1 / S2 / S3
    twin.in_envelope(0.25, "PC", temperature_c=25)  is this inside what was fitted

`true_mass()` raises `TwinError` outside the four calibrated load levels rather
than interpolating a correction it cannot support. Pass `strict=False` to fall
back to the nominal label when that is what you want.

## Model

    true_mass_kg = mass_calibration[nominal_label]
    counts_cell  = offset[position][cell] + gain[position][cell] * true_mass_kg

Linear in true mass. Fitted on the 30 motor-off runs of ME-2's September 4
collection, cleaned data, robust per-run medians with MAD-based dropout
rejection.

## Why there is no nonlinear term

The Week 4 analysis found the per-position linear twin misspecified, residual
systematic in load, and recommended a quadratic or piecewise per-cell fit. The
data does not support that reading.

The deviation is a function of load level only. Across positions within one load
level it varies by 0.0032 kg. Across load levels it varies by 0.0164 kg. A
load-cell nonlinearity would track the load each cell carries, which differs by
a factor of three between PL and PR. It does not.

What it tracks instead is the mass label. The nominal 0.25 kg mass implies
0.265 to 0.280 kg on every one of its nine runs, across all three positions. The
0.5 kg and 1.0 kg masses come back sound. Correcting the labels, with the
response left linear, takes the held-out residual from 0.0168 kg to 0.0055 kg.
Fitting a quadratic to the nominal labels instead makes held-out error worse
than the linear fit (0.0176 kg), because it is fitting a labeling error with a
curve.

Model selection is by leave-one-run-out cross validation, held out at the run
level. Run-to-run error is roughly 15x within-run noise, so a sample-level
holdout would report a twin about 15x better than it is.

| Correction on the load labels | Extra params | In sample | Held out |
|---|---|---|---|
| None, nominal labels | 0 | 0.0148 | 0.0168 |
| Constant tare | 1 | 0.0107 | 0.0123 |
| Affine in load | 2 | 0.0106 | 0.0120 |
| Per level, selected | 2 | 0.0043 | 0.0055 |

kg, 1 sigma of the run-median residual.

## What is left in the residual

Held-out 0.0055 kg against a sensor noise floor of 0.0003 kg, so 18.7x. In
sample the 0.0043 kg splits about evenly into 0.0037 kg of systematic
load-by-position structure and 0.0029 kg of run-to-run repeatability. The second
is the floor reachable without new data. Closing the first needs more load
levels than four.

## Limits, read before trusting a number

- The mass calibration is inferred from the load cells, anchored at 0 kg and
  1.0 kg. It is provisional and is superseded the moment ME-2 weighs the
  physical masses.
- Four load levels only. The twin does not interpolate the mass correction.
- One thermal condition (TEMP01, roughly 25 to 26 C). No temperature term. The
  twin cannot be used to reason about thermal drift.
- Motor off on every fitted run. Vibration is not modeled. `in_envelope`
  rejects it.
- Residuals are correlated within a run. A run's own bias applies to all of its
  samples, so per-sample severity labels are not independent draws. Effective
  sample size is 30 runs, not 316,000 samples. This is the same class of hazard
  as the seq%10 leakage already flagged on the packet track.
- Zero-load run T0001 sits 0.0088 kg above the other two zero-load runs, likely
  tare drift before thermal settling. It is retained in the fit.

## Reproducing

    python3 extract_static_features.py <path to 9_4_26/cleaned_data> features.csv
    python3 fit_static_twin.py features.csv reps_twin/coefficients
    python3 test_static_twin.py features.csv
    python3 plot_twin_diagnostics.py features.csv <output dir>

Requires numpy, pandas, scipy, matplotlib.

## Asks that would move the number

1. ME-2 weighs the three physical masses on a scale. Replaces the inferred
   calibration with a measured one and settles whether the 0.25 kg label is
   wrong or a fixture mass is unaccounted for.
2. ME-2 records a zero-load tare at the start of every run. Lets the twin remove
   the run-specific offset, which is the larger half of what is left.
3. More load levels. Four points cannot separate response curvature from label
   error without the argument made above, and cannot support interpolation.
