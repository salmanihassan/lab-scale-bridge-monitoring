# REPS DOT experimental visualization

Presentation date: **November 5, 2026**. This package characterizes existing
cleaned bridge measurements; it does not train or validate an AI digital twin.

## Run

MATLAB **R2022a or newer** is recommended (developed and executed in R2025b).
Base MATLAB generates time-domain figures, CSV indexes, LaTeX and the ZIP.
Base MATLAB also computes the periodic-Hann single-sided FFT. Signal Processing
Toolbox is not installed on this host, despite a recognized license entitlement;
optional Welch PSD and spectrograms are omitted.
Statistics and Machine Learning Toolbox is not required.

From `Twin Data` in MATLAB:

```matlab
addpath('REPS_DOT_Visualization');
generate_REPS_plots;
```

From another working directory, add this package's directory to the MATLAB
path. The default input root is the parent of `generate_REPS_plots.m`, independent
of the working directory. An explicit input root is optional:

```matlab
generate_REPS_plots('D:\path\to\Twin Data');
```

The output root is always the directory containing the pipeline. Re-running
overwrites only generated artifacts there; it never writes into `cleaned_data`
or the raw experimental folders. Existing user MATLAB figures are not closed.
Files from an earlier run that are no longer in the new manifest may remain on
disk; the manifest and LaTeX list the current outputs. The ZIP contains only
the report files specified by the pipeline.

## Inputs and provenance

- `cleaned_data/ME2_master_features.csv`: filename, batch and condition metadata.
- `cleaned_data/ME2_QC_report.csv`: existing QC status and notes, joined using
  **batch + original filename**, never test ID alone.
- `cleaned_data/model_dataset/manifest.csv`, when present: cross-check source
  provenance, condition metadata and explicit EXCLUDE flags. Mismatches stop
  execution rather than silently overriding information.
- Individual `*_clean.csv` files in retained acquisition folders.
- `cleaned_data/thermal_transient/THERMAL_01_PART1_clean.csv` and `PART2`.

**The actual model manifest is absent in the supplied dataset.** The pipeline
reports this and reconstructs unique cleaned paths from master metadata and
the filename rules in the existing `../clean_ME2_data.m`. No replacement is
written into the source dataset. Missing cleaned files cause an explicit error;
missing thermal metadata are reported. Raw Excel files are never substituted.

`9_4_26` and `911_data` are rejected as complete path components before loading
or calculating sensor metrics, including any manifest source pointing to them.
Their file bytes are hashed only to verify preservation; no excluded sensor
measurements, counts, features or conclusions enter the analysis. Source FAIL
rows and manifest EXCLUDE rows are omitted. CHECK rows are retained with their
warnings visible. Unknown metadata stay NaN/unknown, never zero.

Actual schema: `time_s`, `accel_x_g`, `accel_y_g`, `accel_z_g`,
`temp_left_C`, `temp_center_C`, `temp_right_C`, `loadcell_left_raw`,
`loadcell_right_raw`, and `motor_state`. The schema and existing cleaner establish
seconds, g, degrees Celsius and uncalibrated counts. Mass metadata are in kg;
raw load-cell signals are never labeled kg or N. Motor PWM is never treated as Hz.

## Outputs

- `figures/01_Experimental_Overview/` through `09_Comparative_Summary/`: 300 DPI PNGs.
- `plot_manifest.csv`: one row per generated figure, including source paths,
  experimental conditions, method, numerical findings and limitations.
- `run_metrics.csv`: recomputed recording metrics with original QC and metadata.
- `frequency_audit.csv`: interval endpoints, jitter, gaps and spectral decisions.
- `thermal_fits.csv`: segment-specific observational slopes and R-squared.
- `analysis_evidence.csv`: unrounded calculated inputs to every figure discussion.
- `figure_discussions.csv`: engineering analyses for all 33 figures.
- `T0236_fft_spectrum.csv`: all one-sided frequency/amplitude bins.
- `PROVENANCE_AUDIT.md`: missing-manifest and literal-T0 investigation.
- `report/main.tex`, `report/figures/`, and CSV indexes: independently portable report.
- `report/main.pdf`: compiled and visually checked report from this delivery.
- `REPS_DOT_Overleaf.zip`: upload-ready report bundle.
- `validation/`: source SHA-256 snapshots and hard validation results.
- `execution_log.txt`: MATLAB generation log (appends on repeat execution).

The Python `audit_inputs.py` is an optional development audit, not a dependency
of the MATLAB pipeline. Its `input_audit.csv` reports additional initial findings.

## Selection and metrics

The current retained inventory is 119 recordings: 26 static, 60 combined
load/vibration, 9 unloaded vibration, 16 frequency-command runs, 3 wind, 3 impact,
and 2 thermal segments. The last two are **one** session. The generator determines
these counts from metadata each time rather than assuming they are fixed.

Representatives are nearest the group median of the relevant metric, with a
deterministic filename tie break. Aggregates use all matching runs, not just
representatives. Static response uses per-run medians; condition markers are
means of these medians and error bars are sample SD across runs (only n >= 2).
Run counts appear in comparison legends. No confidence intervals assume that
individual time samples are independent repeats.

Dynamic acceleration is the residual of an OLS straight-line fit against the
**actual timestamps**, separately for each axis. RMS is sample weighted across
all finite residuals; peak is the largest absolute residual. Both logged motor
states are included to preserve the switching cycle. No additional smoothing,
outlier replacement or sensor gap filling is performed. Plotted traces break at
gaps > 1.5 median positive dt, retaining original vertices and extrema.

Comparisons retain batch, mass, position and PWM strata; command-frequency and
disturbance metadata distinguish experiment types. The September 18 unloaded
vibration runs are not combined with September 25 loaded runs to claim a load
effect. Same-batch 0.25 kg records provide vibration-off/on comparisons. The
September 25 0.25 kg static runs are separated from September 18 0.5/1 kg runs.

## Frequency-domain screening

The cleaner explicitly converted raw milliseconds to seconds, removed duplicate
times and retained a segment after resets. The current audit concerns what
remains in cleaned data; it cannot recover discarded timestamp history.

1. Audit positive increments, resets, duplicates and finite z acceleration.
2. Split at missing z samples, nonincreasing timestamps or dt > 1.5 median dt.
3. Select the longest continuous interval. Require >= 4 s, >= 256 samples,
   and maximum local increment deviation <= 20% of the local median.
4. If accepted, use base MATLAB to linearly interpolate
   to a median-dt grid **within those endpoints only**. No extrapolation,
   bridging rejected gaps, zero filling, or fabricated timestamps are allowed.
5. Linearly detrend; compute a periodic Hann FFT normalized by sum(window), with
   correct one-sided doubling for even/odd N. There is no zero padding.
   The periodic Hann window is evaluated directly from its cosine definition.
6. Search peaks only between 0.5 Hz and min(40 Hz, 0.4*fs). These are response
   peaks, not proven structural modes or a force-normalized frequency response.

Four seconds permits two cycles at 0.5 Hz and nominal full-window spacing <=
0.25 Hz. It is a conservative minimum, not proof of stationarity or anti-aliasing.
The supplied records have recurring ~0.09–0.10 s gaps amid ~0.01 s increments.
All but T0236 have longest uninterrupted finite-z segments below one second.
T0236 passes the unchanged timing criteria for 13.106–20.505 s (7.399 s).
Its 741 source samples yield 740 uniform samples at 100 Hz, with a 7.390 s
grid span and 0.135135 Hz FFT bin spacing. The largest searched bin is
1.351351 Hz at 0.001049255 g. This is a response feature, not a validated mode.
Figure F33 includes the recovered FFT; the other 90 candidates still fail timing.
`test_REPS_fft` checks even/odd amplitude scaling and rejects gapped intervals.
Acquisition blocking and packet loss cannot be distinguished from these files.

## Thermal handling

Both segments retain separate axes beginning at their first finite sensor row.
No exact shared clock is inferred from the approximate five-minute interruption.
Part 2 has an all-missing leading row at t=0 followed by a 539.826 s timestamp gap;
this is not silently used as the inter-segment interruption. Original durations
and valid sensor spans are both reported in the metrics.

Thermal trend and drift figures use occupied one-second medians. This is a
display/statistical aggregation only; no cleaned file is changed. Empty bins
are not filled. OLS trends use finite bin pairs, at least 20 bins and at least
1 degree C span of left temperature. Load cells and acceleration offsets are
fitted separately per segment. Time, temperature gradients, excitation and sensor
orientation confound these associations. Slopes are not validated compensation
coefficients, and the two segments do not form independent validation sessions.

## Known limitations

- All 119 retained recordings have existing CHECK status.
- Earlier cleaning already removed spikes and filled short internal gaps. There
  are no per-sample provenance flags, so original peaks cannot be reconstructed.
- Retained left load-cell values include 8,388,607-count plateaus and a roughly
  7.98e12-count thermal artifact. No new cleaning is performed. Medians reduce
  isolated-artifact influence; extreme counts and maxima remain disclosed.
- Sensor calibration, bridge geometry, orientation and uncertainty are not
  established by these files and are not fabricated in the report.
- Test ID T0253 is reused across batches and T0 is suspicious. Relative file
  paths are authoritative identities; identifiers are not silently corrected.
- Disturbance trigger times, wind speeds and forcing amplitudes are unknown.
  The impact envelopes align on a measured maximum, not an assumed trigger.
  No damping ratio or settling time is claimed.
- Temperature is not independently controlled in a balanced factorial design.

## Validation and Overleaf

The MATLAB run asserts unique filenames, existing plotted sources, absence of
excluded source paths, one report image per manifest row, and working relative
LaTeX image paths. SHA-256 hashes of **every file in cleaned_data**, including QC
and feature CSVs, must match before and after execution. The generated report
states the limited characterization scope and does not claim AI validation.

Upload `REPS_DOT_Overleaf.zip` as a new Overleaf project and choose `main.tex`
with pdfLaTeX. Alternatively upload the entire `report/` folder. All images use
`figures/<filename>.png`; no parent-directory file is required for compilation.
Standard LaTeX packages are used: graphicx, amsmath, siunitx, booktabs, float,
subcaption, geometry, hyperref, longtable, xurl, microtype, needspace, caption and fancyhdr.

Local regeneration produces LaTeX and images without needing a local TeX
installation. MATLAB does not compile the PDF; Overleaf or the Codex LaTeX
compiler performs that final step. Successful generation and separate PDF
compilation/visual review are recorded in the delivery notes.

For later prose/layout edits in `write_REPS_report.m`, run
`refresh_REPS_report` to rebuild LaTeX and the ZIP from the validated metrics and
figure manifest without recomputing plots. Recompile the PDF afterwards.

## Targeted revision

All 32 original figure IDs are retained: 21 PNGs are byte-identical to the
revision baseline and 11 are revised (F05, F06, F08, F09, F17, F18, F19, F21,
F23, F24, F30). Ten receive readability changes; F17 corrects the eligibility
result. F33 is the only new figure. No figure or retained recording is removed.

To repeat only these exports, preserving all other existing PNGs:

```matlab
generate_REPS_plots([], [5 6 8 9 17 18 19 21 23 24 30 33]);
```

Run metrics and numerical discussions are recalculated in either mode. Existing
plots are constructed for consistent manifest generation, but unselected PNGs
are not re-exported. `build_REPS_interpretations.m` calculates the quantitative
comparisons from retained samples and metrics; `improve_REPS_figure.m` contains
the localized formatting changes. `REPS_fft_interval.m` isolates the base FFT.
Original metric/manifest/code snapshots and figure hashes are retained under
`validation/revision_baseline/`. `validate_outputs.py` independently checks
source preservation, unchanged verified metrics, selective export hashes and
the actual FFT bins against NumPy.
