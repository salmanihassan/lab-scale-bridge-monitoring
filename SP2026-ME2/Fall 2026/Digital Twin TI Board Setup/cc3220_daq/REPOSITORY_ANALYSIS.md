# Existing repository analysis

Repository: `https://github.com/salmanihassan/lab-scale-bridge-monitoring`  
Commit retrieved: `843c142b02084629c1c2f7b0e54b64c3daff17f0`  
Tracked paths inspected through Git: 1,384

## Windows checkout caveat

The repository was cloned into `lab-scale-bridge-monitoring` as requested. Its
object database is complete, but Windows cannot materialize both `SP2026-*` and
`Sp2026-*` directory names in one case-insensitive worktree; some deeply nested
CCS metadata paths also exceed the legacy checkout path limit. Git long-path
support was enabled for the checkout. Analysis of every tracked path/name and
all relevant source/data files was performed directly from the retrieved Git
objects, so no experimental data was deleted or changed. Do not use the clone's
current worktree status as a source of project edits.

## Relevant contents

| Area | Findings relevant to this migration |
| --- | --- |
| `SP2026-ME2/Fall 2026/Digital Twin Database` | MATLAB cleaners/analysis, raw and cleaned experimental files, QC/features tables, plots, and bridge reports. The current data pipeline expects ten channels in the same order as the Arduino output and uses a nominal 100-Hz rate. |
| `clean_ME2_data.m` | Explicitly records the channel positions: time; X/Y/Z acceleration in g; left/center/right temperature; left/right raw load cell; motor command. It reconstructs invalid timing from `defaultFs_Hz = 100`, performs broad physical plausibility checks, and retains source data. |
| `analyze_ME2_dynamic_and_offsets.m` | Calculates no-load offsets, analyzes each accelerometer axis, identifies dynamic records by vibration PWM and commanded frequency, and uses FFT/dominant-frequency measures. This reinforces timestamp regularity as a migration requirement. |
| File naming | Examples follow `ME2_T####_L##_P.._V##_TEMP##` and optional `_F05_`, `_F10_`, `_F15_` frequency tokens. Existing code maps `V00/V01/V02/V03` to PWM `0/64/128/192`. |
| `Sp2026-CpE1` | Contains existing `CC3220SF_LAUNCHXL_freertos_ticlang` CCS projects, plus UART/MQTT/PWM demonstrations. This is the evidence for the CC3220SF target and the preferred TI Drivers + FreeRTOS + SysConfig stack. |
| Existing PWM SysConfig | Targets `/ti/boards/CC3220SF_LAUNCHXL`, `freertos`, and `simplelink_cc32xx_sdk@7.10.00.13`; uses `UART2` connected to `XDS110UART`, and demonstrates Timer3 PWM with BoosterPack 9/10 candidates. |
| Existing toolchain declaration | The project metadata declares **CCS 12.8.0**, **TIClang 3.2.1 LTS**, Cortex-M4, little-endian, and XDS110. These are the recommended reproducible build settings. |
| `Sp2026-CpE2` | Secure MQTT/timing-monitoring prototype. It is not reused in the initial wired acquisition application, which avoids coupling the 100-Hz measurement path to networking. |

## Architecture selected

The new `cc3220_daq` project is a deliberately isolated acquisition layer. It
keeps the bridge processing CSV-compatible first, while leaving a clean point
for a later queue/buffered network publisher. The initial 100-Hz timing path
does not perform Wi-Fi, MQTT, file-system, or blocking DS18B20 conversion work.

No existing repository file has been modified.
