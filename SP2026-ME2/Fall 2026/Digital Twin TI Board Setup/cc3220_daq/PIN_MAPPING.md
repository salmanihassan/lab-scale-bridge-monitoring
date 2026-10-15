# CC3220SF pin-allocation record

The assignments below were generated successfully by TI SysConfig 1.20.0
against SimpleLink CC32xx SDK 7.10.00.13 for `CC3220SF_LAUNCHXL`.
See [WIRING_GUIDE.md](WIRING_GUIDE.md) for the harness-facing table and
electrical checklist.

| SysConfig resource | LaunchPad header / silk | CC3220 ball | Direction | Use |
| --- | --- | --- | --- | --- |
| `CONFIG_I2C_0` SCL | header 9 / P01 | 1 | I2C | ADXL345 SCL; shared onboard I2C bus |
| `CONFIG_I2C_0` SDA | header 10 / P02 | 2 | I2C | ADXL345 SDA; shared onboard I2C bus |
| `CONFIG_UART2_0` TX | XDS110 backchannel / P55 | 55 | TX | USB virtual COM3 output |
| `CONFIG_UART2_0` RX | XDS110 backchannel / P57 | 57 | RX | Console input (not on the normal 20-pin header) |
| `CONFIG_HX711_1_DOUT` | header 4 / P03 | 3 | input | HX711 #1 DOUT |
| `CONFIG_HX711_1_CLK` | header 5 / P61 | 61 | output | HX711 #1 SCK |
| `CONFIG_HX711_2_DOUT` | header 7 / P05 | 5 | input | HX711 #2 DOUT |
| `CONFIG_HX711_2_CLK` | header 8 / P62 | 62 | output | HX711 #2 SCK |
| `CONFIG_DS18B20_1` | header 27 / P63 | 63 | open-drain emulated | DS18B20 #1 DQ |
| `CONFIG_DS18B20_2` | header 28 / P53 | 53 | open-drain emulated | DS18B20 #2 DQ |
| `CONFIG_DS18B20_3` | header 30 / P50 | 50 | open-drain emulated | DS18B20 #3 DQ |
| `CONFIG_MOTOR_EN` | header 19 / P18 | 18 | output | motor-driver envelope gate; disabled by default |

The isolated P18 route is GPIO, not a hardware-PWM output. SysConfig ruled out
all exposed hardware-PWM alternatives without sharing I2C, SOP/JTAG, or LEDs.
Therefore this version preserves the 10-Hz motor envelope only and requires
the separate `DT_ENABLE_MOTOR` build opt-in after transistor-stage review.
`DT_MOTOR_DEFAULT_STRENGTH` remains telemetry/API metadata; it is not a
hardware duty cycle on P18.
