# CC3220SF DAQ wiring guide

This guide is for the CC3220SF LaunchPad detected through its onboard XDS110.
Every external signal is 3.3-V logic. The Arduino identifiers are historical
origins from `Digital_Twin_All_Sensors.ino`, not CC3220 pin numbers.

| Device signal | Arduino origin | CC3220 SysConfig resource | LaunchPad connection | Notes |
| --- | --- | --- | --- | --- |
| ADXL345 SCL | `Wire` SCL (not named in sketch) | `CONFIG_I2C_0` | header 9, silk P01 | 3.3-V I2C; shared with LaunchPad sensors |
| ADXL345 SDA | `Wire` SDA (not named in sketch) | `CONFIG_I2C_0` | header 10, silk P02 | 3.3-V I2C; address must be `0x53` |
| ADXL345 VCC/GND | 3.3 V/GND | n/a | 3V3/GND headers | Do not retain 5-V I2C pullups |
| DS18B20 #1 DQ | A1 | `CONFIG_DS18B20_1` | header 27, silk P63 | 4.7-kΩ pullup from DQ to 3V3 |
| DS18B20 #2 DQ | A2 | `CONFIG_DS18B20_2` | header 28, silk P53 | separate 4.7-kΩ pullup to 3V3 |
| DS18B20 #3 DQ | A3 | `CONFIG_DS18B20_3` | header 30, silk P50 | separate 4.7-kΩ pullup to 3V3 |
| each DS18B20 VDD/GND | 5 V/GND on Arduino wiring | n/a | 3V3/GND headers | use powered, not parasite, mode for first test |
| HX711 #1 DOUT | D2 | `CONFIG_HX711_1_DOUT` | header 4, silk P03 | input; never exceed 3.3 V |
| HX711 #1 SCK | D1 | `CONFIG_HX711_1_CLK` | header 5, silk P61 | output to HX711 clock |
| HX711 #2 DOUT | D4 | `CONFIG_HX711_2_DOUT` | header 7, silk P05 | input; never exceed 3.3 V |
| HX711 #2 SCK | D3 | `CONFIG_HX711_2_CLK` | header 8, silk P62 | output to HX711 clock |
| HX711 power / ground | module VCC/GND | n/a | verify module, common GND | level-shift DOUT if a 5-V module drives it high |
| motor-driver control | D6 `analogWrite` | `CONFIG_MOTOR_EN` | header 19, silk P18 | 10-Hz on/off envelope only; compile-time disabled by default |
| motor supply / return | external | n/a | external driver + common GND | never connect the motor to P18 or the 3V3 rail |
| host serial output | `Serial` TX over USB | `CONFIG_UART2_0` | onboard XDS110, COM3 | 230400, 8-N-1, no flow control |

## Before connecting power

- Use one shared ground between the LaunchPad, every sensor, and the motor
  driver; power the motor from its own suitable supply.
- Put a transistor/MOSFET stage and flyback protection between P18 and the
  motor. P18 is a logic signal only.
- Keep the I2C pullups at 3.3 V. The board’s I2C jumpers may already provide
  pullups; if they are removed, fit external pullups before testing.
- Verify the exact HX711 breakout supply scheme. Many boards allow 3.3-V
  operation; a module with 5-V DOUT needs a level shifter before P03/P05.
- The default image only scans I2C and passively reports HX711/DS18B20 status.
  It does not configure or energize P18.

## Motor limitation

With I2C, XDS110 UART, SOP/JTAG, and onboard LEDs reserved, the stock header
has no isolated hardware-PWM pin accepted by SysConfig. P18 was selected for
the safest external motor-driver gate. If true 175/255 duty control is required,
use an external PWM driver or accept a documented board modification; do not
reassign P01/P02, SOP, JTAG, or LED pins casually.
