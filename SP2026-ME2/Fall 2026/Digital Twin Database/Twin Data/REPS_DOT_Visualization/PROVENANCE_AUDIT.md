# Targeted provenance and FFT audit — October 26, 2026

The data root resolves from the plotting function's location, not MATLAB's
working directory. `cleaned_data/model_dataset/manifest.csv` and its containing
directory are absent. A recursive filename search through the available Fall
2026 project tree found only this visualization package's output manifests.
The existing `../clean_ME2_data.m` explicitly constructs `model_dataset` and
writes `manifest.csv`, plus train/validation/test manifests. The available files
do not establish why those outputs were omitted. No manifest was reconstructed
inside the input tree. The existing master feature table, QC report and unique
batch/filename join remain the fallback, with unknown conditions preserved.

The original September 25 file is literally
`9_25_loadvib/ME234_T0_L03_PC_V03_TEMP01.csv.xlsx`. Its feature/QC filename agrees.
The parser extracts the existing `_T0_` token; it did not truncate a longer ID.
The cleaned T0 recording has 3,347 rows, compared with 2,939 in T0235 at the
same condition. Its SHA-256 hash is unique among all 119 retained cleaned
recordings. Thus it is not a byte-identical duplicate, but this does not prove
independent acquisition. The unusual `ME234` prefix suggests a filename issue;
it cannot justify substituting T0234 or another invented ID. Acquisition logs
are needed. Full relative paths remain the unique recording identifiers.

MATLAB R2025b Update 2 recognizes a Signal Processing Toolbox license, but
`which` finds no installed `hann`, `pwelch`, or `spectrogram`. Base `fft` is
built in and `detrend` is installed. The original toolbox gate was therefore
too restrictive for FFT. It has been replaced with base MATLAB detrending,
the explicit periodic Hann definition and correctly normalized one-sided FFT.
Optional Welch PSD and spectrograms remain omitted.

All original timing thresholds remain unchanged: split on missing z,
nonincreasing timestamps or increments exceeding 1.5 times the median; require
at least four seconds, 256 samples, and maximum local jitter no greater than
20 percent. T0236 alone passes among 91 candidates. Its interval is
13.106–20.505 s, with 741 source samples, 740 uniform samples at 100 Hz and
0.135135 Hz bin spacing. The 1.351351 Hz largest searched response bin is not
a validated natural frequency. T0236 has no finite temperature readings.

All 249 files under `cleaned_data`, including source QC and feature tables,
match the original source-byte snapshot. The September 4 and September 11
batches remain excluded from all response analysis. The two thermal files
remain separate recording segments of one THERMAL_01 session.
