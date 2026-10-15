#include "acquisition.h"
#include "accelerometer.h"
#include "board_config.h"
#include "loadcells.h"
#include "temperature.h"
#include "vibration_motor.h"

#include <stdarg.h>
#include <stdbool.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include <FreeRTOS.h>
#include <task.h>
#include <ti/drivers/UART2.h>
#include "ti_drivers_config.h"

static UART2_Handle uart;

static void writeText(const char *text)
{
    if (uart != NULL) {
        (void)UART2_write(uart, text, strlen(text), NULL);
    }
}

static void logLine(const char *format, ...)
{
    char line[160];
    va_list args;
    va_start(args, format);
    (void)vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    writeText(line);
}

static void reportI2cAddress(uint8_t address)
{
    logLine("I2C device ACK at 0x%02X\r\n", address);
}

static void reportAdxl345Probe(uint8_t address)
{
    uint8_t device_id = 0u;

    if (ADXL345_probeResponded(address, &device_id)) {
        logLine("ADXL345 probe 0x%02X: ACK, DEVID=0x%02X\r\n",
                address, device_id);
    } else {
        logLine("ADXL345 probe 0x%02X: no I2C ACK\r\n", address);
    }
}

static uint32_t elapsedMilliseconds(void)
{
    return (uint32_t)xTaskGetTickCount() * (uint32_t)portTICK_PERIOD_MS;
}

static void runDiagnostics(Acquisition_Mode mode)
{
    ADXL345_Sample sample;
    HX711_Readings loads = {0};
    DS18B20_Readings temperatures = { .celsius = { NAN, NAN, NAN } };
    uint32_t started = elapsedMilliseconds();
    uint8_t sample_index;

    switch (mode) {
    case ACQ_MODE_I2C_SCAN:
        logLine("DIAGNOSTIC: ADXL345 I2C scan and live data (CSV disabled)\r\n");
        ADXL345_scanBus(reportI2cAddress);
        reportAdxl345Probe(0x53u);
        reportAdxl345Probe(0x1Du);
        if (ADXL345_read(&sample)) {
            logLine("ADXL345 verified: address=0x%02X, DEVID=0xE5\r\n",
                    ADXL345_getAddress());
            logLine("ADXL345 live capture: 100 samples at 10 Hz\r\n");
            for (sample_index = 0u; sample_index < 100u; ++sample_index) {
                logLine("ADXL345 sample %u/100 raw=%d,%d,%d g=%.4f,%.4f,%.4f\r\n",
                        (unsigned int)(sample_index + 1u),
                        sample.x_raw, sample.y_raw, sample.z_raw,
                        sample.x_g, sample.y_g, sample.z_g);
                vTaskDelay(pdMS_TO_TICKS(100u));
                if (!ADXL345_read(&sample)) {
                    logLine("ADXL345 live read failed at sample %u\r\n",
                            (unsigned int)(sample_index + 1u));
                    break;
                }
            }
        } else {
            logLine("ADXL345 data read: unavailable (no valid DEVID 0xE5)\r\n");
        }
        break;
    case ACQ_MODE_ADXL345:
        logLine("DIAGNOSTIC: ADXL345, Ctrl-C or reset to stop\r\n");
        for (;;) {
            if (ADXL345_read(&sample)) {
                logLine("ADXL345 raw=%d,%d,%d g=%.4f,%.4f,%.4f\r\n",
                        sample.x_raw, sample.y_raw, sample.z_raw,
                        sample.x_g, sample.y_g, sample.z_g);
            } else {
                logLine("ADXL345 read failed\r\n");
            }
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    case ACQ_MODE_LOADCELLS:
        logLine("DIAGNOSTIC: HX711, Ctrl-C or reset to stop\r\n");
        for (;;) {
            HX711_poll(&loads);
            logLine("HX711 raw=%ld (%s),%ld (%s)\r\n",
                    (long)loads.raw[0], loads.valid[0] ? "valid" : "waiting",
                    (long)loads.raw[1], loads.valid[1] ? "valid" : "waiting");
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    case ACQ_MODE_TEMPERATURES:
        logLine("DIAGNOSTIC: DS18B20, Ctrl-C or reset to stop\r\n");
        for (;;) {
            DS18B20_service(elapsedMilliseconds() - started, &temperatures);
            logLine("DS18B20 C=%.2f (%s),%.2f (%s),%.2f (%s)\r\n",
                    temperatures.celsius[0], temperatures.valid[0] ? "valid" : "invalid",
                    temperatures.celsius[1], temperatures.valid[1] ? "valid" : "invalid",
                    temperatures.celsius[2], temperatures.valid[2] ? "valid" : "invalid");
            vTaskDelay(pdMS_TO_TICKS(250));
        }
    case ACQ_MODE_MOTOR:
    #if defined(DT_ENABLE_MOTOR)
        logLine("DIAGNOSTIC: motor %u Hz, strength %u/255; reset to stop\r\n",
                DT_MOTOR_DEFAULT_HZ, DT_MOTOR_DEFAULT_STRENGTH);
        VibrationMotor_init();
        VibrationMotor_start(DT_MOTOR_DEFAULT_HZ, DT_MOTOR_DEFAULT_STRENGTH);
        for (;;) {
            VibrationMotor_service(elapsedMilliseconds());
            vTaskDelay(pdMS_TO_TICKS(1));
        }
    #else
        logLine("DIAGNOSTIC: motor is compile-time disabled; define DT_ENABLE_MOTOR after wiring review\r\n");
        break;
    #endif
    default:
        break;
    }
}

void Acquisition_run(Acquisition_Mode mode)
{
    ADXL345_Sample accel = {0};
    HX711_Readings loads = {0};
    DS18B20_Readings temperatures = {0};
    UART2_Params uart_params;
    TickType_t last_wake;
    uint32_t next_load_ms = 0u;
    bool accel_ok;

    UART2_Params_init(&uart_params);
    uart_params.baudRate = DT_UART_BAUD;
    uart = UART2_open(CONFIG_UART2_0, &uart_params);
    if (uart == NULL) {
        for (;;) { }
    }

    logLine("Digital Twin CC3220 DAQ boot\r\n");
    logLine("Target: CC3220SF_LAUNCHXL configuration; UART %lu baud\r\n",
            (unsigned long)DT_UART_BAUD);

    accel_ok = ADXL345_init();
    if (mode != ACQ_MODE_I2C_SCAN) {
        HX711_init();
        DS18B20_init();
    }
    /* A first-test diagnostic must never configure a motor drive pin. */
    #if defined(DT_ENABLE_MOTOR)
    if ((mode == ACQ_MODE_STREAM) || (mode == ACQ_MODE_MOTOR)) {
        VibrationMotor_init();
    }
    #endif

    if (accel_ok) {
        logLine("ADXL345: detected and configured at 0x%02X\r\n",
                ADXL345_getAddress());
    } else {
        logLine("ADXL345: NOT DETECTED\r\n");
    }
    if (mode != ACQ_MODE_I2C_SCAN) {
        logLine("HX711: initialized; readings update only when DOUT is ready\r\n");
        logLine("DS18B20: initialized; 12-bit conversions are asynchronous\r\n");
    }
    #if defined(DT_ENABLE_MOTOR)
    logLine("Motor gate: %s\r\n", (mode == ACQ_MODE_STREAM) ? "ready (P18 envelope gate)" : "disabled for diagnostic");
    #else
    logLine("Motor: compile-time disabled (define DT_ENABLE_MOTOR only after transistor wiring review)\r\n");
    #endif

    if (mode != ACQ_MODE_STREAM) {
        runDiagnostics(mode);
        return;
    }

    /* Diagnostics end here.  From this header onward only CSV reaches UART. */
    writeText("Time_ms,X_g,Y_g,Z_g,Temp1_C,Temp2_C,Temp3_C,LoadCell1_Raw,LoadCell2_Raw,Motor\r\n");
    #if defined(DT_ENABLE_MOTOR)
    VibrationMotor_start(DT_MOTOR_DEFAULT_HZ, DT_MOTOR_DEFAULT_STRENGTH);
    #endif
    last_wake = xTaskGetTickCount();

    for (;;) {
        char row[192];
        uint32_t now_ms = elapsedMilliseconds();

        /* Do the high-priority acquisition first every 10-ms cadence. */
        accel_ok = ADXL345_read(&accel);
        if (!accel_ok) {
            /* A synthetic zero is a valid-looking vibration sample.  Emit
             * NaN instead so downstream QC can discard a failed read. */
            accel.x_g = accel.y_g = accel.z_g = NAN;
        }

        #if defined(DT_ENABLE_MOTOR)
        VibrationMotor_service(now_ms);
        #endif
        if ((int32_t)(now_ms - next_load_ms) >= 0) {
            HX711_poll(&loads);
            next_load_ms = now_ms + (1000u / DT_LOADCELL_RATE_HZ);
        }
        DS18B20_service(now_ms, &temperatures);

        (void)snprintf(row, sizeof(row),
                       "%lu,%.4f,%.4f,%.4f,%.2f,%.2f,%.2f,%ld,%ld,%u\r\n",
                       (unsigned long)now_ms,
                       accel.x_g, accel.y_g, accel.z_g,
                       temperatures.celsius[0], temperatures.celsius[1],
                       temperatures.celsius[2],
                       (long)loads.raw[0], (long)loads.raw[1],
                       
                       #if defined(DT_ENABLE_MOTOR)
                       VibrationMotor_isOn() ? 1u : 0u
                       #else
                       0u
                       #endif
                       );
        writeText(row);

        /* vTaskDelayUntil prevents loop-body variation becoming sample-time
         * drift.  SysConfig must retain a 1-kHz FreeRTOS tick. */
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000u / DT_OUTPUT_RATE_HZ));
    }
}
