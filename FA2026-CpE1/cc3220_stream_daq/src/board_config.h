#ifndef BOARD_CONFIG_H_
#define BOARD_CONFIG_H_

/*
 * All physical routing lives in digital_twin_daq.syscfg (unchanged from the
 * ME-2 cc3220_daq project). See PIN_MAPPING.md there.
 */

#define DT_ACCEL_I2C_ADDRESS          0x53u
#define DT_ACCEL_ODR_HZ               100u
#define DT_OUTPUT_RATE_HZ             100u
#define DT_TEMPERATURE_PERIOD_MS      1000u
#define DT_DS18B20_CONVERSION_MS      750u  /* 12-bit worst case */

/* 230400 gives headroom for 100 CSV rows/s. The serial logger must match. */
#define DT_UART_BAUD                  230400u

#define DT_MOTOR_DEFAULT_HZ           10u
#define DT_MOTOR_DEFAULT_STRENGTH     175u
#define DT_MOTOR_PWM_PERIOD_US        1000u

/* HX711: SCK high and low time per bit. The HX711 needs at least 0.2 us and
 * powers down if SCK stays high for more than 60 us. Raise this (for example
 * to 5) if readings look corrupted with long wires or a slow level shifter. */
#define DT_HX711_HALF_CYCLE_US        1u
/* How long the startup check waits for each HX711 to report data ready.
 * At the usual 10 samples/s a working HX711 is ready within about 100 ms. */
#define DT_HX711_READY_TIMEOUT_MS     1000u

/* Default mode for this build is the CSV stream. A DT_DIAG_* define (makefile
 * EXTRA_DEFS) selects a single-sensor diagnostic instead. The motor stays
 * off unless DT_ENABLE_MOTOR is defined after the transistor stage is wired. */
#if defined(DT_DIAG_I2C_SCAN)
#define DT_STARTUP_MODE ACQ_MODE_I2C_SCAN
#elif defined(DT_DIAG_ADXL345)
#define DT_STARTUP_MODE ACQ_MODE_ADXL345
#elif defined(DT_DIAG_LOADCELLS)
#define DT_STARTUP_MODE ACQ_MODE_LOADCELLS
#elif defined(DT_DIAG_TEMPERATURES)
#define DT_STARTUP_MODE ACQ_MODE_TEMPERATURES
#elif defined(DT_DIAG_MOTOR)
#define DT_STARTUP_MODE ACQ_MODE_MOTOR
#else
#define DT_STARTUP_MODE ACQ_MODE_STREAM
#endif

#endif /* BOARD_CONFIG_H_ */
