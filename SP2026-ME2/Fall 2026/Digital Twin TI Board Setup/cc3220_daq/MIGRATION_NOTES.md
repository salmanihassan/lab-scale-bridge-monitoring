# Arduino-to-CC3220 migration notes

## Baseline analyzed

`Digital_Twin_All_Sensors.ino` was preserved unchanged. It configured an
ADXL345 at address `0x53` with `POWER_CTL=0x08`, `DATA_FORMAT=0x08`, and
`BW_RATE=0x0A`; polled two HX711 modules at 10 Hz; ran three independent
DS18B20 buses asynchronously; toggled a motor envelope at 10 Hz with strength
175/255; and printed ten columns near 100 Hz at 115200 baud.

The repository analysis independently confirms the same ten-channel order and
100-Hz expectation: `clean_ME2_data.m` documents timestamp, XYZ acceleration,
three temperatures, two load-cell raw values, and motor command in columns
1–10. Its MATLAB processing treats 100 Hz as the default sampling rate and
separately analyzes FFT response at the commanded vibration frequency.

## Native replacement

| Arduino baseline | CC3220 implementation | Reason |
| --- | --- | --- |
| `Wire` | TI Drivers `I2C` | Uses transactional I2C burst reads and explicit transfer failure checks |
| `Serial` | TI Drivers `UART2` over XDS110 VCOM | Allows a configured higher baud rate and separates startup diagnostics from CSV |
| `analogWrite` plus `millis()` motor toggling | TI Drivers `PWM` carrier plus FreeRTOS-scheduled excitation gate | Separates PWM duty from low-frequency mechanical excitation |
| `millis()` if-statements | `vTaskDelayUntil` 10-ms periodic release | Avoids cumulative scheduling drift from variable loop execution |
| DallasTemperature async conversion | three GPIO OneWire transactions with a conversion state machine | Retains individual buses but does not wait 750 ms |
| HX711 library `is_ready` / `read` | GPIO DOUT poll plus 24-bit sign conversion / 25th gain pulse | Preserves raw counts and does not wait for unavailable data |

## Timing decisions

The 100-Hz task reads the accelerometer first, then emits a row using the last
valid load-cell and temperature values. The load cells are only polled at 10 Hz.
Temperature conversion begins every second and is read at least 750 ms later;
there is no conversion-length blocking delay. The short OneWire bit slots and
the 25-pulse HX711 read are bounded microsecond-scale transactions, scheduled
outside the main ADXL345 burst path.

For resonance work around 4–7 Hz, use a stable 100-Hz sample stream, record
the actual timestamp column, and inspect `diff(Time_ms)` as part of every run's
quality control. The next performance upgrade, if needed, is the ADXL345 data-
ready interrupt plus FIFO, not a faster uncontrolled polling loop.

## Unresolved questions

1. The physical board marking/revision has not been observed, although the
   repository selects `CC3220SF_LAUNCHXL`.
2. The existing external wire locations are unknown. Seven GPIO/PWM resources
   are intentionally unbound instead of inventing a translation from Arduino.
3. The supply level and pullup topology of the particular HX711, DS18B20, and
   ADXL345 breakout modules must be checked before connection.
4. The DS18B20 code currently preserves three separate buses. Moving to one
   bus with fixed ROM IDs is a recommended future simplification only after a
   deliberate rewiring and ROM-discovery procedure.
5. Calibration coefficients remain deliberately out of the raw HX711 path.

## Validation status

The ADXL345 register values were checked against the Analog Devices ADXL345
Rev. G data sheet, which identifies the register map and 100-Hz rate code:
<https://www.analog.com/media/en/technical-documentation/data-sheets/ADXL345.pdf>.

This work is code-complete but not build-tested, flash-tested, or
hardware-tested. Those states must not be conflated.
