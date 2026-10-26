# Delivery validation — October 26, 2026

The pipeline was executed successfully in MATLAB R2025b Update 2.

| Check | Result |
|---|---|
| Retained cleaned recordings | 119 |
| Generated 300 DPI figures | 32, all included in the report |
| Report | 43-page PDF; all 14 requested sections |
| Scrapped September 4/11 sources in analysis | 0 |
| Source preservation | All 249 files under `cleaned_data` have unchanged SHA-256 hashes |
| Independent numerical verification | NumPy recalculation agrees with MATLAB z RMS, absolute peaks, and both load-cell medians for all 119 recordings |
| Static repetition grouping | 26 recordings in 9 batch/mass/position groups |
| Figure provenance | All source files exist; condition descriptions are populated, including explicit unknown labels |
| Figure filenames | Unique |
| Report images | 32 valid relative references; copies are byte-identical to category exports |
| Overleaf ZIP | Current LaTeX and all referenced images verified against the report directory |
| Thermal handling | Two separately displayed segments of THERMAL_01; unknown load/PWM preserved |
| Spectral outputs | None generated; omissions audited individually |
| LaTeX | Successfully compiled with the desktop compiler and exported using its installed Tectonic engine |
| PDF layout | All 43 pages rendered with Poppler and visually reviewed; no clipped content, missing figures, overfull boxes or unresolved references in the final build |

The final report source was refreshed from the validated figure manifest after
layout edits. `refresh_REPS_report.m` reproduces that step without recalculating
sensor data. The full `generate_REPS_plots.m` execution uses the same report writer.

## Important limitations retained in the deliverable

- The supplied model manifest is absent. The pipeline uses the master metadata
  and batch/filename joins, documenting this fallback without changing sources.
- All retained source QC statuses are CHECK. No run was relabeled as passing QC.
- Of 91 vibration/disturbance spectral candidates, 90 have insufficient continuous
  intervals. T0236 passes timing with a 7.399 s interval, but the required Signal
  Processing Toolbox functions are not installed. Its spectrum is therefore
  skipped as well. The conditional spectral code was not executed on this host.
- The cleaned data retain 115 extreme load-cell entries in four recordings.
  Medians provide robust summaries; no extra cleaning or replacement is performed.
- Thermal slopes are observational fits and do not establish a compensation model.
- Report language describes experimental characterization, not a trained or
  validated AI digital twin.

Machine-readable evidence: `validation/validation.json`,
`validation/independent_validation.json`, source hash CSVs, `frequency_audit.csv`,
and the final PDF contact sheets under `validation/`.

The compiler emitted an environment-level fontconfig diagnostic, but completed
successfully; the final PDF fonts and page contents were verified by rendering.
