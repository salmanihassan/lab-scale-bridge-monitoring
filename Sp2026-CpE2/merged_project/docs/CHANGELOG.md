# Changelog

All notable changes to the CC3220SF Digital Twin telemetry system are documented
in this file.  The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for the packet
schema starting at v1.0.0.

---

## [1.1.0] -- 2026-05-01 (Week 10: Integration with Secure Firmware)

Merge of CpE-1 secure firmware (PWM motor driver, AES-128-ECB hardware
encryption, fault injection) into the CpE-2 MQTT/TLS client.  The
merged project at `Sp2026-CpE2/merged_project/` is the new working
baseline; the standalone `mqtt_client_CC3220SF_LAUNCHXL_freertos_ticlang/`
is preserved for reference only.

### Added
- `pwm_duty_us` and `pwm_period_us` as optional fields inside
  `telemetry`.  HMAC canonical string is unchanged from v1.0.0 so
  v1.0.0 receivers continue to validate v1.1.0 packets.
- AES-128-ECB encryption of the JSON payload in firmware using the
  CC3220SF DTHE hardware block (`CryptoCC32XX_AES`).  Wire format is
  raw uppercase hex ciphertext published over MQTT/TLS to
  `cc32xx/telemetry`.  No decorative prefix -- the broker
  discriminates plaintext JSON (test harnesses, legacy v1.0.0) from
  ciphertext by leading character (`{` vs hex digit).
- Vibration motor PWM driver (`CONFIG_PWM_0`, period 10000 us, duties
  cycling 7000 / 8000 / 9000 / 10000 us at a 3 s step).
- Firmware fault injection: `FAULT_CORRUPT_EVERY 10`,
  `FAULT_DROP_EVERY 15`, `FAULT_DELAY_EVERY 20`.
- `docs/schema_v1.1.0.json` -- formal JSON Schema for v1.1.0.
- `docs/week10_integration.md` -- integration notes deliverable.
- `host_receiver.py`: AES-decrypt stage, `aes_fail` counter,
  `PWM_Duty_us` / `PWM_Period_us` columns in `raw_dataset_encrypted.csv`.
- `test_schema.py`: v1.1.0 acceptance test (3b) and AES-wrapped v1.1.0
  broker roundtrip test (5).
- `test_integrity.py`: AES wire-format round-trip test (5).
- `aes_wrap()` helpers in `test_integrity.py`, `test_freshness.py`,
  `test_schema.py` for parity with the new wire format.

### Changed
- MCU firmware (`mqtt_client_app.c`): `SCHEMA_VERSION "1.1.0"`, publish
  loop standardized at 3000 ms (replaces 250 ms 4 Hz loop), publish
  path is now JSON -> HMAC -> AES-128-ECB -> hex -> MQTT/TLS publish.
  UART2 is reserved for board console and `[FAULT]` debug prints
  only -- no telemetry on UART.
- SysConfig (`mqtt_client.syscfg`): added `PWM` module with
  `CONFIG_PWM_0` on `boosterpack.9` (Timer3, LED_YELLOW); removed
  `CONFIG_GPIO_LED_1` and `CONFIG_GPIO_LED_2` GPIO instances (their
  pins are now claimed by PWM_0).
- MQTT subscriptions: removed `cc32xx/ToggleLED1` / `LED2` / `LED3`
  topics.  A single `cc32xx/ToggleLED0` subscription remains.
- `host_receiver.py` `SUPPORTED_SCHEMA_VERSIONS` is now `{"1.0.0",
  "1.1.0"}` plus `legacy`.

### Design decisions
- AES-128-ECB is layered **inside** MQTT/TLS for defense-in-depth:
  the broker host process never sees plaintext telemetry even if the
  TLS session is compromised or replaced by a `mosquitto_pub`
  injection.  The CC3220SF DTHE hardware block makes the additional
  encrypt step essentially free.
- Wire-format prefix removed: every MQTT publish on `cc32xx/telemetry`
  is AES ciphertext, so the legacy `[AES] ` decorator from the
  CpE-1 dual-transport prototype is redundant.  The host receiver
  discriminates plaintext JSON (test harnesses, legacy v1.0.0) from
  ciphertext by leading character (`{` vs hex digit).
- Single transport: telemetry is published over MQTT/TLS only.  UART
  is reserved for the board console, `[FAULT]` diagnostics, and any
  future UART-protocol sensor reads -- no telemetry over UART.
- PWM telemetry fields are excluded from the HMAC canonical string so
  the v1.0.0 contract is preserved verbatim and minor schema bumps do
  not require firmware/host coordination.
- Fault injection is intentionally always-on for the Week 10 demo so
  the broker pipeline visibly catches each failure mode (CORRUPT ->
  HMAC fail, DROP -> seq gap, DELAY -> timing z-score spike).

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
