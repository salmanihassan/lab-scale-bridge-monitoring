# Week 6 Report: Data Integrity & Authentication

**Project:** IoT Digital Twin — Secure Telemetry Pipeline  
**Date:** April 17, 2026  
**Author:** Jeff Allo  

---

## 1. Objective

The goal for Week 6 was to add an application-layer data integrity and authentication mechanism on top of the TLS 1.2 transport encryption established in Week 5. Specifically:

- Add message authentication (MAC/signature) to every telemetry packet
- Bind packets to the originating device identity
- Simulate payload modification and verify detection

## 2. Approach

### 2.1 Algorithm Selection

**HMAC-SHA256** was chosen as the message authentication code, following RFC 2104 (HMAC construction) and FIPS 180-4 (SHA-256 hash). This provides:

- **256-bit authentication tags** — computationally infeasible to forge
- **Keyed construction** — only parties possessing the pre-shared key (PSK) can generate or verify tags
- **Deterministic output** — identical inputs always produce identical tags, enabling exact verification across C and Python implementations

A 32-byte (256-bit) pre-shared key is used, providing a security level equivalent to the hash output size.

### 2.2 Why HMAC on Top of TLS?

TLS 1.2 already provides transport-level integrity and encryption. The application-layer HMAC adds defense-in-depth:

| Layer | Protection | Threat Covered |
|-------|-----------|----------------|
| TLS 1.2 (Week 5) | Encrypted channel between MCU and broker | Eavesdropping, man-in-the-middle |
| HMAC-SHA256 (Week 6) | Per-packet authentication tag | Compromised broker, injection at application layer, device spoofing |

The broker is a trusted relay but does not possess the HMAC key, so it cannot forge packets. If the broker were compromised, the HMAC layer would still detect injected or modified messages.

## 3. Implementation

### 3.1 Authenticated Packet Format

Each telemetry packet is a JSON object containing sensor data plus a 64-character hex HMAC tag:

```json
{
  "device_id": "CC3220SF_NODE_01",
  "seq_num": 42,
  "timestamp_ms": 10500,
  "telemetry": {
    "temperature_c": 24.5,
    "humidity": 47.3
  },
  "hmac": "a1b2c3d4e5f6...64 hex characters..."
}
```

| Field | Type | Purpose |
|-------|------|---------|
| `device_id` | string | Fixed node identifier — included in HMAC input for identity binding |
| `seq_num` | uint32 | Monotonically increasing counter |
| `timestamp_ms` | uint32 | Board-side timestamp in milliseconds |
| `temperature_c` | float | DHT11 temperature reading (one decimal place) |
| `humidity` | float | DHT11 humidity reading (one decimal place) |
| `hmac` | string | HMAC-SHA256 digest over the canonical representation of all data fields |

Maximum payload size is approximately 220 bytes; the MCU transmit buffer is 384 bytes.

### 3.2 Canonical Message Format

To avoid ambiguity from JSON key ordering or whitespace differences, the HMAC is computed over a deterministic pipe-delimited string:

```
<device_id>|<seq_num>|<timestamp_ms>|<temperature_c>|<humidity>
```

For example:

```
CC3220SF_NODE_01|42|10500|24.5|47.3
```

Float values use a fixed one-decimal-place format (`%.1f` in C, `:.1f` in Python) to guarantee bit-exact matching between platforms.

### 3.3 MCU Firmware (`hmac_auth.h` + `mqtt_client_app.c`)

A header-only HMAC-SHA256 implementation was written in C for the CC3220SF. It contains:

1. **SHA-256 core** — a complete FIPS 180-4 implementation (init, update, final, transform)
2. **HMAC wrapper** — RFC 2104 construction using inner/outer padding
3. **Hex encoder** — converts the 32-byte binary digest to a 64-character hex string

The telemetry publish path in `mqtt_client_app.c` calls:

```c
// 1. Build the canonical string
snprintf(canonical, sizeof(canonical),
    "CC3220SF_NODE_01|%lu|%lu|%.1f|%.1f",
    g_seq_num, g_timestamp_ms,
    sensorData->temperature_c, sensorData->humidity);

// 2. Compute HMAC-SHA256
hmac_sha256(HMAC_KEY, sizeof(HMAC_KEY),
            (const uint8_t *)canonical, strlen(canonical),
            digest);

// 3. Convert to hex and embed in JSON
bytes_to_hex(digest, SHA256_DIGEST_SIZE, hmac_hex);
```

### 3.4 Host Receiver (`host_receiver.py`)

The Python host receiver verifies every incoming packet:

1. Extracts all data fields and the `hmac` tag from the received JSON
2. Reconstructs the canonical string using the same format
3. Computes the expected HMAC using Python's `hmac.new(key, msg, sha256)`
4. Performs a **timing-safe comparison** via `hmac.compare_digest()` to prevent side-channel leakage
5. Logs `[HMAC OK]` or `[HMAC FAIL: <reason>]` per packet

The CSV dataset (`raw_dataset_encrypted.csv`) now includes an `HMAC_Verified` column for every logged packet.

### 3.5 Device Identity Binding

The `device_id` field (`CC3220SF_NODE_01`) is included in the canonical HMAC input. This ensures:

- Changing the `device_id` in the JSON invalidates the HMAC
- An attacker cannot re-attribute a packet to a different device without possessing the PSK
- In a multi-node deployment, each device would use its own unique PSK, preventing cross-device forgery

## 4. Threat Model

### 4.1 Attacks Addressed

| Threat | Description | Mitigation |
|--------|-------------|------------|
| Payload tampering | Attacker modifies sensor values in transit | HMAC-SHA256 detects any change to covered fields |
| Device spoofing | Unauthorized device publishes on the telemetry topic | HMAC key is required to produce a valid signature |
| Message forgery | Attacker crafts a fake packet from scratch | Cannot produce a valid HMAC tag without the PSK |
| Selective field mutation | Changing `device_id`, `seq_num`, or timestamps | All fields are included in the HMAC canonical input |

### 4.2 Attacks Not Addressed (Planned for Future Weeks)

| Threat | Planned Mitigation | Week |
|--------|--------------------|------|
| Replay attacks | Sequence number + freshness window checks | 7 |
| Timing manipulation | Inter-arrival time anomaly monitoring | 8 |
| Key extraction from firmware | Secure key provisioning via CC3220SF secure file system | 10 |
| Key rotation | Versioned key provisioning protocol | 10+ |

### 4.3 Trust Assumptions

- The PSK is known only to the MCU firmware and the host receiver
- The TLS tunnel prevents passive eavesdropping of key material or HMAC tags
- The broker faithfully relays messages but cannot forge valid HMACs (it does not possess the PSK)
- The MCU firmware has not been compromised (secure boot is handled by the CpE-1 collaborator)

## 5. Testing & Verification

### 5.1 Automated Test Suite (`test_integrity.py`)

A dedicated test suite validates four attack scenarios through the live Mosquitto broker:

| Test | Scenario | Expected Result | Actual Result |
|------|----------|-----------------|---------------|
| 1a | Valid authenticated packet — correct key, correct data | HMAC verification passes | **PASS** |
| 1b | Valid packet roundtrip — publish through broker, verify on receipt | HMAC survives broker relay | **PASS** |
| 2 | Tampered payload — temperature changed from 25.3 to 99.9 after signing | HMAC mismatch detected | **PASS** |
| 3 | Wrong key — packet signed with an unauthorized PSK (`0xDEAD...`) | HMAC mismatch detected | **PASS** |
| 4 | Missing HMAC field — legacy/stripped packet with no `hmac` key | Missing HMAC flagged | **PASS** |

**Result: 5/5 tests passed.**

Test output:

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

  5/5 tests passed.
=======================================================
```

### 5.2 Live MCU Integration

With the CC3220SF board running the updated firmware and connected over TLS 1.2, the host receiver confirmed successful HMAC verification on every packet:

```
Connecting to 127.0.0.1:8883 with TLS...
Connected to Mosquitto Broker at 127.0.0.1:8883 (TLS)
Subscribed to topic: cc32xx/telemetry
Waiting for DHT11 sensor data...

[HMAC OK] [2026-04-17 05:53:51.736] Seq: 1 | Temp: 25.8°C | Hum: 45.8%
[HMAC OK] [2026-04-17 05:53:52.142] Seq: 2 | Temp: 25.3°C | Hum: 46.5%
[HMAC OK] [2026-04-17 05:53:52.860] Seq: 3 | Temp: 25.1°C | Hum: 47.7%
[HMAC OK] [2026-04-17 05:53:53.269] Seq: 4 | Temp: 25.0°C | Hum: 46.9%
[HMAC OK] [2026-04-17 05:53:53.683] Seq: 5 | Temp: 25.2°C | Hum: 48.6%
[HMAC OK] [2026-04-17 05:53:54.089] Seq: 6 | Temp: 24.9°C | Hum: 46.7%
[HMAC OK] [2026-04-17 05:53:54.511] Seq: 7 | Temp: 24.4°C | Hum: 46.0%
[HMAC OK] [2026-04-17 05:53:54.980] Seq: 8 | Temp: 24.5°C | Hum: 49.3%
[HMAC OK] [2026-04-17 05:53:55.434] Seq: 9 | Temp: 24.9°C | Hum: 48.3%
[HMAC OK] [2026-04-17 05:53:56.159] Seq: 10 | Temp: 25.7°C | Hum: 46.6%
[HMAC OK] [2026-04-17 05:53:56.549] Seq: 11 | Temp: 24.6°C | Hum: 47.8%
[HMAC OK] [2026-04-17 05:53:58.566] Seq: 12 | Temp: 25.5°C | Hum: 46.1%
[HMAC OK] [2026-04-17 05:54:00.241] Seq: 13 | Temp: 24.7°C | Hum: 45.4%
[HMAC OK] [2026-04-17 05:54:00.990] Seq: 14 | Temp: 25.1°C | Hum: 49.5%
[HMAC OK] [2026-04-17 05:54:03.294] Seq: 15 | Temp: 24.2°C | Hum: 48.6%
[HMAC OK] [2026-04-17 05:54:04.522] Seq: 16 | Temp: 24.4°C | Hum: 45.5%
[HMAC OK] [2026-04-17 05:54:05.700] Seq: 17 | Temp: 25.4°C | Hum: 45.2%
```

All 17 packets received from the live MCU passed HMAC verification with zero failures, confirming that the C implementation on the MCU and the Python implementation on the host produce identical digests.

### 5.3 Broker Log Confirmation

The Mosquitto broker log shows the full TLS-secured message flow:

```
New client connected from 10.0.0.34:53896 as clientId123 (p3, c1, k25)
Client clientId123 negotiated TLSv1.2 cipher DHE-RSA-AES256-GCM-SHA384
Sending CONNACK to clientId123 (0, 0)
Received PUBLISH from clientId123 (d0, q2, r0, m11, 'cc32xx/telemetry', ... (188 bytes))
Sending PUBLISH to MacHostReceiver (d0, q0, r0, m0, 'cc32xx/telemetry', ... (188 bytes))
```

Each PUBLISH message is approximately 188–190 bytes (the authenticated JSON payload), relayed from the MCU (`clientId123`) to the host receiver (`MacHostReceiver`) over QoS 2.

## 6. Key Management

### Current Approach

The 32-byte PSK is compiled into two locations during the research phase:

| Location | File | Format |
|----------|------|--------|
| MCU firmware | `hmac_auth.h` | C `uint8_t[32]` array |
| Host receiver | `host_receiver.py` | Python `bytes` list |
| Test suite | `test_integrity.py` | Python `bytes` list |

### Planned Improvements (Week 10+)

- Provision the PSK through the CC3220SF's secure file system at boot time rather than compiling it into source
- Derive per-device unique keys from a master secret
- Implement key rotation with version tagging
- Leverage hardware-backed key storage on the CC3220SF

## 7. System Architecture (Updated)

```
CC3220SF MCU                                    Host Machine
┌─────────────────────┐                         ┌──────────────────────┐
│  DHT11 Sensor Read  │                         │   Mosquitto Broker   │
│         │           │      TLS 1.2 / 8883     │   (server.crt/key)   │
│  buildTelemetryPayload()  ═══════════════════> │         │            │
│  ┌──────────────┐   │                         │         ▼            │
│  │ HMAC-SHA256  │   │                         │  ┌─────────────────┐ │
│  │ (hmac_auth.h)│   │                         │  │ host_receiver.py│ │
│  │ PSK signing  │   │                         │  │ HMAC verify()   │ │
│  └──────────────┘   │                         │  │ CSV logging     │ │
│  JSON + HMAC tag    │                         │  └─────────────────┘ │
└─────────────────────┘                         └──────────────────────┘
```

## 8. Deliverables Summary

| Deliverable | Status | Location |
|-------------|--------|----------|
| Authenticated packet format | Complete | `hmac_auth.h`, `mqtt_client_app.c` |
| Integrity-check results | 5/5 tests pass + live MCU verification | `test_integrity.py`, host receiver logs |
| Threat assumptions documentation | Complete | `docs/integrity_authentication.md` |

## 9. Limitations

| Limitation | Impact | Planned Resolution |
|------------|--------|--------------------|
| Hardcoded PSK | Key compromise requires re-flashing both sides | Week 10: secure provisioning |
| No replay protection | Valid old packets can be re-sent | Week 7: sequence + freshness checks |
| No timing validation | Delayed packets are not flagged | Week 8: inter-arrival monitoring |
| Single device / single key | Cannot distinguish multiple MCU nodes | Per-device key derivation |
| Software SHA-256 | Slower than NWP hardware crypto | Acceptable at current ~4 Hz throughput |

## 10. Next Steps (Week 7)

- Implement replay detection using sequence number validation and freshness windows
- Flag and discard packets with out-of-order or duplicate sequence numbers
- Add inter-packet timing baselines for anomaly detection groundwork
