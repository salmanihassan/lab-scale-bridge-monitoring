# Changelog

All notable changes to the CC3220SF Digital Twin telemetry system are documented
in this file.  The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) for the packet
schema starting at v1.0.0.

---

## [2.0.0] -- 2026-05-02 (Week 11: AES-128-GCM AEAD Upgrade) -- BREAKING

Replaces the Week 10 AES-128-ECB + inner HMAC-SHA256 stack with a single
hardware-accelerated AES-128-GCM (AEAD) layer on the CC3220SF DTHE crypto
engine.  The GCM authentication tag now provides both ciphertext integrity
and identity / replay metadata authentication via Additional Authenticated
Data (AAD), making the inner HMAC-SHA256 redundant -- it has been removed.

### BREAKING
- Wire format changed from raw uppercase hex (PKCS7-padded ECB ciphertext)
  to a plaintext outer JSON envelope containing the ciphertext as a hex
  string field.  v1.x firmware and v1.x test harnesses no longer interop
  with the v2.0.0 broker; everything must be upgraded together.
- Inner JSON schema dropped `device_id`, `seq_num`, `timestamp_ms`, and
  `hmac` fields -- those moved to the outer envelope (and the `hmac` field
  is gone entirely; GCM tag replaces it).
- `host_receiver.py` `SUPPORTED_SCHEMA_VERSIONS` is now `{"2.0.0"}`; the
  `legacy` (no-version) acceptance path was removed because every wire
  packet must now be a v2.0.0 envelope.

### Added
- `gcm_encrypt_envelope()` in `mqtt_client_app.c` -- hardware AES-128-GCM
  via `CryptoCC32XX_encrypt(handle, CryptoCC32XX_AES_GCM, ...)` (DTHE
  block, mode `AES_CFG_MODE_GCM_HY0CALC`).
- `gcm_get_random()` -- pulls 12-byte GCM nonces from the CC3220SF NWP
  TRNG via `sl_NetUtilGet(SL_NETUTIL_TRUE_RANDOM, ...)`.  Same entropy
  source mbedtls uses for `mbedtls_hardware_poll()` inside the SDK.
- `decrypt_gcm_envelope()` in `host_receiver.py` -- uses `cryptography`
  package's `AESGCM` AEAD primitive.
- `gcm_wrap()` test helper in `test_integrity.py`, `test_schema.py`, and
  `test_freshness.py` so tests publish the same wire format the firmware
  produces.
- `docs/week11_gcm.md` -- wire-format spec, AAD canonical form, hardware
  API call shape, and TRNG sourcing rationale.
- `inner_parse_fail` counter on the broker for the "GCM-verified but
  inner JSON corrupt" case (firmware CORRUPT fault path under v2.0.0).
- New CSV freshness statuses: `GCM_FAIL`, `INNER_PARSE_FAIL`.

### Changed
- `SCHEMA_VERSION` bumped to `"2.0.0"`.
- MCU firmware (`mqtt_client_app.c`):
  - Removed `#include "hmac_auth.h"` and all HMAC-SHA256 compute calls
    from the publish path.  The `hmac_auth.h` header file is left in
    place so other modules that may use it still compile.
  - Removed `pkcs7_pad()` and `aes_encrypt_hex()` (ECB stack).
  - `buildTelemetryPayload()` now emits ONLY the inner JSON
    (`schema_version` + `telemetry`).  Identity / replay metadata is
    appended by `gcm_encrypt_envelope()` as the outer envelope and
    bound to the GCM tag as AAD.
  - CORRUPT fault now flips a byte of the inner JSON pre-encrypt
    (host sees `[JSON FAIL]` -- GCM tag valid, inner parse fails)
    instead of the legacy "HMAC mismatch" path.
- `host_receiver.py`:
  - Replaced `pycryptodome` (`Crypto.Cipher.AES`, `Crypto.Util.Padding`)
    with `cryptography` (`cryptography.hazmat.primitives.ciphers.aead.AESGCM`).
  - Removed `verify_hmac()` -- GCM tag now provides AEAD over both the
    encrypted telemetry and the AAD-bound metadata.
  - CSV column `HMAC_Verified` renamed to `GCM_Verified`.
  - Counters renamed: `hmac_pass` -> `gcm_pass`, `hmac_fail` -> `gcm_fail`.
  - Removed leading-character JSON-vs-hex discriminator: every payload
    is now a JSON envelope (with hex ciphertext nested as a string).

### Removed
- AES-128-ECB transport (insecure: deterministic, no integrity).
- PKCS7 padding helper.
- Inner `hmac` JSON field and the `verify_hmac()` host-side check.
- The `legacy` (missing `schema_version`) acceptance path on the host.

### Design decisions
- AAD canonical form mirrors the v1.x HMAC canonical's first three
  fields verbatim: `"<device_id>|<seq_num>|<timestamp_ms>"`.  Tampering
  with any of those plaintext outer-envelope fields fails GCM
  verification on the host -- the GCM tag thus binds identity and
  replay metadata even though they ride in plaintext for inspectability.
- Random per-publish nonces from the NWP TRNG keep the GCM nonce-reuse
  budget at `2^96` per key, well within safe limits for telemetry rates.
  No persistent counter state is required across reboots.
- Key length stays at 128-bit (matching the existing 16-byte `AES_KEY`).
  Promoting to AES-256 later is a one-line change to `keySize` plus a
  32-byte key array on both sides.
- The CC3220SF NWP TRNG (`SL_NETUTIL_TRUE_RANDOM`, option 3 in
  `netutil.h`) is the same entropy source `mbedtls_hardware_poll()` uses
  inside the SDK -- it requires the NWP to be powered up, so
  `gcm_encrypt_envelope()` is only called from inside the publish loop
  after `WIFI_IF_init()` / `SlNetConn_start()`.

---

## [1.1.0] -- 2026-05-01 (Week 10: Integration with Secure Firmware)

Merge of CpE-1 secure firmware (PWM motor driver, AES-128-ECB hardware
encryption, fault injection) into the CpE-2 MQTT/TLS client.  The
merged project at `Sp2026-CpE2/merged_project/` is the new working
baseline; the standalone `mqtt_client_CC3220SF_LAUNCHXL_freertos_ticlang/`
is preserved for reference only.

### Added
- `pwm_duty_us` and `pwm_period_us` as optional fields inside
  `telemetry`.  v1.1.0 widens the HMAC canonical string to bind these
  PWM fields (`...|temperature_c|humidity|pwm_duty_us|pwm_period_us`)
  so motor-command tampering is also caught by the integrity check.
  Both signer and verifier default missing PWM fields to 0, so v1.0.0
  packets without PWM continue to validate without coordination.
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
- PWM telemetry fields are **bound** to the HMAC canonical string in
  v1.1.0 so any tampering with motor commands is also caught by the
  integrity check.  Backward compat is preserved by 0-defaulting
  missing PWM fields on both signer and verifier.  This is an
  intentional deviation from the Week 9 rule that minor schema bumps
  preserve the canonical string verbatim -- the PWM bytes drive a
  physical actuator and warrant coverage.
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
