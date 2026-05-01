# Data Integrity & Authentication -- Week 6

This document covers the HMAC-SHA256 message authentication layer added on top
of the TLS 1.2 transport encryption established in Week 5.

## 1. Threat Model

### Attacks addressed

| Threat                   | Description                                             | Mitigation                         |
|--------------------------|---------------------------------------------------------|------------------------------------|
| Payload tampering        | An attacker modifies sensor values in transit           | HMAC-SHA256 detects any change     |
| Device spoofing          | An unauthorized device publishes on the telemetry topic | HMAC key is required to sign       |
| Message forgery          | An attacker crafts a fake packet from scratch           | Cannot produce a valid HMAC tag    |
| Selective field mutation | Changing `device_id`, `seq_num`, or timestamps          | All fields are covered by the HMAC |

### Attacks NOT addressed (planned for later weeks)

| Threat               | Planned mitigation            | Week |
|----------------------|-------------------------------|------|
| Replay attacks       | Sequence + freshness checks   | 7 (done) |
| Timing manipulation  | Inter-arrival time monitoring | 8 (done) |
| Key extraction       | Secure firmware (CpE-1)       | 10   |
| Key rotation         | Provisioning protocol         | 10+  |
| Physical side-channel | Hardware countermeasures      | Out of scope |

### Trust assumptions

- The pre-shared key (PSK) is known only to the MCU and the host receiver.
- The TLS tunnel prevents passive eavesdropping of the HMAC key material.
- The broker is trusted to relay messages faithfully (it cannot forge valid
  HMACs because it does not possess the PSK).
- The MCU firmware has not been compromised (secure boot is handled by CpE-1).

## 2. Scheme Description

### Algorithm

**HMAC-SHA256** (RFC 2104 + FIPS 180-4)

- Hash function: SHA-256 (256-bit / 32-byte digest)
- Key size: 32 bytes (256-bit PSK)
- Tag size: 32 bytes, transmitted as 64 lowercase hex characters

### Canonical message format

To avoid JSON serialization ordering ambiguity, the HMAC is computed over a
deterministic pipe-delimited string:

```
<device_id>|<seq_num>|<timestamp_ms>|<temperature_c>|<humidity>
```

Example:

```
CC3220SF_NODE_01|42|10500|24.5|47.3
```

Float values use one decimal place (`%.1f` format) to ensure bit-exact
matching between the C `snprintf` on the MCU and Python `f"{val:.1f}"` on
the host.

### MCU-side computation (`hmac_auth.h`)

1. `buildTelemetryPayload()` formats the canonical string via `snprintf`
2. Calls `hmac_sha256(HMAC_KEY, 32, canonical, len, digest)`
3. Converts the 32-byte digest to a 64-char hex string via `bytes_to_hex()`
4. Embeds the hex string in the JSON `"hmac"` field

### Host-side verification (`host_receiver.py`)

1. Extracts all data fields and the `hmac` tag from the received JSON
2. Reconstructs the same canonical string with `f"{device_id}|{seq}|{ts}|{temp:.1f}|{hum:.1f}"`
3. Computes the expected HMAC using Python's `hmac.new(key, msg, sha256)`
4. Uses `hmac.compare_digest()` for timing-safe comparison
5. Logs `[HMAC OK]` or `[HMAC FAIL: <reason>]` per packet

## 3. Authenticated Packet Specification

### JSON format

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

### Field breakdown

| Field              | Type    | Size (JSON chars) | Notes                                             |
|--------------------|---------|--------------------|----------------------------------------------------|
| `schema_version`   | string  | 5                  | Semver tag (`"1.0.0"`). Excluded from HMAC.        |
| `device_id`        | string  | 16                 | Fixed identifier for this node                     |
| `seq_num`          | uint32  | 1--10              | Monotonically increasing counter                   |
| `timestamp_ms`     | uint32  | 1--10              | Monotonic board time in ms (FreeRTOS tick)         |
| `temperature_c`    | float   | 3--5               | One decimal place                                  |
| `humidity`         | float   | 3--5               | One decimal place                                  |
| `hmac`             | string  | 64                 | HMAC-SHA256 hex digest                             |

### Maximum payload size

Worst case: ~240 bytes (with version field).  The MCU buffer is 384 bytes,
providing ample headroom.

## 4. Device Identity Binding

The `device_id` field (`CC3220SF_NODE_01`) is included in the canonical HMAC
input.  This means:

- Changing the `device_id` in the JSON invalidates the HMAC.
- An attacker cannot re-attribute a packet to a different device without
  knowing the PSK.
- Each device in a multi-node deployment would use its own PSK, preventing
  cross-device forgery.

Currently, one device is deployed with one key.  Per-device key provisioning
is planned for Week 10 integration with CpE-1 secure firmware.

## 5. Key Management

### Current approach (research phase)

The 32-byte PSK is hardcoded in two locations:

| Location            | File                | Format               |
|---------------------|---------------------|----------------------|
| MCU firmware        | `hmac_auth.h`       | C `uint8_t` array    |
| Host receiver       | `host_receiver.py`  | Python `bytes` list  |
| Test suite          | `test_integrity.py` | Python `bytes` list  |

The key value is: `MySecureDigitalTwinKey2026!@#$%^` (ASCII representation
of the hex bytes).

### Future improvements (Week 10+)

- Secure key provisioning via CpE-1 firmware at boot time
- Per-device unique keys derived from a master secret
- Key rotation protocol with version tagging
- Hardware-backed key storage in the CC3220SF secure file system

## 6. Running the Tests

### Prerequisites

- Mosquitto broker running: `cd broker && ./broker.sh`
- Certificates generated: `cd broker/certs && ./generate_certs.sh`

### Execute the integrity test suite

```bash
cd broker
python3 test_integrity.py
```

### Expected output

```
=======================================================
  MQTT Data Integrity & Authentication Tests
=======================================================

--- Test 1: Valid Authenticated Packet ---
  [PASS] Valid Packet Accepted  -- HMAC verified successfully
  [PASS] Valid Packet Roundtrip  -- Survived broker relay

--- Test 2: Tampered Payload Detection ---
  [PASS] Tampered Payload Detected  -- HMAC mismatch (tamper caught)

--- Test 3: Unauthorized Source (Wrong Key) ---
  [PASS] Wrong Key Rejected  -- HMAC mismatch (unauthorized device caught)

--- Test 4: Missing HMAC Field ---
  [PASS] Missing HMAC Flagged  -- HMAC missing (unauthenticated packet caught)

=======================================================
  SUMMARY
=======================================================
  [PASS] Valid Packet Accepted
  [PASS] Valid Packet Roundtrip
  [PASS] Tampered Payload Detected
  [PASS] Wrong Key Rejected
  [PASS] Missing HMAC Flagged

  5/5 tests passed.
=======================================================
```

### Interpreting failures

- **Valid Packet Accepted FAIL**: The HMAC computation is inconsistent between
  the test script and the verification logic.  Check the canonical string
  format and PSK bytes.
- **Tampered Payload Detected FAIL**: The verification function is not
  comparing the HMAC correctly, or the canonical string is not including all
  fields.
- **Wrong Key Rejected FAIL**: Key comparison is broken -- both keys may
  accidentally be the same.
- **Missing HMAC Flagged FAIL**: The verification function is not checking for
  the presence of the `hmac` field.

## 7. Integration with Live MCU

When the MCU is running with the updated firmware:

1. Start the broker: `cd broker && ./broker.sh`
2. Start the receiver: `cd broker && python3 host_receiver.py`
3. Power on the MCU and press BTN-0 to start telemetry
4. Observe `[HMAC OK]` tags on every received packet
5. Press Ctrl+C to see the integrity summary

The CSV output (`raw_dataset_encrypted.csv`) now includes an `HMAC_Verified`
column (`True` / `False`) for every logged packet.

## 8. Limitations and Future Work

| Limitation                 | Impact                                         | Planned fix          |
|----------------------------|-------------------------------------------------|----------------------|
| Hardcoded PSK              | Key compromise requires re-flashing both sides  | Week 10 provisioning |
| No replay protection       | ~~An attacker can re-send valid old packets~~   | **Addressed in Week 7** |
| No timing validation       | ~~Delayed packets are not flagged~~             | **Addressed in Week 8** |
| Single device / single key | Cannot distinguish multiple MCU nodes           | Per-device keys      |
| Software SHA-256           | Slower than NWP hardware crypto                 | Acceptable at 4 Hz   |
| No key rotation            | Long-lived key increases exposure window        | Future enhancement   |

The HMAC layer provides the **integrity and authentication** foundation.
Replay detection (Week 7) and timing-anomaly monitoring (Week 8) will build
on top of this authenticated packet format.
