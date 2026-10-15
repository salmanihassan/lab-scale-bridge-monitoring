# CC3220SF DAQ migration status — 2026-10-09

## Latest isolated ADXL345 test — FAIL

The hardware integration was restarted with only the GY-291 connected: VCC to
3.3 V, GND to GND, CS to 3.3 V, SDO to GND, SCL to P01/header 9, and SDA to
P02/header 10. All other sensors and the vibration motor were physically
disconnected.

The project configuration was verified: `CONFIG_I2C_0` is the LaunchPad I2C
resource on P01 (SCL) and P02 (SDA), with 3.3-V pull-ups expected through
J15/J16. The motor build opt-in `DT_ENABLE_MOTOR` remains undefined.

The diagnostic was narrowed to this I2C bus only: it probes both `0x53` and
`0x1D`, reads `DEVID` when either responds, and prints 100 live samples at
10 Hz only after a `0xE5` identity match. The CCS/SDK build completed, and
the resulting `.out` was loaded through the established UniFlash 9.6
XDS110 Debug Server workflow. No explicit post-load reset or power cycle was
issued; the tool's normal target reset happened before its load operation.

Actual COM3 output at 230400 baud:

```text
Digital Twin CC3220 DAQ boot
Target: CC3220SF_LAUNCHXL configuration; UART 230400 baud
ADXL345: NOT DETECTED
Motor: compile-time disabled (define DT_ENABLE_MOTOR only after transistor wiring review)
DIAGNOSTIC: ADXL345 I2C scan and live data (CSV disabled)
ADXL345 probe 0x53: no I2C ACK
ADXL345 probe 0x1D: no I2C ACK
ADXL345 data read: unavailable (no valid DEVID 0xE5)
```

Result: no address ACK, no `DEVID`, and no XYZ data. This prevents an
accelerometer pass. With this one-sensor setup, check at the GY-291 header:
VCC and CS must be approximately 3.3 V, SDO must be 0 V, and SDA/SCL must
idle at approximately 3.3 V (never 5 V). If those levels are correct, power
down and continuity-check P01-to-SCL and P02-to-SDA individually, then verify
that J15/J16 are installed or equivalent 3.3-V I2C pull-ups are present.

## Board-level bring-up: PASS

- **Development provisioning:** PASS. The CC3220SF serial flash was formatted
  and provisioned with the SDK 7.10 ImageCreator development image. No
  production-security, secure-lock, OTP, or debug-lock command was used.
- **Service pack:** PASS. Installed from SDK package
  `sp_3.22.0.1_2.7.0.0_2.2.0.7.bin` (ImageCreator reported NWP `3.21.0.0`,
  MAC `2.7.0.0`, PHY `2.2.0.7`).
- **XDS110:** PASS. UniFlash 9.6 Debug Server connected to the supplied
  `CC3220SF` / `Texas Instruments XDS110 USB Debug Probe` configuration and
  enumerated `Cortex_M4_0`.
- **Application:** PASS. `build/digital_twin_daq.out` was loaded at
  `0x01000800` into the CC3220SF on-chip executable flash and started through
  XDS110. The image loader reported `Success`.
- **UART:** PASS. XDS110 application UART is COM3, 230400 baud, 8-N-1, no
  flow control. The one-time diagnostic startup was captured below.
- **Stability:** PASS for this board-level test. A subsequent 10-second COM3
  capture received zero further bytes; the diagnostic emitted one boot header
  and showed no reset/restart loop.
- **Motor:** remains compile-time disabled. `DT_ENABLE_MOTOR` is not defined;
  the captured firmware explicitly reports that state and the I2C-scan mode
  never initializes the motor pin.

## Development provisioning performed

`development_provision.syscfg` was generated with project-local SysConfig
1.20 and programmed with SDK 7.10 `SLImageCreator`. Its generated
`cc3220sf_development_provision.sli` intentionally had **no MCU application
file and no user files**. The operation did the following:

- formatted the serial flash into ImageCreator **development** mode;
- installed the SDK-default TI service pack and TI default certificate
  catalog;
- applied the ImageCreator default system/network configuration;
- created no user Wi-Fi credential and installed no user certificate; and
- did not use OTP, secure bootloader, production mode, or a debug-lock option.

This was an authorized repurposing operation. It replaced the board's former
serial-flash filesystem, application, network configuration, and user
certificate state. The previous contents were not recoverably backed up.

## Application debug/programming method

CCS 21.0.1 built the firmware, but its installed current target database has
no CC3220SF device definition. UniFlash 9.6 includes the required official
CC3220SF/XDS110 target database and `FlashCC3220SF` loader, so its bundled
Debug Server was used for the XDS110 `.out` load/run operation. The
project-local `build/cc3220sf_xds110_uniflash.ccxml` is only a wrapper that
points at those installed TI database files; it adds no target settings.

The XDS110 probe reported firmware `2.3.0.9`; UniFlash recommends `3.0.0.43`.
It nevertheless connected and programmed successfully. No probe firmware
update was attempted.

## Captured UART startup output

```text
Digital Twin CC3220 DAQ boot
Target: CC3220SF_LAUNCHXL configuration; UART 230400 baud
ADXL345: NOT DETECTED
HX711: initialized; readings update only when DOUT is ready
DS18B20: initialized; 12-bit conversions are asynchronous
Motor: compile-time disabled (define DT_ENABLE_MOTOR only after transistor wiring review)
DIAGNOSTIC: I2C scan plus passive sensor status (CSV disabled)
HX711 status: CH1=waiting/not connected CH2=waiting/not connected (DOUT low means ready)
DS18B20 status: T1=valid T2=valid T3=valid
```

The absent ADXL345 and not-ready/not-connected HX711 channels are expected
while the external bridge sensors are disconnected. No physical sensor wiring
or motor enablement was performed.

## ADXL345 isolated 3.3-V wiring test — 2026-10-09: FAIL

After the GY-291 was rewired for a 3.3-V-only test (and the vibration motor
was physically disconnected), the diagnostic was extended only to report the
two valid ADXL345 I2C addresses, their `DEVID` responses, and one raw XYZ
sample after a valid `0xE5` identification. The motor remains compile-time
disabled; no motor code path was enabled or initialized.

`gmake -f makefile all` completed successfully. The resulting
`build/digital_twin_daq.out` was loaded and run through the same UniFlash
9.6 XDS110 Debug Server command without an explicit reset after loading. The
operation programmed only the nonpersistent, on-chip debug application image; it
did not erase or reformat serial flash or alter the service pack,
certificates, network configuration, or security configuration.

COM3 was opened at 230400 baud before loading. The actual capture was:

```text
Digital Twin CC3220 DAQ boot
Target: CC3220SF_LAUNCHXL configuration; UART 230400 baud
ADXL345: NOT DETECTED
HX711: initialized; readings update only when DOUT is ready
DS18B20: initialized; 12-bit conversions are asynchronous
Motor: compile-time disabled (define DT_ENABLE_MOTOR only after transistor wiring review)
DIAGNOSTIC: I2C scan plus passive sensor status (CSV disabled)
ADXL345 probe 0x53: no I2C ACK
ADXL345 probe 0x1D: no I2C ACK
ADXL345 data read: unavailable (no valid DEVID 0xE5)
HX711 status: CH1=waiting/not connected CH2=waiting/not connected (DOUT low means ready)
DS18B20 status: T1=valid T2=valid T3=valid
```

There was no acknowledgement at either possible ADXL345 address. Therefore,
no `DEVID` or acceleration reading exists to report. This is an I2C
electrical/wiring failure before address selection or register configuration,
not an ADXL345 device-ID mismatch. The next physical check is to measure at
the GY-291 header with USB power applied: VCC-to-GND and CS-to-GND must be
about 3.3 V, SDO-to-GND must be 0 V, and both SDA/P02 and SCL/P01 must idle
near 3.3 V (never 5 V). If either bus line is low or 5 V, remove power and
correct that wiring/pull-up condition before another test.

## Artifacts

| Artifact | Result |
| --- | --- |
| `build/digital_twin_daq.out` | Correct ELF artifact for the XDS110 debug/program operation; programmed and run. |
| `build/digital_twin_daq.bin` | Raw ImageCreator input; not directly programmed. |
| `build/cc3220sf_development_provision.sli` | Development provisioning image; programmed once during this authorized repurposing step. |
| `build/digital_twin_diagnostic.sli` | Earlier full image; not programmed. |

See [SETUP.md](SETUP.md) for the repeatable development-board workflow.
