# Changelog

All notable changes to the CC3220SF Digital Twin telemetry system are documented
in this file.  The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for the packet
schema starting at v1.0.0.

---

## [1.0.0] -- 2026-04-24 (Week 9: Schema Freeze)

### Added
- `schema_version` field (`"1.0.0"`) to every telemetry packet.
- Formal JSON Schema specification: `docs/schema_v1.0.0.json` (draft-07).
- Host receiver validates `schema_version`; accepts `legacy` (missing) and
  supported versions, rejects unknown versions.
- `Schema_Version` column in `raw_dataset_encrypted.csv`.
- `broker/test_schema.py` -- 4 schema-validation test scenarios.
- `docs/week9_schema.md` -- frozen spec, versioning rationale, backward
  compatibility rules, and Fall migration guide.

### Changed
- MCU firmware (`mqtt_client_app.c`): `buildTelemetryPayload()` now emits
  `schema_version` as the first JSON field.
- `docs/integrity_authentication.md`: packet specification updated to include
  `schema_version`; max payload size updated to ~240 bytes.
- All test helpers (`test_integrity.py`, `test_freshness.py`, `test_timing.py`)
  now include `schema_version` in generated packets.

### Design decisions
- `schema_version` is **excluded** from the HMAC canonical string so that old
  firmware remains compatible and version bumps do not require key rotation.

---

## [Pre-1.0.0] -- Weeks 5--8 (Spring 2026)

### Week 8 -- Timing-Anomaly Monitoring (2026-04-17)
- Added `broker/timing_monitor.py`: rolling-window z-score anomaly detection.
- Host receiver exports per-packet timing features to `timing_features.csv`.
- `[TIMING ALERT]` printed when |z-score| > 3.0.
- Ctrl+C summary includes Timing Analysis section.
- Added `broker/test_timing.py` (6 test scenarios).
- Added `docs/week8_timing.md`.

### Week 7 -- Timestamping & Freshness Guarantees
- MCU `timestamp_ms` switched from synthetic counter to real FreeRTOS tick
  (`xTaskGetTickCount()`).
- Host receiver implements replay, duplicate, stale, reboot, and gap detection.
- `Freshness_Status` and `Host_Delta_ms` columns added to CSV.
- Added `broker/test_freshness.py` (6 test scenarios).
- Added `docs/week7_freshness.md`.

### Week 6 -- Data Integrity & Authentication
- HMAC-SHA256 message authentication (RFC 2104 + FIPS 180-4).
- `hmac` field added to JSON packet; canonical pipe-delimited string format.
- 32-byte pre-shared key hardcoded on MCU (`hmac_auth.h`) and host.
- Host receiver verifies HMAC with timing-safe comparison.
- Added `broker/test_integrity.py` (5 test scenarios).
- Added `docs/integrity_authentication.md` and `docs/week6_report.md`.

### Week 5 -- TLS Transport Encryption
- Mosquitto broker configured with TLS 1.2 on port 8883.
- Self-signed CA and server certificates (`broker/certs/generate_certs.sh`).
- MCU connects over TLS using `SLNETSOCK_SEC_METHOD_TLSV1_2`.
- Basic JSON telemetry format: `device_id`, `seq_num`, `timestamp_ms`,
  `telemetry.temperature_c`, `telemetry.humidity`.
- Added `docs/crypto_configuration.md`.
