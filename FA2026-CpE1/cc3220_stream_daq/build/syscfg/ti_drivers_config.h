/*
 *  ======== ti_drivers_config.h ========
 *  Configured TI-Drivers module declarations
 *
 *  The macros defines herein are intended for use by applications which
 *  directly include this header. These macros should NOT be hard coded or
 *  copied into library source code.
 *
 *  Symbols declared as const are intended for use with libraries.
 *  Library source code must extern the correct symbol--which is resolved
 *  when the application is linked.
 *
 *  DO NOT EDIT - This file is generated for the CC3220SF_LAUNCHXL
 *  by the SysConfig tool.
 */
#ifndef ti_drivers_config_h
#define ti_drivers_config_h

#define CONFIG_SYSCONFIG_PREVIEW

#define CONFIG_CC3220SF_LAUNCHXL
#ifndef DeviceFamily_CC3220
#define DeviceFamily_CC3220
#endif

#include <ti/devices/DeviceFamily.h>

#include <stdint.h>

/* support C++ sources */
#ifdef __cplusplus
extern "C" {
#endif


/*
 *  ======== GPIO ========
 */
extern const uint_least8_t CONFIG_MOTOR_EN_CONST;
#define CONFIG_MOTOR_EN 28

extern const uint_least8_t CONFIG_HX711_1_DOUT_CONST;
#define CONFIG_HX711_1_DOUT 12

extern const uint_least8_t CONFIG_HX711_1_CLK_CONST;
#define CONFIG_HX711_1_CLK 6

extern const uint_least8_t CONFIG_HX711_2_DOUT_CONST;
#define CONFIG_HX711_2_DOUT 14

extern const uint_least8_t CONFIG_HX711_2_CLK_CONST;
#define CONFIG_HX711_2_CLK 7

extern const uint_least8_t CONFIG_DS18B20_1_CONST;
#define CONFIG_DS18B20_1 8

extern const uint_least8_t CONFIG_DS18B20_2_CONST;
#define CONFIG_DS18B20_2 30

extern const uint_least8_t CONFIG_DS18B20_3_CONST;
#define CONFIG_DS18B20_3 0

/* The range of pins available on this device */
extern const uint_least8_t GPIO_pinLowerBound;
extern const uint_least8_t GPIO_pinUpperBound;

/* LEDs are active high */
#define CONFIG_GPIO_LED_ON  (1)
#define CONFIG_GPIO_LED_OFF (0)

#define CONFIG_LED_ON  (CONFIG_GPIO_LED_ON)
#define CONFIG_LED_OFF (CONFIG_GPIO_LED_OFF)


/*
 *  ======== I2C ========
 */

/*
 *  SCL: P01
 *  SDA: P02
 *  LaunchPad I2C
 */
extern const uint_least8_t              CONFIG_I2C_0_CONST;
#define CONFIG_I2C_0                    0
#define CONFIG_TI_DRIVERS_I2C_COUNT     1

/* ======== I2C Addresses and Speeds ======== */
#include <ti/drivers/I2C.h>

/* ---- CONFIG_I2C_0 I2C bus components ---- */

/* BMA222E address and max speed */
#define CONFIG_I2C_0_BMA222E_ADDR     (0x18)
#define CONFIG_I2C_0_BMA222E_MAXSPEED (400U) /* kbps */

/* TMP006 address and max speed */
#define CONFIG_I2C_0_TMP006_ADDR     (0x41)
#define CONFIG_I2C_0_TMP006_MAXSPEED (3400U) /* kbps */

/* CONFIG_I2C_0 max speed (supported by all components) */
#define CONFIG_I2C_0_MAXSPEED   (3400U) /* kbps */
#define CONFIG_I2C_0_MAXBITRATE ((I2C_BitRate)I2C_3400kHz)


/*
 *  ======== UART2 ========
 */

/*
 *  TX: P55
 *  RX: P57
 *  XDS110 UART
 */
extern const uint_least8_t                  CONFIG_UART2_0_CONST;
#define CONFIG_UART2_0                      0
#define CONFIG_TI_DRIVERS_UART2_COUNT       1


/*
 *  ======== Board_init ========
 *  Perform all required TI-Drivers initialization
 *
 *  This function should be called once at a point before any use of
 *  TI-Drivers.
 */
extern void Board_init(void);

/*
 *  ======== Board_initGeneral ========
 *  (deprecated)
 *
 *  Board_initGeneral() is defined purely for backward compatibility.
 *
 *  All new code should use Board_init() to do any required TI-Drivers
 *  initialization _and_ use <Driver>_init() for only where specific drivers
 *  are explicitly referenced by the application.  <Driver>_init() functions
 *  are idempotent.
 */
#define Board_initGeneral Board_init

#ifdef __cplusplus
}
#endif

#endif /* include guard */
