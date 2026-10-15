#ifndef BOARD_CONFIG_H_
#define BOARD_CONFIG_H_

/*
 * All physical routing lives in digital_twin_daq.syscfg.  Do not substitute
 * Arduino pin numbers here.  SysConfig creates the CONFIG_* identifiers used
 * by the drivers after the selected board and actual wiring are confirmed.
 */

#define DT_ACCEL_I2C_ADDRESS          0x53u
#define DT_ACCEL_ODR_HZ               100u
#define DT_OUTPUT_RATE_HZ             100u
#define DT_LOADCELL_RATE_HZ           10u
#define DT_TEMPERATURE_PERIOD_MS      1000u
#define DT_DS18B20_CONVERSION_MS      750u /* 12-bit worst case */

/* 230400 provides comfortable headroom for 100 CSV rows/s. */
#define DT_UART_BAUD                  230400u

#define DT_MOTOR_DEFAULT_HZ           10u
#define DT_MOTOR_DEFAULT_STRENGTH     175u
#define DT_MOTOR_PWM_PERIOD_US        1000u

#define DT_HX711_HALF_CYCLE_US        1u

/* The first hardware build must be diagnostic and motor-safe.  Set
 * DT_ENABLE_STREAM only after wiring validation.  DT_ENABLE_MOTOR is a
 * separate, deliberate opt-in because the isolated P18 route is an envelope
 * gate, not hardware duty PWM.  A more-specific DT_DIAG_* selection wins. */
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
#elif defined(DT_ENABLE_STREAM)
#define DT_STARTUP_MODE ACQ_MODE_STREAM
#else
#define DT_STARTUP_MODE ACQ_MODE_I2C_SCAN
#endif

#endif /* BOARD_CONFIG_H_ */
