# Data Schema Freeze & Versioning -- Week 9

This document freezes the telemetry packet schema at **v1.0.0**, adds version
tags to every packet, and defines the rules for backward compatibility and
future schema evolution.  The frozen schema serves as the canonical reference
for the Spring-to-Fall handoff.

## 1. Problem Statement

Across Weeks 5--8 the packet format evolved incrementally (TLS, HMAC, freshness
fields, timing features).  Without a formal schema definition and version tag:

- It is impossible to tell which firmware produced a given packet.
- The Fall team cannot safely extend the format without risking silent
  incompatibility.
- Automated validation and data-pipeline tooling cannot assert correctness.

## 2. Frozen Schema v1.0.0

The formal JSON Schema is stored at
[`docs/schema_v1.0.0.json`](schema_v1.0.0.json).  It uses JSON Schema
draft-07 and specifies every field, type, constraint, and whether the field is
required.

### Packet format

```json
{
  "schema_version": "1.0.0",
  "device_id": "CC3220SF_NODE_01",
  "seq_num": 42,
  "timestamp_ms": 10500,
  "telemetry": {
    "temperature_c": 24.5,
    "humidity": 47.3
  },
  "hmac": "a1b2c3d4...64 hex characters..."
}
```

### Field specification

| Field              | Type    | Required | Notes                                              |
|--------------------|---------|----------|----------------------------------------------------|
| `schema_version`   | string  | yes      | Semver string, currently `"1.0.0"`                 |
| `device_id`        | string  | yes      | Uppercase alphanumeric + underscores               |
| `seq_num`          | uint32  | yes      | Monotonically increasing, resets on reboot          |
| `timestamp_ms`     | uint32  | yes      | FreeRTOS tick-based monotonic board time            |
| `temperature_c`    | number  | yes      | One decimal place (`%.1f`)                         |
| `humidity`         | number  | yes      | One decimal place (`%.1f`)                         |
| `hmac`             | string  | yes      | 64-char lowercase hex HMAC-SHA256 digest           |

### HMAC canonical string

```
<device_id>|<seq_num>|<timestamp_ms>|<temperature_c>|<humidity>
```

The `schema_version` field is **excluded** from the HMAC computation.  See
Section 4 for the rationale.

### Maximum payload size

Worst case with version field: ~240 bytes.  MCU buffer is 384 bytes.

## 3. Versioning Strategy

### Semantic versioning

The `schema_version` field uses [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR** (X.0.0): Breaking changes -- fields removed, types changed, HMAC
  canonical string altered.  Receivers MUST reject unknown major versions.
- **MINOR** (1.X.0): Backward-compatible additions -- new optional fields
  added.  Old receivers safely ignore unknown fields.
- **PATCH** (1.0.X): Non-structural fixes -- documentation corrections,
  clarifications.

### Version negotiation

The host receiver validates incoming packets as follows:

1. If `schema_version` is **absent**: treat as `legacy` (pre-v1.0.0).
   Accept with a `[LEGACY]` tag.  This ensures devices running older firmware
   continue to work during the transition.
2. If `schema_version` is **present and supported**: accept normally.
3. If `schema_version` is **present but unknown**: discard with
   `[SCHEMA UNKNOWN]`.  Log for investigation.

### Supported versions

Currently: `{"1.0.0"}`.  Adding a new version requires updating the
`SUPPORTED_SCHEMA_VERSIONS` set in `host_receiver.py`.

## 4. Design Decision: `schema_version` Excluded from HMAC

The version field is **not** included in the HMAC canonical string.  Rationale:

| Concern                        | Analysis                                           |
|--------------------------------|----------------------------------------------------|
| Backward compatibility         | Old firmware (no version) still produces valid HMACs|
| Security impact                | An attacker changing the version tag gains nothing  |
| Rollout simplicity             | MCU and host can be updated independently           |
| Future flexibility             | Version bumps do not require PSK rotation           |

The HMAC protects the data-carrying fields (`device_id`, `seq_num`,
`timestamp_ms`, `temperature_c`, `humidity`).  The version tag is pipeline
metadata, not integrity-critical data.

## 5. Backward Compatibility Rules

For the Fall team, the following rules ensure safe schema evolution:

1. **Never remove** a required field from v1.0.0.
2. **Never change** the type of an existing field.
3. **Never alter** the HMAC canonical string without incrementing the major
   version and coordinating a firmware + host update.
4. New optional fields may be added with a **minor** version bump.
5. The host receiver must always accept `legacy` packets until the fleet is
   fully upgraded.

## 6. Migration Guide (Fall Semester)

### Adding a new sensor (e.g., pressure)

1. Bump schema to `1.1.0`.
2. Add `"pressure_hpa"` as an optional field inside `telemetry`.
3. Update the JSON Schema (`docs/schema_v1.1.0.json`).
4. Update `SUPPORTED_SCHEMA_VERSIONS` to `{"1.0.0", "1.1.0"}`.
5. Do **not** add the new field to the HMAC canonical string yet (minor
   version = backward compatible).

### Changing the HMAC contract

1. Bump schema to `2.0.0`.
2. Create a new JSON Schema (`docs/schema_v2.0.0.json`).
3. Update both MCU firmware and host receiver simultaneously.
4. Remove support for `1.x.x` only after all devices are upgraded.

## 7. Test Suite

The schema validation test suite (`broker/test_schema.py`) covers:

| # | Scenario                    | Expected                              |
|---|-----------------------------|---------------------------------------|
| 1 | v1.0.0 packet               | Accepted, version recognized          |
| 2 | Legacy packet (no version)  | Accepted as legacy                    |
| 3 | Unknown version (`"2.0.0"`) | Rejected with SCHEMA_UNKNOWN          |
| 4 | Broker roundtrip            | v1.0.0 survives relay intact          |

### Running the tests

```bash
cd broker
python3 test_schema.py
```

## 8. Changelog

| Date       | Version | Change                                                    |
|------------|---------|-----------------------------------------------------------|
| 2026-04-24 | 1.0.0   | Initial frozen schema. Added `schema_version` field.      |
|            |         | MCU firmware: `SCHEMA_VERSION "1.0.0"` define added.      |
|            |         | Host receiver: version validation, legacy support, CSV.   |
|            |         | Formal JSON Schema: `docs/schema_v1.0.0.json`.           |
|            |         | Test suite: `broker/test_schema.py` (4 scenarios).        |

### Pre-v1.0.0 history

| Week | Change                                                              |
|------|---------------------------------------------------------------------|
| 5    | TLS 1.2 transport encryption. Basic JSON telemetry format.          |
| 6    | HMAC-SHA256 authentication. Added `hmac` field.                     |
| 7    | Freshness guarantees. `seq_num` and `timestamp_ms` made meaningful. |
| 8    | Timing-anomaly monitoring. No packet format changes.                |
| 9    | Schema frozen at v1.0.0. Added `schema_version` field.             |

## 9. Files Changed

| File                            | Change                                          |
|---------------------------------|-------------------------------------------------|
| `mqtt_client_app.c`            | Added `SCHEMA_VERSION` define, inserted field   |
| `broker/host_receiver.py`      | Version validation, legacy support, CSV column  |
| `broker/test_integrity.py`     | Added `schema_version` to packet helpers        |
| `broker/test_freshness.py`     | Added `schema_version` to packet helpers        |
| `broker/test_timing.py`        | Added `schema_version` to packet helpers        |
| `broker/test_schema.py`        | **New** -- 4 schema validation test scenarios   |
| `docs/schema_v1.0.0.json`      | **New** -- formal JSON Schema (draft-07)        |
| `docs/week9_schema.md`         | **New** -- this document                        |
| `docs/integrity_authentication.md` | Updated packet spec with `schema_version`   |
