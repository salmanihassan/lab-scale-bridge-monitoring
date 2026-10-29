# CC3220SF stream firmware: accelerometer, load cells and temperatures

Reads every bridge sensor on the CC3220SF LaunchPad and prints one CSV row every 10 ms over the USB serial port.

| Sensor | Pins |
|---|---|
| ADXL345 accelerometer | SCL P01 (header 9), SDA P02 (header 10) |
| HX711 Load 1 | DT P03 (header 4), SCK P61 (header 5) |
| HX711 Load 2 | DT P05 (header 7), SCK P62 (header 8) |
| DS18B20 Temp 1, 2, 3 | P63 (header 27), P53 (header 28), P50 (header 30), each with a 4.7 kΩ pull-up to 3V3 |
| Vibration motor | P18 (header 19), off in this build |

Everything is powered from 3V3. Nothing connects to the 5V pin.

## Status

- **Not yet built or run on hardware.** It could not be compiled with the TI toolchain here.
- It passes a syntax check against TI driver headers with every build option.
- It passes host simulations of the HX711 and DS18B20 pin protocols (see `tests/`).

The first build and the first run are the real tests.

## What it is based on

This is a copy of ME-2's `SP2026-ME2/Fall 2026/Digital Twin TI Board Setup/cc3220_daq`, with these changes:

1. **Microsecond timing for the HX711 and DS18B20 (the important fix).** The ME-2 drivers wait with `ClockP_usleep()`. On FreeRTOS that function rounds up to a whole scheduler tick, which is 1 ms here. So `ClockP_usleep(1)` really waits about 1 ms. That holds the HX711 clock high for about 1000 us, and the HX711 powers down if its clock stays high for more than 60 us. It also misses every DS18B20 timing window, which are 15 to 70 us. The new `src/timing.c` waits on the CPU cycle counter, and interrupts are held off only for the length of one bit slot.
2. **Accelerometer fixes from CpE-2** (`FA2026-CpE2/ADXL345_CC3220_firmware`), which passed on this board on Oct 26: 100 kHz I2C, a scan that reads one register, and configure-then-measure order.
3. **Temperatures are read in their own low-priority task.** Reading three probes takes about 20 ms, so it no longer delays the 10 ms sample rows.
4. **Load cells are polled every row, not every 100 ms.** A new conversion is picked up within 10 ms, and two new columns mark which rows carry one.
5. **Startup self-check** of every sensor, with the likely wiring fault named when one fails.
6. **The stream is the default mode.** The ME-2 default was an I2C scan only.

The pin assignments (`digital_twin_daq.syscfg`) are unchanged from ME-2.

## What you need on Windows

- Code Composer Studio 21.0.1, which supplies `gmake` and TI Arm Clang 5.1.1, at `C:\ti\ccs2101`. The installer is in the repo at `SP2026-ME2/Fall 2026/Digital Twin TI Board Setup/Installation Files`.
- SimpleLink CC32xx SDK 7.10.00.13 at `C:\ti\simplelink_cc32xx_sdk_7_10_00_13`.
- UniFlash 9.6.0 at `C:\ti\uniflash_9.6.0`. This is what you already used to flash the accelerometer test.
- The ME-2 `cc3220_daq` folder where it is in the repo. The build uses its SysConfig 1.20 and FreeRTOS copies.

To check the first two, run this in PowerShell:

```powershell
Test-Path 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe'
Test-Path 'C:\ti\ccs2101\ccs\tools\compiler\ti-cgt-armllvm_5.1.1.LTS\bin\tiarmclang.exe'
Test-Path 'C:\ti\simplelink_cc32xx_sdk_7_10_00_13'
```

All three should print `True`.

## Build

Run all the commands below from this folder (`FA2026-CpE1\cc3220_stream_daq` in your clone).

```powershell
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile all
```

The result is `build\dt_stream_daq.out`.

If you installed the tools somewhere else, add `SDK=...` or `TICLANG=...` to the end of the gmake line.

## Flash

This is the same method as the accelerometer test, with a different `$out`:

```powershell
$repo = git rev-parse --show-toplevel
$daq = "$repo\SP2026-ME2\Fall 2026\Digital Twin TI Board Setup\cc3220_daq"
$env:TI_APPDATA_DIR = "$daq\build\uniflash_appdata"
$dslite = 'C:\ti\uniflash_9.6.0\deskdb\content\TICloudAgent\win\ccs_base\DebugServer\bin\DSLite.exe'
$cfg = "$daq\build\cc3220sf_xds110_uniflash.ccxml"
$out = "$PWD\build\dt_stream_daq.out"
& $dslite flash --config $cfg --core 0 --verbose --run $out
```

## Log the output: 230400 baud, not 115200

Start the logger **before** flashing, in a separate PowerShell window. Use a new file name for every run.

Logs go in `runs\`, which is gitignored.

```powershell
New-Item -ItemType Directory -Force runs | Out-Null
$p = New-Object System.IO.Ports.SerialPort 'COM3',230400,'None',8,'One'
$p.Open()
try { while ($true) { $l = $p.ReadLine(); $l; Add-Content 'runs\stream_run01.csv' $l } } finally { $p.Close() }
```

## What you should see

The startup lines begin with `# ` and come first:

```text
# Digital Twin CC3220 DAQ, stream build (ME-2 cc3220_daq + CpE-2 ADXL345 fixes)
# UART 230400 baud, 8-N-1
# timing: cycle counter running (exact microsecond waits)
# ADXL345: found at 0x53, configured +/-2 g, 100 Hz
# HX711 Load 1 (DT P03, SCK P61): ready, raw=...
# HX711 Load 2 (DT P05, SCK P62): ready, raw=...
# DS18B20 Temp 1 (P63): present
# DS18B20 Temp 2 (P53): present
# DS18B20 Temp 3 (P50): present
# motor: off (compile-time disabled)
```

Then a header line and 100 rows per second:

```text
Time_ms,X_g,Y_g,Z_g,Temp1_C,Temp2_C,Temp3_C,LoadCell1_Raw,LoadCell2_Raw,Motor,LoadCell1_New,LoadCell2_New
```

- **The first 10 columns** are in the same order as ME-2's Arduino data.
- **An empty field** means no valid reading. The temperature columns stay empty for about the first second.
- **`LoadCellN_Raw`** is the raw HX711 count at gain 128, channel A. This is the same setting as the Arduino HX711 library, so counts are comparable to the old data.
- **`LoadCellN_New`** is 1 on the row where a new conversion arrived, about 10 times per second. Use only those rows when computing load noise, because the other rows repeat the last value.

## If a sensor reports a problem

| Startup line | Check |
|---|---|
| `HX711 ... NOT RESPONDING` | VCC on 3V3, GND, the DT wire |
| `HX711 ... looks like a wiring fault` | DT or SCK wire, or a loose load cell wire on the HX711 |
| `DS18B20 ... NOT FOUND` | 4.7 kΩ resistor from data to 3V3, red wire on 3V3, black on GND |
| `ADXL345: NOT FOUND` | Same wiring as the Oct 26 test |
| `timing: cycle counter NOT running` | The firmware still works with a less exact fallback. Report it. |

For a closer look at one sensor, build a diagnostic instead of the stream:

```powershell
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile clean all EXTRA_DEFS=-DDT_DIAG_LOADCELLS
```

The other options are `-DDT_DIAG_TEMPERATURES`, `-DDT_DIAG_ADXL345` and `-DDT_DIAG_I2C_SCAN`.

- **Load cell diagnostic:** prints each conversion, plus how many arrived each second (expect about 10).
- **Temperature diagnostic:** prints each probe's reading once per second, with counts of failed reads and how long the pin switch takes. The simulation shows reads stay reliable up to about 6 us for that switch.

Run `clean all` again without `EXTRA_DEFS` to go back to the stream.

## Identify the sensors after the first run

- **Load cells:** with the stream running, put a mass near the **left** support. The left cell should take roughly three quarters of the change. Load 1 should be the left cell, to match ME-2's `loadcell_left` column. If it is the other way round, swap the two HX711s' DT/SCK pairs.
- **Temperatures:** hold one probe in your fingers for about 10 seconds and see which column rises. Then match each column to ME-2's left, center and right probes.

## Tests

`tests/run_tests.sh` runs on any machine with gcc. It compiles the real `loadcells.c` and `temperature.c` against simulated pins, time and devices. It checks:

- all HX711 values, including the extremes
- that the HX711 clock stays high for less than 60 us
- 1-Wire timing with a pin switch time from 0.5 to 10 us, at the shortest and the typical DS18B20 hold time
- the CRC against Maxim's published example
- missing probes, a shorted bus and an all-zero reply

## Not changed

- **Motor:** stays off. It needs the transistor stage, and P18 can only switch it on and off.
- **Accelerometer range:** stays at +/-2 g.
- **Security:** there is no Wi-Fi, encryption or HMAC in this firmware. It is a data logger for wiring and calibration checks.
