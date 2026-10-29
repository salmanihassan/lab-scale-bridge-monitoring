# CC3220SF Wi-Fi node: real sensor data over secured MQTT (stage 2)

The board samples the accelerometer and both load cells every 10 ms and the three temperature probes once per second, exactly like the serial stream build. It sends one second of data, 100 samples, as one MQTT message over Wi-Fi to a Mosquitto broker on your laptop. A Python receiver checks every message and writes the data to CSV.

Stage 1 sent the data as plain MQTT. Stage 2 protects the link in layers and lets the receiver prove every packet is genuine before it is used.

## Status

- **Stage 1 ran on hardware on Oct 27** over the "batphone 2.0" hotspot: 111 packets, 0 missing, 0 rejected, 11,100 samples all 10 ms apart.
- **Stage 2 has not been built or run on hardware yet.** The first build and run are the real tests.
- The C code passes a syntax check against the real SDK 7.10 headers, with TLS on and off, with no errors or warnings.
- The HMAC code matches all RFC 4231 test vectors, and packets signed by the C code verify in Python.
- The host tests pass: every receiver verdict, plus full round trips through Mosquitto 2.0.18 for stage 2a and stage 2b.
- The security self-test stops 8 of 8 attacker moves against the stage 2b broker (5 of 5 for stage 2a).

## How the link is protected

| Layer | What it does | What it stops |
|---|---|---|
| **TLS 1.2** (stage 2b) | The board connects to port 8883 and checks the broker's certificate against the project CA built into the firmware. Only forward-secret AES-GCM and ChaCha20 suites are allowed. | Eavesdropping on the Wi-Fi, a fake broker, a man in the middle |
| **Logins and topic rules** | Each client has its own MQTT user and password. The ACL lets the board write only `bridge/CC3220SF_NODE_01/#` and lets the receiver only read `bridge/#`. Anonymous clients are refused. | Strangers publishing or reading, a stolen receiver login injecting data |
| **HMAC-SHA256 on every batch** | The board signs the whole payload with a 32-byte key. The packet names the key (`kid`). | Changed or forged data anywhere on the path, including on the broker itself |
| **Replay and freshness checks** (receiver) | `boot_id` plus `seq` must move forward. Boots that were replaced are refused, even after the receiver restarts. A packet much later than the link's normal delay is refused. | Replayed packets, packets held back and released later |

The receiver writes a sample to the CSV only after all of these checks pass. Everything else is logged with a verdict.

### What it does not stop (yet)

These are worth knowing for the research write-up and the attack modelling:

- **Physical access to the board.** The HMAC key and MQTT password are in the firmware image, so anyone who can read the board's flash can recover them. The CC3220's secure file storage could hold them instead.
- **Replay of a whole session the receiver never saw.** The receiver remembers every `boot_id` it has seen. A recording of a boot from a time when no receiver was running would still be accepted once. A fresh value from the receiver for each session (a nonce) would close this.
- **The status topic is not signed.** Only the topic rules protect `online` and `offline`.
- **Jamming or flooding.** These show up as gaps and late packets, but software cannot prevent them.
- **The broker can read the data.** TLS protects the Wi-Fi link only. The broker is on our laptop, so this is acceptable here.
- **`ca.key` is the master key.** Whoever holds it can impersonate the broker. It stays in `host\secrets` on the laptop and is never shared.

### Three SDK details found while building this

- **The board does not check the broker's IP address in its certificate.** The SDK only checks names when it connects by host name. It connects by IP here, so the CA check is what authenticates the broker.
- **The SDK's MQTT library continues without server verification** if the TLS layer reports error -453 (connected without server verification). That happens only when no CA file is given. This build always gives one.
- **The SDK's "full" cipher list includes RC4 and static-RSA suites.** This build names its three suites explicitly, and the broker accepts only those for TLS 1.2.

## What you need

- **The stage 1 setup:** CCS 21.0.1 and SDK 7.10 under `C:\ti`, the ME-2 `cc3220_daq` folder, Mosquitto for Windows, Python 3, and `network_config.h`.
- **Two Python packages** (PowerShell, in this folder):
  ```powershell
  py -m pip install -r host\requirements.txt
  ```

## One-time setup

**1. Network settings.** Keep `network_config.h` from stage 1. Nothing in it needs to change. `DT_BROKER_PORT` (1883) is used by stage 2a, and stage 2b uses 8883.

**2. Make the keys and certificates** (PowerShell, in this folder):

```powershell
py host\dt_setup_security.py
```

It reads the broker IP and device id from `network_config.h` and writes:

| File | Used by | Secret? |
|---|---|---|
| `secrets.h` | the board firmware: HMAC key, key id, board MQTT password, CA certificate | yes |
| `host\secrets\keys.json` | the receiver: HMAC keys, MQTT passwords | yes |
| `host\secrets\ca.key`, `server.key` | CA and broker private keys | yes |
| `host\secrets\passwd`, `acl` | Mosquitto's logins (hashed) and topic rules | the hashes, yes |
| `host\secrets\mosquitto_2a.conf`, `mosquitto_2b.conf` | the two broker configurations | no |
| `host\secrets\ca.crt`, `server.crt` | certificates | no |

`secrets.h` and `host\secrets` are in `.gitignore`. Never commit them, put them in a shared OneDrive folder, or paste them into a chat. Running the script a second time does nothing unless you add `--force` (see "Changing the keys").

**3. Open port 8883 in the Windows firewall** for devices on the same network (PowerShell as administrator). The stage 1 rule for 1883 is still needed for stage 2a:

```powershell
New-NetFirewallRule -DisplayName "Mosquitto 8883 TLS (bridge DT)" -Direction Inbound -Protocol TCP -LocalPort 8883 -RemoteAddress LocalSubnet -Action Allow
```

**4. The Mosquitto Windows service stays stopped,** as in stage 1.

## Bring-up order

Do stage 2a first. It changes only the login and the signatures, so if it fails the cause is narrow. Then switch on TLS for stage 2b.

| | Stage 2a | Stage 2b |
|---|---|---|
| Build | `gmake -f makefile all EXTRA_DEFS=-DDT_USE_TLS=0` | `gmake -f makefile all` |
| Broker | `mosquitto -c host\secrets\mosquitto_2a.conf -v` | `mosquitto -c host\secrets\mosquitto_2b.conf -v` |
| Receiver | `py host\dt_receiver.py --plain --name ...` | `py host\dt_receiver.py --name ...` |
| Self-test | `py host\dt_security_check.py --plain` | `py host\dt_security_check.py` |

The makefile now rebuilds everything that depends on `secrets.h`, `network_config.h` or the 2a/2b choice, so switching between them is just a different build command.

## Every run

Use three PowerShell windows, all starting in this folder:
`C:\Users\olumi\projects\dot-lab\lab-scale-bridge-monitoring\FA2026-CpE1\cc3220_wifi_daq`

**Window 1: broker** (stage 2b shown)

```powershell
& 'C:\Program Files\mosquitto\mosquitto.exe' -c host\secrets\mosquitto_2b.conf -v
```

**Window 2: receiver.** Use a new `--name` for every run:

```powershell
py host\dt_receiver.py --name wifi_2b_test1
```

**Window 3: build and flash.** Rebuild after changing code, `network_config.h` or the keys:

```powershell
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile all 2>&1 | Tee-Object -FilePath build_log.txt

$daq = 'C:\Users\olumi\projects\dot-lab\lab-scale-bridge-monitoring\SP2026-ME2\Fall 2026\Digital Twin TI Board Setup\cc3220_daq'
$env:TI_APPDATA_DIR = "$daq\build\uniflash_appdata"
$dslite = 'C:\ti\uniflash_9.6.0\deskdb\content\TICloudAgent\win\ccs_base\DebugServer\bin\DSLite.exe'
$cfg = "$daq\build\cc3220sf_xds110_uniflash.ccxml"
$out = 'C:\Users\olumi\projects\dot-lab\lab-scale-bridge-monitoring\FA2026-CpE1\cc3220_wifi_daq\build\dt_wifi_node.out'
& $dslite flash --config $cfg --core 0 --verbose --run $out
```

**Optional: the board's console** at **115200** baud, started before flashing in a fourth window:

```powershell
$p = New-Object System.IO.Ports.SerialPort 'COM3',115200,'None',8,'One'
$p.Open()
try { while ($true) { $l = $p.ReadLine(); $l; Add-Content 'C:\Users\olumi\projects\dot-lab\wifi_console_2b_01.txt' $l } } finally { $p.Close() }
```

**Optional: the security self-test**, in another window while the broker runs. It does not need the board. With the board running, `--inject` also sends a tampered, a forged and a replayed batch, and the receiver window should show them rejected:

```powershell
py host\dt_security_check.py
py host\dt_security_check.py --inject
```

## What you should see

On the console:

```text
[DT] ==== Bridge DT Wi-Fi node 0.2.0 ====
[DT] device CC3220SF_NODE_01, MAC ..., boot_id 1a2b3c4d
[DT] network "batphone 2.0", broker 172.20.10.2:8883, topic bridge/CC3220SF_NODE_01/batch
[DT] security: TLS 1.2 + login + HMAC, MQTT user dt_node01, key id k20261027-....
[DT] TLS: CA certificate dt-ca.pem written to the network processor
[DT] Wi-Fi: connecting to "batphone 2.0"...
[DT] Wi-Fi: got an IP address
[DT] MQTT: connecting to 172.20.10.2:8883...
[DT] MQTT: connected, publishing on bridge/CC3220SF_NODE_01/batch
```

On later boots the CA line says `already up to date`. The key itself is never printed.

In the Mosquitto window, the board's connection line ends with its user name, `u'dt_node01'`.

In the receiver window, the first line shows the link. On the laptop itself it is usually TLS 1.3 (the board uses 1.2):

```text
connected to 127.0.0.1:8883 as dt_receiver, TLSv1.3 TLS_AES_256_GCM_SHA384, listening on bridge/CC3220SF_NODE_01/batch
seq     12   3610 B  ok  z=+0.813 g  L1=   319512  L2=   639401  T=[31.13, 31.06, 30.25]  late=0
```

Packets are about 90 bytes larger than in stage 1 (the key id and the signature).

## If something goes wrong

| Symptom | Check |
|---|---|
| Build stops: `secrets.h is missing` | Run `py host\dt_setup_security.py` once |
| `MQTT: connection refused` | Mosquitto running with the config for the same stage as the build (2a on 1883, 2b on 8883), and the firewall rule for that port |
| `the broker refused the login` | The Mosquitto window says why. If the password was refused, the firmware and `host\secrets` come from different runs of the setup script. Rebuild and reflash |
| `TLS: the broker's certificate is not from the project CA` (-468) | Same cause. Rebuild and reflash after the last setup script run |
| `TLS: certificate date check failed` (-461) | The board's clock is set to the build time. Rebuild |
| Other negative `connect failed` numbers during 2b | Send the console log and the Mosquitto window. Stage 2a working rules out Wi-Fi, login and keys |
| Receiver: `REJECTED bad_mac` with no attack running | The board's key and `keys.json` do not match. Rebuild and reflash |
| Receiver: `REJECTED stale` now and then | The link stalled for over 10 s. Compare with `late=` and the gaps. `--max-age-ms` changes the limit |
| Receiver: `REJECTED stale_boot` after `--force` or on a new laptop | Old state. Use a new `--out-dir` or delete `runs\receiver_state.json` |

## Output files

**`<name>_samples.csv`:** one row per 10 ms sample, from accepted packets only.
- The first 12 columns match the serial stream CSV exactly: `Time_ms, X_g, Y_g, Z_g, Temp1_C, Temp2_C, Temp3_C, LoadCell1_Raw, LoadCell2_Raw, Motor, LoadCell1_New, LoadCell2_New`.
- Two columns follow: `Boot_ID, Seq`.
- An empty field means no valid reading.

**`<name>_packets.csv`:** one row per packet that could be read, accepted or not:
- arrival time on the laptop, sequence number, packets missing before this one, duplicate and new-boot flags
- `host_minus_board_ms` (laptop time minus board time)
- the board's own counters (failed accelerometer reads, late slots, discarded seconds, failed publishes, seconds offline)
- `kid` and `verdict`: `accepted`, `duplicate`, `bad_mac`, `unknown_kid`, `wrong_key`, `unsigned`, `malformed`, `wrong_topic`, `replay`, `stale_boot` or `stale`

**`<name>_rejected.log`:** every rejected packet with the reason.

**`runs\receiver_state.json`:** the boots the receiver has seen, kept so that a replay is refused even after the receiver restarts.

A `duplicate` is the latest packet arriving twice, which MQTT may do after a lost acknowledgement. It is logged but not written twice, and it is not counted as an attack.

## Packet format (`dt-batch/1.1`)

Topic `bridge/CC3220SF_NODE_01/batch`, QoS 1, about 3.6 KB per packet:

```json
{"schema":"dt-batch/1.1","kid":"k20261027-3fa1","device_id":"CC3220SF_NODE_01","boot_id":"1a2b3c4d",
 "seq":41,"fs_hz":100,"t0_ms":123450,"n":100,"accel_lsb_g":0.00390625,
 "dt_ms":[0,10,20,...],"ax":[-130,...],"ay":[58,...],"az":[208,...],
 "l1":[319500,...],"l2":[null,...,639400,...],"l1_new":"1000000010...","l2_new":"...",
 "temp_c":[30.5,null,29.69],
 "diag":{"uptime_ms":124450,"accel_fail":1,"late_slots":0,"dropped":0,"pub_fail":0,"not_connected":0},
 "mac":"5f0c...64 hex characters..."}
```

**How the signature works:**
1. The board builds the payload without `mac`.
2. It computes HMAC-SHA256 over every byte before the closing brace.
3. It replaces the closing brace with `,"mac":"<64 hex>"}`.

The receiver verifies the bytes before the last `,"mac":"` exactly as they arrived, so no JSON re-encoding can change what was signed.

- **`kid`** names the key, so keys can be replaced later without guessing.
- **`boot_id`** is a fresh random number from the radio chip at every power-up. With `seq` it tells a reboot (new `boot_id`, `seq` back at 0) from a replay (old `boot_id` or old `seq`).
- **Raw counts:** accelerometer and load values are raw counts, as in stage 1.
- **`bridge/CC3220SF_NODE_01/status`** stays retained: `online` after each connect, and `offline` as the MQTT will.

## Changing the keys

```powershell
py host\dt_setup_security.py --force
```

This replaces every key, password and certificate. Then rebuild and reflash the board, restart Mosquitto, and start the receiver with a new `--out-dir` (or delete `runs\receiver_state.json`). Keep a copy of the old `keys.json` if old runs need to be verified again.

## Not in stage 2

- **Keys in secure storage** on the board, and a per-session nonce (see "What it does not stop").
- **Persistent firmware.** The `.out` loaded through the debugger is gone after a power cycle. Flashing it into the board's serial flash is a separate step before the demo.
- **The motor.** It is not driven in this build.

## Tests

`tests/run_tests.sh` runs the HMAC vectors, the payload encoder and signer, and the receiver unit tests. `--e2e` adds the setup script, then a fake board, Mosquitto, the receiver and the security self-test for stage 2a and stage 2b. It runs on any machine with gcc, openssl, Python 3 with paho-mqtt and cryptography and, for `--e2e`, Mosquitto.
