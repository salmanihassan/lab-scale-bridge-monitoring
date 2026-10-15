# CC3220 structural-health-monitoring acquisition firmware

This is a new, stand-alone Phase 1 firmware project for the `CC3220SF_LAUNCHXL`
target indicated by the existing repository's CCS/SysConfig projects. It has not
been flashed or run on hardware. The physical board marking and external harness
must still be confirmed before generating the final SysConfig pin solution.

## What the firmware does

`src/acquisition.c` executes a periodic FreeRTOS task at 100 Hz. Each 10-ms
record begins with an ADXL345 I2C burst read, then emits the current accelerometer
sample and the most recently valid readings from the slower devices.

| Signal | Driver / method | Update behavior |
| --- | --- | --- |
| ADXL345 | TI `I2C` at 400 kHz | 6-byte XYZ burst every 10 ms; configures `DEVID`, measurement mode, full-resolution +/-2 g, and 100-Hz ODR |
| HX711 ×2 | TI `GPIO`, 25-clock sample transaction | DOUT-polled at 10 Hz; preserves signed raw 24-bit counts and the latest valid sample |
| DS18B20 ×3 | TI `GPIO` OneWire state machine | starts conversions every second and reads after 750 ms; it never waits 750 ms in the acquisition task |
| motor | TI `PWM` with software excitation gate | 1-kHz carrier, default 10-Hz on/off excitation, duty scaled from the Arduino 0–255 setting |
| output | TI `UART2` / XDS110 virtual COM port | a synchronized CSV row every 10 ms |

The first target is 230400 baud rather than 115200. A representative 85–95 byte
row requires about 850–950 serial bits; 100 rows/s therefore needs roughly
85–95 kbit/s. At 115200 baud that is 74–82% link utilization before jitter or
longer numeric fields; at 230400 it is 37–41%. This preserves enough timing
headroom for vibration measurements. Change `DT_UART_BAUD` only if a host tool
cannot reliably use 230400.

The CSV schema remains compatible in column order with the Arduino stream:

```text
Time_ms,X_g,Y_g,Z_g,Temp1_C,Temp2_C,Temp3_C,LoadCell1_Raw,LoadCell2_Raw,Motor
```

`Motor` is numeric (`0`/`1`) rather than `OFF`/`ON`, which retains the same
meaning while making MATLAB numeric import more reliable. The repository's data
cleaner expects this same ten-channel order and a nominal 100-Hz sample rate.

## Build

1. Install the TI tools and SDK listed in `SETUP.md`.
2. In CCS, import this directory as a SysConfig/FreeRTOS project (or create a
   new `CC3220SF_LAUNCHXL`, FreeRTOS project and add this directory's sources).
3. Open `digital_twin_daq.syscfg`; select actual pins for every `CONFIG_*`
   resource listed in `PIN_MAPPING.md`. Do not use unverified inherited wiring.
4. Ensure the FreeRTOS tick is 1000 Hz. Build, then resolve any tool-version
   migration prompts through SysConfig rather than hand-editing generated files.

The `src` folder deliberately contains no generated `ti_drivers_config.*` files;
the installed SDK's SysConfig version must generate them for the local toolchain.

## Diagnostics

Before building, add exactly one preprocessor symbol to produce a diagnostic
build. Diagnostic text is emitted before CSV mode and is never mixed with it.

| Symbol | Test |
| --- | --- |
| `DT_DIAG_I2C_SCAN` | I2C address scan |
| `DT_DIAG_ADXL345` | ADXL345 raw and g readings |
| `DT_DIAG_LOADCELLS` | two HX711 raw readings and ready state |
| `DT_DIAG_TEMPERATURES` | three DS18B20 values and validity |
| `DT_DIAG_MOTOR` | default motor PWM/excitation |

No diagnostic switch selects normal streaming; omit all five symbols for the
production CSV stream.

## Status

- Code-complete: yes, subject to final SysConfig pin bindings and a TI build.
- Build-tested: no — the required SDK/compiler are not installed on this PC.
- Flash-tested: no.
- Hardware-tested: no.

See `MIGRATION_NOTES.md` and `PIN_MAPPING.md` before connecting hardware.
