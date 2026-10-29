/*
 * Startup self-check, then either the CSV stream (default) or one diagnostic.
 *
 * Output format on the XDS110 UART (DT_UART_BAUD, 8-N-1):
 *   lines starting with "# "  startup and status messages (skip when parsing)
 *   one header line           column names, same first 10 columns as ME-2
 *   one row every 10 ms       Time_ms,X_g,Y_g,Z_g,Temp1_C,Temp2_C,Temp3_C,
 *                             LoadCell1_Raw,LoadCell2_Raw,Motor,
 *                             LoadCell1_New,LoadCell2_New
 *
 * An empty field means "no valid reading" (failed accelerometer read, a probe
 * that has not passed its CRC, a load cell that has never reported).
 * LoadCellN_Raw repeats the last conversion between HX711 updates (about every
 * 100 ms at 10 samples/s). LoadCellN_New is 1 only on the row that received a
 * new conversion, so repeated values can be dropped before computing noise.
 */
#include "acquisition.h"
#include "accelerometer.h"
#include "board_config.h"
#include "loadcells.h"
#include "temperature.h"
#include "timing.h"
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

static const char *const loadPins[2] = { "DT P03, SCK P61", "DT P05, SCK P62" };
static const char *const tempPins[3] = { "P63", "P53", "P50" };

static void writeText(const char *text)
{
    if (uart != NULL) {
        (void)UART2_write(uart, text, strlen(text), NULL);
    }
}

static void logLine(const char *format, ...)
{
    char line[200];
    va_list args;

    va_start(args, format);
    (void)vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    writeText(line);
}

/*
 * Appends to row[] with a direct snprintf() call and a literal format string.
 *
 * This must stay a macro, not a function that forwards to vsnprintf(). The
 * TI Arm Clang linker picks the printf engine by reading the literal format
 * strings at each printf-family call. When every format string arrives
 * through a variable it picked the "minimal" engine, which supports only %s
 * and %c, and every number printed as a stray letter (first run, Oct 26).
 * The literals below contain %lu, %ld, %u and %.4f, so the full engine is
 * linked and logLine() benefits too.
 */
#define ROW_APPEND(row, len, ...)                                              \
    do {                                                                       \
        if ((len) < sizeof(row)) {                                             \
            int n_ = snprintf((row) + (len), sizeof(row) - (len), __VA_ARGS__); \
            if (n_ > 0) {                                                      \
                (len) += (size_t)n_;                                           \
                if ((len) >= sizeof(row)) {                                    \
                    (len) = sizeof(row) - 1u;                                  \
                }                                                              \
            }                                                                  \
        }                                                                      \
    } while (0)

static uint32_t elapsedMilliseconds(void)
{
    return (uint32_t)xTaskGetTickCount() * (uint32_t)portTICK_PERIOD_MS;
}

static bool suspiciousRaw(int32_t raw)
{
    /* Typical results of a floating or shorted DT line, not of a load cell. */
    return (raw == 0) || (raw == -1) || (raw == 8388607) || (raw == -8388608);
}

static void reportI2cAddress(uint8_t address)
{
    logLine("#   I2C device answers at 0x%02X%s\r\n", address,
            ((address == 0x53u) || (address == 0x1Du)) ? "  <- ADXL345 address" : "");
}

/* ------------------------------------------------------------ self-check */

static void selfCheck(bool accel_ok, bool temps_present[3])
{
    uint8_t index;

    logLine("# timing: %s\r\n", Timing_cycleCounterOk()
            ? "cycle counter running (exact microsecond waits)"
            : "cycle counter NOT running, using UtilsDelay fallback");

    if (accel_ok) {
        logLine("# ADXL345: found at 0x%02X, configured +/-2 g, 100 Hz\r\n",
                ADXL345_getAddress());
    } else {
        logLine("# ADXL345: NOT FOUND (check SCL P01, SDA P02, VCC/CS on 3V3, SDO on GND)\r\n");
    }

    for (index = 0u; index < 2u; ++index) {
        int32_t raw = 0;
        if (HX711_waitAndRead(index, DT_HX711_READY_TIMEOUT_MS, &raw)) {
            logLine("# HX711 Load %u (%s): ready, raw=%ld%s\r\n",
                    (unsigned)(index + 1u), loadPins[index], (long)raw,
                    suspiciousRaw(raw) ? "  <- looks like a wiring fault" : "");
        } else {
            logLine("# HX711 Load %u (%s): NOT RESPONDING, DT never went low "
                    "(check VCC on 3V3, GND, DT wire)\r\n",
                    (unsigned)(index + 1u), loadPins[index]);
        }
    }

    for (index = 0u; index < 3u; ++index) {
        temps_present[index] = DS18B20_isPresent(index);
        logLine("# DS18B20 Temp %u (%s): %s\r\n", (unsigned)(index + 1u), tempPins[index],
                temps_present[index] ? "present"
                : "NOT FOUND (check 4.7k pull-up to 3V3, red to 3V3, black to GND)");
    }

    #if defined(DT_ENABLE_MOTOR)
    logLine("# motor: enabled on P18 (%u Hz on/off envelope)\r\n", DT_MOTOR_DEFAULT_HZ);
    #else
    logLine("# motor: off (compile-time disabled)\r\n");
    #endif
}

/* ------------------------------------------------------------ diagnostics */

static void runDiagnostics(Acquisition_Mode mode)
{
    ADXL345_Sample sample;
    HX711_Readings loads;
    DS18B20_Readings temperatures;
    DS18B20_Stats stats[3];
    uint32_t window_start, counts[2];
    uint8_t index;

    memset(&loads, 0, sizeof(loads));

    switch (mode) {
    case ACQ_MODE_I2C_SCAN:
        logLine("# DIAGNOSTIC: I2C scan\r\n");
        ADXL345_scanBus(reportI2cAddress);
        logLine("# scan done\r\n");
        break;

    case ACQ_MODE_ADXL345:
        logLine("# DIAGNOSTIC: ADXL345 at 10 Hz, reset to stop\r\n");
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
        logLine("# DIAGNOSTIC: HX711, every new conversion, rate summary each second\r\n");
        window_start = elapsedMilliseconds();
        counts[0] = counts[1] = 0u;
        for (;;) {
            HX711_poll(&loads);
            for (index = 0u; index < 2u; ++index) {
                if (loads.fresh[index]) {
                    ++counts[index];
                    logLine("Load%u raw=%ld\r\n", (unsigned)(index + 1u), (long)loads.raw[index]);
                }
            }
            if ((uint32_t)(elapsedMilliseconds() - window_start) >= 1000u) {
                logLine("# conversions in the last second: Load1=%lu Load2=%lu (expect about 10)\r\n",
                        (unsigned long)counts[0], (unsigned long)counts[1]);
                counts[0] = counts[1] = 0u;
                window_start = elapsedMilliseconds();
            }
            vTaskDelay(pdMS_TO_TICKS(5));
        }

    case ACQ_MODE_TEMPERATURES:
        logLine("# DIAGNOSTIC: DS18B20 once per second, reset to stop\r\n");
        if (!DS18B20_startTask()) {
            logLine("# could not start the temperature task\r\n");
            break;
        }
        for (;;) {
            vTaskDelay(pdMS_TO_TICKS(1000));
            DS18B20_get(&temperatures);
            for (index = 0u; index < 3u; ++index) {
                DS18B20_getStats(index, &stats[index]);
            }
            logLine("Temp C=%.2f,%.2f,%.2f valid=%u%u%u | reads=%lu no_answer=%lu,%lu,%lu "
                    "crc_err=%lu,%lu,%lu | pin switch %lu us\r\n",
                    temperatures.celsius[0], temperatures.celsius[1], temperatures.celsius[2],
                    temperatures.valid[0], temperatures.valid[1], temperatures.valid[2],
                    (unsigned long)stats[0].reads,
                    (unsigned long)stats[0].no_presence, (unsigned long)stats[1].no_presence,
                    (unsigned long)stats[2].no_presence,
                    (unsigned long)stats[0].crc_errors, (unsigned long)stats[1].crc_errors,
                    (unsigned long)stats[2].crc_errors,
                    (unsigned long)DS18B20_switchOverheadUs());
        }

    case ACQ_MODE_MOTOR:
    #if defined(DT_ENABLE_MOTOR)
        logLine("# DIAGNOSTIC: motor %u Hz, strength %u/255; reset to stop\r\n",
                DT_MOTOR_DEFAULT_HZ, DT_MOTOR_DEFAULT_STRENGTH);
        VibrationMotor_start(DT_MOTOR_DEFAULT_HZ, DT_MOTOR_DEFAULT_STRENGTH);
        for (;;) {
            VibrationMotor_service(elapsedMilliseconds());
            vTaskDelay(pdMS_TO_TICKS(1));
        }
    #else
        logLine("# DIAGNOSTIC: motor is compile-time disabled; define DT_ENABLE_MOTOR after wiring review\r\n");
        break;
    #endif

    default:
        break;
    }
}

/* ------------------------------------------------------------ stream */

static void runStream(void)
{
    ADXL345_Sample accel;
    HX711_Readings loads;
    DS18B20_Readings temperatures;
    TickType_t last_wake;
    uint8_t index;

    memset(&accel, 0, sizeof(accel));
    memset(&loads, 0, sizeof(loads));

    if (!DS18B20_startTask()) {
        logLine("# could not start the temperature task; temperature columns stay empty\r\n");
    }

    writeText("Time_ms,X_g,Y_g,Z_g,Temp1_C,Temp2_C,Temp3_C,LoadCell1_Raw,LoadCell2_Raw,Motor,"
              "LoadCell1_New,LoadCell2_New\r\n");

    #if defined(DT_ENABLE_MOTOR)
    VibrationMotor_start(DT_MOTOR_DEFAULT_HZ, DT_MOTOR_DEFAULT_STRENGTH);
    #endif
    last_wake = xTaskGetTickCount();

    for (;;) {
        char row[160];
        size_t len = 0u;
        uint32_t now_ms = elapsedMilliseconds();
        bool accel_ok;

        /* Accelerometer first so its sample time is closest to Time_ms. */
        accel_ok = ADXL345_read(&accel);

        #if defined(DT_ENABLE_MOTOR)
        VibrationMotor_service(now_ms);
        #endif

        /* Polled every row: a ready HX711 is read within 10 ms of finishing
         * a conversion, and a not-ready one costs a single pin read. */
        HX711_poll(&loads);
        DS18B20_get(&temperatures);

        ROW_APPEND(row, len, "%lu", (unsigned long)now_ms);
        if (accel_ok) {
            ROW_APPEND(row, len, ",%.4f,%.4f,%.4f",
                       (double)accel.x_g, (double)accel.y_g, (double)accel.z_g);
        } else {
            ROW_APPEND(row, len, ",,,");
        }
        for (index = 0u; index < 3u; ++index) {
            if (temperatures.valid[index]) {
                ROW_APPEND(row, len, ",%.2f", (double)temperatures.celsius[index]);
            } else {
                ROW_APPEND(row, len, ",");
            }
        }
        for (index = 0u; index < 2u; ++index) {
            if (loads.valid[index]) {
                ROW_APPEND(row, len, ",%ld", (long)loads.raw[index]);
            } else {
                ROW_APPEND(row, len, ",");
            }
        }
        #if defined(DT_ENABLE_MOTOR)
        ROW_APPEND(row, len, ",%u", VibrationMotor_isOn() ? 1u : 0u);
        #else
        ROW_APPEND(row, len, ",0");
        #endif
        ROW_APPEND(row, len, ",%u,%u\r\n",
                   loads.fresh[0] ? 1u : 0u, loads.fresh[1] ? 1u : 0u);
        writeText(row);

        /* vTaskDelayUntil keeps the 10 ms cadence from drifting with the
         * loop body. Needs the 1 kHz FreeRTOS tick from SysConfig. */
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(1000u / DT_OUTPUT_RATE_HZ));
    }
}

void Acquisition_run(Acquisition_Mode mode)
{
    UART2_Params uart_params;
    bool accel_ok;
    bool temps_present[3];

    UART2_Params_init(&uart_params);
    uart_params.baudRate = DT_UART_BAUD;
    uart = UART2_open(CONFIG_UART2_0, &uart_params);
    if (uart == NULL) {
        for (;;) { }
    }

    logLine("# Digital Twin CC3220 DAQ, stream build (ME-2 cc3220_daq + CpE-2 ADXL345 fixes)\r\n");
    logLine("# UART %lu baud, 8-N-1\r\n", (unsigned long)DT_UART_BAUD);

    (void)Timing_init();
    accel_ok = ADXL345_init();
    HX711_init();
    DS18B20_init();
    #if defined(DT_ENABLE_MOTOR)
    VibrationMotor_init();
    #endif

    selfCheck(accel_ok, temps_present);

    if (mode == ACQ_MODE_STREAM) {
        runStream();
    } else {
        runDiagnostics(mode);
    }
}
