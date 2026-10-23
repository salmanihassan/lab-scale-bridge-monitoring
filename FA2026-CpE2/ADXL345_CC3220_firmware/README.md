# ADXL345 on the CC3220SF LaunchPad: please flash and test

Firmware from the CpE team (`pwmled2`: simulated temperature and humidity, HMAC, AES, fault injection) with the
ADXL345 accelerometer added over I2C, plus a self-checking hardware test.

## Status, honestly

- It **compiles and links with no errors** (CCS 12.8.1, SDK 7.10.00.13, SysConfig 1.15.0, TI Arm Clang 3.2.1).
- It has **never run on hardware.** The Mac it was built on cannot connect the debugger to the board
  (XDS110 errors -1170 and -261, even though the probe and a JTAG scan test both pass). So we need the Windows
  setup that has already flashed this board.

## What we are asking you to do

1. **Wire the GY-291 with the board unplugged:**

   | GY-291 | LaunchPad |
   |---|---|
   | SCL | P01 (header 9) |
   | SDA | P02 (header 10) |
   | VCC | 3V3 |
   | GND | GND |
   | CS | 3V3 (must be high, or the chip ignores I2C) |
   | SDO | GND (address 0x53) |

   The SOP2 jumper must be off. Nothing else should be on header 9 or 10.

2. **Flash the prebuilt image** (`prebuilt/pwmled2_adxl345_CC3220SF_LAUNCHXL_freertos_ticlang.out`) the way
   `SP2026-ME2/Fall 2026/Digital Twin TI Board Setup/cc3220_daq/SETUP.md` does, with `$out` pointing at that file:

   ```powershell
   $env:TI_APPDATA_DIR = '<...>\cc3220_daq\build\uniflash_appdata'
   $dslite = 'C:\ti\uniflash_9.6.0\deskdb\content\TICloudAgent\win\ccs_base\DebugServer\bin\DSLite.exe'
   $cfg = '<...>\cc3220_daq\build\cc3220sf_xds110_uniflash.ccxml'
   $out = '<...>\FA2026-CpE2\ADXL345_CC3220_firmware\prebuilt\pwmled2_adxl345_CC3220SF_LAUNCHXL_freertos_ticlang.out'
   & $dslite flash --config $cfg --core 0 --verbose --run $out
   ```

3. **Open the XDS110 application UART at 115200 baud, 8-N-1** (not 230400: this firmware uses 115200) before it
   starts, then reset the board so you catch the start.

## What you should see

An I2C scan, then prompts: lay the board **flat and still** for 10 s, then **shake** it for 5 s. Each check
prints PASS or FAIL, then a line `[ACC] x= y= z= g` every few seconds, followed by the usual `[AES] ...` packets.

| Scan result | Meaning |
|---|---|
| `0x18`, `0x49` and `0x53` all appear | Bus and ADXL345 are fine |
| `0x18` and `0x49` appear, `0x53` does not | Bus is fine; module power, CS, SDO or SDA/SCL wiring |
| Nothing appears | Bus problem |

A flat, still reading should be about x = 0, y = 0, z = +1.00 g with noise near 0.003 g.

## Please send back

The full serial output, and whether the flash itself worked. That tells us whether the problem is the Mac or the board.

## What changed from the original `pwmled2`

- **Motor PWM removed.** It used header 9 and 10 (P01/P02), which are the I2C pins. `USE_MOTOR_PWM` at the top of
  `pwmled2.c` is 0, and the packet reports `pwm_duty_us = 0` while the motor is off.
- **Acceleration is only printed on the serial port.** It is not in the encrypted packet. The HMAC canonical
  string is unchanged (`CC3220SF_NODE_01|seq|ts|temp|hum`).
- **Driver differences from `cc3220_daq`:** the bus scan reads one register (a zero-length write cannot find devices on
  this driver) and the bus runs at 100 kHz.

## Layout

```
src/        the sources: pwmled2.c, adxl345.c/.h, main_freertos.c, pwmled2.syscfg, image.syscfg, ...
prebuilt/   the built .out and .bin
```

To rebuild you need SysConfig **1.15.0** (the version shipped with SDK 7.10; SysConfig 1.21 and later cannot target the
CC3220SF) and the FreeRTOS kernel 202104.00.
