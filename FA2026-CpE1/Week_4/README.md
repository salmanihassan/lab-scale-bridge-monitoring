# Fall 2026 CpE-1 Week 4: Static Sensor Spoofing Datasets

Task order: implement offset and scaling attacks on sensor data, inject falsified calibration values, observe deviations from twin expectations. Deliverable: static spoofing datasets.

Taxonomy codes covered: A1.1 constant_offset, A1.2 scale_factor, A1.3 falsified_calibration. Taxonomy version 1.0.0. Labels per labels_schema_v1.0.0. Injection point IP-D (post-hoc on recorded data) for every episode.

## Layout

```
packet/        15 episodes on the authenticated packet path (temperature_c, humidity)
physical/      10 attack episodes plus 1 clean reference on ME-2 load-cell samples (load_cell_kg)
cpe2_format/   1 flat CSV in the column layout CpE-2 requested (packet track only)
w04_manifest.json   every episode, parameters, record counts, severity histograms, SHA-256, twin fit
```

Each episode is a CSV plus a JSON sidecar of the same basename carrying the episode_metadata block. Filenames follow `w04_<code>_<channel>_<severity>_r<run>[_phys].csv`.

## Packet track

Carrier is the Week 3 clean set (680 verified packets). A1.1 and A1.2 use the 428 packets of session S20260501-02 only, so they do not cross a reboot. A1.3 uses all 680 packets across all four sessions, so the falsified constant persists across reboots, which is what distinguishes A1.3 from A1.1 and A1.2 in the taxonomy.

Identical-carrier design: every episode reuses the same source packets (traceable through `source_packet_id`). The only difference between an attacked record and its clean twin is the value of `target_channel`. A detector that separates them has learned the manipulation and nothing else.

For every record the HMAC-SHA256 tag and the AES-128-ECB ciphertext were recomputed with the verified keys, and every record was decrypted and verified against a re-implementation of `host_receiver.py`. `receiver_detection_result` is ACCEPTED on all 7,176 attack records. This is the IP-F attacker capability being modelled: the packet is cryptographically perfect.

Magnitudes are set against the per-sample sigma from the Week 3 baseline: temperature 0.1 C (the sensor quantization step), humidity 1.5 (synthetic baseline dispersion, no physical referent). S1 is 1 to 2 sigma, S2 is 2 to 5, S3 is 5 and above. Because the transmitted temperature is quantized to 0.1, S1 is exactly one step and parameters were chosen so every record rounds into its target band.

| Code | Channel | S1 | S2 | S3 |
| --- | --- | --- | --- | --- |
| A1.1 | temperature_c | +0.1 | -0.3 | +0.8 |
| A1.1 | humidity | +2.0 | -5.0 | +12.0 |
| A1.2 | temperature_c | x1.004 | x0.988 | x1.032 |
| A1.2 | humidity | x1.045 | x0.90 | x1.25 |
| A1.3 | temperature_c | gain 1.002, offset 0.05 | gain 1.008, offset 0.10 | gain 1.02, offset 0.30 |

Limitation carried in every sidecar: the carrier sensor values are the firmware `rand()` stub. Separating these records from clean ones demonstrates detection of a departure from a known pseudo-random stream, not physical implausibility.

## Physical track

Carrier is ME-2's September 4 static-load runs (30 runs: 3 at zero load, 27 in the 3 load by 3 position matrix), cleaned as follows: drop the first 5 s of settling, drop any sample more than 10 percent from the run median on either cell (sensor dropouts), decimate 100 Hz to 10 Hz. 10,578 samples per episode.

A per-position linear twin was fitted on run medians: `total_counts = a_pos + b_pos * load_kg`. Fitted sensitivities are 1,034,917 (left), 922,952 (center) and 890,001 (right) counts per kg, which confirms the two cells have different gains. Every record carries `twin_expected_total`, `twin_residual_counts`, `twin_residual_kg` and `twin_residual_sigma`, plus `left_fraction_expected` and `left_fraction_residual` for the position split. This is the "observe deviations from twin expectations" task line, delivered per record.

Attacks act on the raw counts before conversion to kg:

| Code | Variant | S1 | S2 | S3 |
| --- | --- | --- | --- | --- |
| A1.1 | offset on total, split equally across cells | +0.003 kg | -0.007 kg | +0.020 kg |
| A1.2 | multiplier on load above zero | x1.003 | x0.993 | x1.02 |
| A1.3 | LC_ZERO_OFFSET_COUNTS falsified | +0.003 kg | -0.007 kg | +0.020 kg |
| A1.3 | LC_LEFT_GAIN falsified to 0.98 (disguise off-center load) | | | one episode |

A1.2 severity depends on applied load by construction. At zero load the deviation is zero (S0), which is the zero-input invariance the taxonomy describes. Per-record `severity` is authoritative. Filename severity is the band reached at 1.0 kg.

### Two severity columns

`severity` is banded against the sensor-limited sigma of 0.002 kg. `severity_twin_linear` is banded against the empirical clean residual of the provisional linear twin, 0.0144 kg.

The gap between those two numbers is the main finding of this week. Within-run residual (sensor noise) is 0.0005 kg. Between-run residual (model error) is 0.0144 kg, and it is systematic in applied load: +0.018 to +0.028 kg at 0.25 kg, -0.014 kg at 0 kg, near zero at 1.0 kg. The load-cell response is concave and a linear twin cannot represent it. Consequence: against the current twin every attack in this package is S0 or S1, including the +0.020 kg offset that sits 10 sigma above sensor noise. A quadratic or piecewise twin would close most of that gap and is recommended to ME-1 and ME-2.

## CpE-2 flat format

`cpe2_format/w04_static_spoofing_cpe2_format.csv` has 7,856 rows: 680 NORMAL (the Week 3 clean set) plus 7,176 SENSOR_OFFSET (all 15 packet-track episodes). Columns are exactly as requested: packet_id, seq_num, timestamp_ms, attack_type, attack_parameter, encrypted_hex, decrypted, hmac, detection_result, notes. A1.1, A1.2 and A1.3 all map to SENSOR_OFFSET. The CpE-1 code, channel, per-record severity, parameters and episode id are in `notes`. `attack_parameter` is the offset (A1.1), the multiplier (A1.2) or the falsified offset component (A1.3). Every row passes decrypt and HMAC verification.

## Verification performed

Independent pass, separate process from the generator: every packet-track record decrypts and passes HMAC (7,176 of 7,176); every attacked record differs from its clean source only in the target channel; `deviation_abs` equals transmitted minus ground truth on all 112,956 attack records; `severity` and `severity_twin_linear` recompute correctly on all of them; zero-input invariance holds on every A1.2 record at zero load; clean physical records conserve counts exactly; all nine required label fields and all required sidecar fields are present; every sidecar SHA-256 matches its CSV.

Generator: `build_week4.py` (session scratch, reuses the Week 3 crypto helpers).
