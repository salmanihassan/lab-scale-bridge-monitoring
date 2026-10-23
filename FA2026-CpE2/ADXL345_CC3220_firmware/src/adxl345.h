/*
 * adxl345.h
 * ADXL345 (GY-291) accelerometer on the CC3220SF LaunchPad I2C bus, for the CpE-2 MQTT project.
 *
 * Wiring: SCL -> P01 (header 9), SDA -> P02 (header 10), VCC -> 3V3, GND -> GND,
 *         CS -> 3V3 (selects I2C mode), SDO -> GND (address 0x53). INT1/INT2 unused.
 *
 * Needs an I2C instance named CONFIG_I2C_0 in SysConfig (Use Hardware: LaunchPad I2C).
 */
#ifndef ADXL345_H_
#define ADXL345_H_

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int16_t x_raw, y_raw, z_raw;
    float   x_g, y_g, z_g;
} ADXL345_Sample;

/* Open the bus at 100 kHz, find the chip at 0x53 or 0x1D, check DEVID == 0xE5, start measuring
 * (+/-2 g, full resolution, 100 Hz). Returns false if the chip does not answer or is not an ADXL345. */
bool ADXL345_init(void);

/* One X/Y/Z reading in raw counts and in g (3.9 mg per count). */
bool ADXL345_read(ADXL345_Sample *sample);

/* I2C address the chip answered at (0x53 or 0x1D), or 0 if not found. */
uint8_t ADXL345_address(void);

/* Calls report(address) for every device that acknowledges a 1-byte register read.
 * (A zero-length write cannot be used to scan: the CC32xx I2C driver rejects it.) */
void ADXL345_scan(void (*report)(uint8_t address));

/* Output hook: the host project must define this (print the string on its UART). Examples:
 *   pwmled2:      void ADXL345_puts(const char *s) { UART2_write(g_uart, s, strlen(s), NULL); }
 *   MQTT project: void ADXL345_puts(const char *s) { UART_PRINT("%s", s); }                    */
void ADXL345_puts(const char *s);

/* Hardware test over ADXL345_puts: scan, identify, 10 s stillness check (gravity = 1 g, low noise),
 * 5 s shake check, then PASS or FAIL with the reason. Call once from the main thread after the UART is open. */
void ADXL345_bringup(void);

#endif /* ADXL345_H_ */
