# Encrypted Telemetry -- Crypto Configuration

This document covers the TLS setup for encrypted MQTT communication between
the CC3220SF MCU and the Mosquitto broker.

## Architecture

```
CC3220SF MCU                          Host Machine
┌──────────────┐    TLS 1.2 / 8883    ┌─────────────────┐
│ mqtt_client   │ ═══════════════════> │ Mosquitto Broker │
│ (NWP HW TLS) │                      │ server.crt/key   │
│ ca-cert.pem   │                      └────────┬────────┘
└──────────────┘                                │
                                       ┌────────▼────────┐
                                       │ host_receiver.py │
                                       │ (TLS client)     │
                                       │ ca-cert.pem      │
                                       └─────────────────┘
```

All traffic on the `cc32xx/telemetry` topic is encrypted end-to-end between
the MCU and the broker. The Python host receiver also connects over TLS.

## 1. Certificate Generation

### Prerequisites

- OpenSSL installed (`openssl version` to verify)

### Generate Certificates

```bash
cd broker/certs
./generate_certs.sh [BROKER_IP]
```

Default broker IP is `10.198.144.56`. Pass a different IP as the first argument
if your broker runs elsewhere.

This generates:

| File                  | Purpose                           |
|-----------------------|-----------------------------------|
| `certs/ca.key`        | CA private key (keep secure)      |
| `certs/ca-cert.pem`   | CA certificate (shared with clients) |
| `certs/server.key`    | Mosquitto server private key      |
| `certs/server.crt`    | Mosquitto server certificate      |
| `userFiles/ca-cert.pem` | Copy of CA cert for MCU flashing |

### Certificate Details

- **Algorithm**: RSA 2048-bit with SHA-256 signatures
- **CA validity**: 10 years (3650 days)
- **Server validity**: ~2 years (825 days)
- **SANs on server cert**: `IP:10.198.144.56`, `IP:127.0.0.1`, `DNS:localhost`

## 2. Mosquitto Broker Configuration

The broker config at `broker/mosquitto.conf` defines two listeners:

```
# TLS listener (primary)
listener 8883 0.0.0.0
cafile certs/ca-cert.pem
certfile certs/server.crt
keyfile certs/server.key
tls_version tlsv1.2
allow_anonymous true

# Plaintext listener (debug fallback -- remove for production)
listener 1883 0.0.0.0
allow_anonymous true
```

### Start the Broker

```bash
cd broker
./broker.sh
```

The `-v` flag enables verbose logging so you can see TLS handshake details.

## 3. MCU Firmware Configuration

### What Changed in `mqtt_client_app.c`

1. **`MQTT_SECURE_CLIENT` enabled** -- activates the `#ifdef` TLS path
2. **Connection flags** include:
   - `MQTTCLIENT_NETCONN_IP4` -- IPv4 addressing
   - `MQTTCLIENT_NETCONN_SEC` -- enable TLS
   - `MQTTCLIENT_NETCONN_SKIP_CERTIFICATE_CATALOG_VERIFICATION` -- required
     because our self-signed CA is not in TI's built-in root CA catalog
3. **Port 8883** -- standard MQTT-over-TLS port
4. **Date/time set** to current date for certificate validity checking
5. **TLS method**: `SLNETSOCK_SEC_METHOD_SSLv3_TLSV1_2`
6. **Cipher**: `SLNETSOCK_SEC_CIPHER_FULL_LIST`
7. **Secure file**: `ca-cert.pem` on the device filesystem

### Flashing the CA Certificate to the MCU

The CA certificate must be in the CC3220SF's internal filesystem. This is
configured in `image.syscfg` as `fileTree20` pointing to `ca-cert.pem`.

Steps:
1. Run `generate_certs.sh` (copies `ca-cert.pem` to `userFiles/`)
2. Open the project in CCS
3. Build the project (this regenerates the SLI image)
4. Flash using UniFlash -- the Image Creator will include `ca-cert.pem`

### Domain Name Verification

Since the MCU connects by IP address (`MQTTCLIENT_NETCONN_IP4`), domain name
verification is automatically disabled by the TI MQTT library. No additional
flag is needed for this.

## 4. Host Receiver Configuration

`broker/host_receiver.py` connects to the broker over TLS:

```python
client.tls_set(ca_certs="certs/ca-cert.pem", tls_version=ssl.PROTOCOL_TLSv1_2)
client.connect(BROKER_IP, 8883, 60)
```

Run from the `broker/` directory:

```bash
cd broker
python3 host_receiver.py
```

Data is logged to `raw_dataset_encrypted.csv`.

## 5. Validation Tests

### Run the Test Suite

```bash
cd broker
python3 test_tls_validation.py
```

Requires: Mosquitto running with TLS (`./broker.sh`).

### Test Scenarios

| Test            | Method                                | Expected         |
|-----------------|---------------------------------------|------------------|
| Valid TLS       | Correct CA cert, port 8883            | PASS (connected, payload decrypted) |
| Wrong CA        | Random self-signed cert, port 8883    | PASS (SSL handshake rejected) |
| No TLS          | Plaintext connection to port 8883     | PASS (protocol mismatch rejected) |

### Interpreting Results

```
=======================================================
  SUMMARY
=======================================================
  [PASS] Valid TLS Connect
  [PASS] Valid TLS Decrypt
  [PASS] Wrong CA Rejected
  [PASS] Plaintext Rejected

  4/4 tests passed.
=======================================================
```

## 6. Troubleshooting

### "WRONG ROOT CA" error on MCU serial console

The MCU's NWP could not verify the server certificate against the CA cert
on its filesystem. Causes:
- `ca-cert.pem` was not flashed (re-flash with UniFlash)
- Certificates were regenerated on the host but not re-flashed to the MCU
- The `MQTTCLIENT_NETCONN_SKIP_CERTIFICATE_CATALOG_VERIFICATION` flag is
  missing (required for self-signed CAs)

### MCU fails TLS handshake with date/time error

The NWP validates certificate dates. Make sure the `setTime()` values in
`mqtt_client_app.c` are set to a date within the certificate validity period.
The CA cert is valid for 10 years from generation; the server cert for ~2 years.

### Python receiver gets `ssl.SSLCertVerificationError`

The CA cert used by Python does not match the one that signed the server cert.
Regenerate certs and ensure `broker/certs/ca-cert.pem` is consistent.

### Mosquitto fails to start with "Error: Unable to load server key"

Check file permissions on `certs/server.key`. The Mosquitto process must have
read access. Also verify the paths in `mosquitto.conf` are relative to the
directory where `broker.sh` is launched from.

### Testing with a different broker IP

1. Regenerate certs: `cd broker/certs && ./generate_certs.sh <NEW_IP>`
2. Update `MQTT_CONNECTION_ADDRESS` in `mqtt_client_app.c`
3. Update `BROKER_IP` in `host_receiver.py`
4. Re-flash the MCU with the new `ca-cert.pem`
5. Restart Mosquitto

## 7. Security Notes

- The `ca.key` and `server.key` files are private keys. Do not commit them
  to version control or share them.
- The plaintext listener on port 1883 is provided for debugging only.
  Remove it from `mosquitto.conf` in production.
- For production deployments, replace self-signed certificates with
  certificates from a trusted CA.
- The CC3220SF's NWP handles TLS in hardware, so there is negligible
  performance impact on the application processor.
