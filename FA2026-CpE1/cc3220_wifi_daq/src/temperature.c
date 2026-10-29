/*
 * Three DS18B20 probes, one 1-Wire bus each (powered mode, 4.7 k pull-up to 3V3):
 *   Temp 1: header 27 / P63   Temp 2: header 28 / P53   Temp 3: header 30 / P50
 *
 * Changes from the ME-2 driver:
 *   - Bit slots use a real microsecond wait (timing.c). The old ClockP_usleep()
 *     calls waited whole 1 ms ticks, so no slot or presence window was met.
 *   - Times inside a slot are measured from the start of the slot, so the time
 *     GPIO_setConfig() takes to switch the pin is absorbed instead of added.
 *   - Interrupts are held off for each slot (at most about 0.6 ms for a reset,
 *     70 us for a bit). Between slots the bus idles high and may wait any time.
 *   - Conversions and reads run in their own low-priority task, so the roughly
 *     20 ms it takes to read three probes never delays a 10 ms sample row.
 */
#include "temperature.h"
#include "board_config.h"
#include "timing.h"

#include <math.h>
#include <pthread.h>
#include <FreeRTOS.h>
#include <task.h>
#include <ti/drivers/GPIO.h>
#include <ti/drivers/dpl/HwiP.h>
#include "ti_drivers_config.h"

#define OW_RESET_LOW_US        500u  /* >= 480 */
#define OW_PRESENCE_SAMPLE_US   70u  /* after release; presence pulse is 60..240 us */
#define OW_RESET_RECOVERY_US   430u  /* rest of the >= 480 us presence window */
#define OW_SLOT_US              70u  /* >= 60 */
#define OW_WRITE_1_LOW_US        6u  /* 1..15 */
#define OW_WRITE_0_LOW_US       64u  /* 60..120 */
#define OW_READ_LOW_US           2u  /* >= 1 */
#define OW_READ_SAMPLE_US       12u  /* before 15 us from the falling edge */
#define OW_READ_SETTLE_US        1u  /* minimum rise time after release */
#define OW_RECOVERY_US           2u  /* >= 1 between slots */

#define DS18B20_SKIP_ROM       0xCCu
#define DS18B20_CONVERT_T      0x44u
#define DS18B20_READ_SCRATCH   0xBEu
#define DS18B20_POWER_ON_C     85.0f

#define TEMPERATURE_TASK_PRIORITY      1  /* below the 100 Hz loop (2) */
#define TEMPERATURE_TASK_STACK_BYTES   1024u

static const uint_least8_t buses[3] = {
    CONFIG_DS18B20_1, CONFIG_DS18B20_2, CONFIG_DS18B20_3
};

static DS18B20_Readings s_latest = { .celsius = { NAN, NAN, NAN } };
static DS18B20_Stats s_stats[3];
static bool s_ever_valid[3];
static volatile uint32_t s_switch_us;

static void releaseBus(uint_least8_t pin)
{
    GPIO_setConfig(pin, GPIO_CFG_INPUT);
}

static void driveLow(uint_least8_t pin)
{
    GPIO_setConfig(pin, GPIO_CFG_OUTPUT | GPIO_CFG_OUT_LOW);
}

static bool resetPulse(uint_least8_t pin)
{
    bool presence;
    uint32_t t;
    uintptr_t key;

    /* An idle bus must be high (pulled up). Low here means a short, a probe
     * wired backwards, or a missing pull-up: report "not present". */
    if (GPIO_read(pin) == 0u) {
        return false;
    }
    key = HwiP_disable();
    driveLow(pin);
    Timing_delayUs(OW_RESET_LOW_US);
    releaseBus(pin);
    t = Timing_now();
    Timing_waitUntil(t, OW_PRESENCE_SAMPLE_US);
    presence = (GPIO_read(pin) == 0u);
    HwiP_restore(key);
    Timing_delayUs(OW_RESET_RECOVERY_US);
    return presence;
}

static void writeBit(uint_least8_t pin, bool one)
{
    uint32_t t;
    uintptr_t key;

    key = HwiP_disable();
    t = Timing_now();
    driveLow(pin);
    Timing_waitUntil(t, one ? OW_WRITE_1_LOW_US : OW_WRITE_0_LOW_US);
    releaseBus(pin);
    Timing_waitUntil(t, OW_SLOT_US);
    HwiP_restore(key);
    Timing_delayUs(OW_RECOVERY_US);
}

static bool readBit(uint_least8_t pin)
{
    bool bit;
    uint32_t t, t_release, t_released;
    uintptr_t key;

    key = HwiP_disable();
    t = Timing_now();
    driveLow(pin);
    Timing_waitUntil(t, OW_READ_LOW_US);
    t_release = Timing_now();
    releaseBus(pin);
    t_released = Timing_now();
    Timing_waitUntil(t, OW_READ_SAMPLE_US);
    Timing_waitUntil(t_released, OW_READ_SETTLE_US);
    bit = (GPIO_read(pin) != 0u);
    Timing_waitUntil(t, OW_SLOT_US);
    HwiP_restore(key);
    {
        uint32_t us = Timing_elapsedUs(t_release, t_released);
        if (us > s_switch_us) {
            s_switch_us = us;
        }
    }
    Timing_delayUs(OW_RECOVERY_US);
    return bit;
}

static void writeByte(uint_least8_t pin, uint8_t byte)
{
    uint8_t bit;

    for (bit = 0u; bit < 8u; ++bit) {
        writeBit(pin, (byte & (1u << bit)) != 0u);
    }
}

static uint8_t readByte(uint_least8_t pin)
{
    uint8_t bit, byte = 0u;

    for (bit = 0u; bit < 8u; ++bit) {
        if (readBit(pin)) {
            byte |= (uint8_t)(1u << bit);
        }
    }
    return byte;
}

/* Dallas/Maxim CRC-8, polynomial x^8 + x^5 + x^4 + 1 (reflected 0x8C). */
static uint8_t crc8(const uint8_t *data, uint8_t len)
{
    uint8_t crc = 0u, byte, bit;

    while (len-- != 0u) {
        byte = *data++;
        for (bit = 0u; bit < 8u; ++bit) {
            uint8_t mix = (crc ^ byte) & 1u;
            crc >>= 1;
            if (mix != 0u) {
                crc ^= 0x8Cu;
            }
            byte >>= 1;
        }
    }
    return crc;
}

static bool startConversion(uint_least8_t pin)
{
    if (!resetPulse(pin)) {
        return false;
    }
    writeByte(pin, DS18B20_SKIP_ROM);
    writeByte(pin, DS18B20_CONVERT_T);
    return true;
}

typedef enum { READ_OK, READ_NO_PRESENCE, READ_CRC_ERROR, READ_OUT_OF_RANGE } ReadResult;

static ReadResult readTemperature(uint_least8_t pin, float *celsius)
{
    uint8_t scratch[9];
    uint8_t index;
    int16_t raw;

    if (!resetPulse(pin)) {
        return READ_NO_PRESENCE;
    }
    writeByte(pin, DS18B20_SKIP_ROM);
    writeByte(pin, DS18B20_READ_SCRATCH);
    for (index = 0u; index < sizeof(scratch); ++index) {
        scratch[index] = readByte(pin);
    }
    /* An all-ones scratchpad (silent bus) fails the CRC. An all-zeros one
     * would pass it, so also require the configuration register's low five
     * bits, which always read 1 on a DS18B20. */
    if ((crc8(scratch, 8u) != scratch[8]) || ((scratch[4] & 0x1Fu) != 0x1Fu)) {
        return READ_CRC_ERROR;
    }
    raw = (int16_t)((uint16_t)scratch[0] | ((uint16_t)scratch[1] << 8));
    *celsius = (float)raw / 16.0f;
    if ((*celsius < -55.0f) || (*celsius > 125.0f)) {
        return READ_OUT_OF_RANGE;
    }
    return READ_OK;
}

static void publish(uint8_t index, bool ok, float celsius)
{
    uintptr_t key = HwiP_disable();
    s_latest.valid[index] = ok;
    s_latest.celsius[index] = ok ? celsius : NAN;
    HwiP_restore(key);
}

static void *temperatureTask(void *arg)
{
    TickType_t last_wake = xTaskGetTickCount();
    bool started[3];
    uint8_t index;

    (void)arg;
    for (;;) {
        for (index = 0u; index < 3u; ++index) {
            started[index] = startConversion(buses[index]);
        }
        vTaskDelay(pdMS_TO_TICKS(DT_DS18B20_CONVERSION_MS));

        for (index = 0u; index < 3u; ++index) {
            float value = NAN;
            ReadResult result = READ_NO_PRESENCE;

            ++s_stats[index].reads;
            if (started[index]) {
                result = readTemperature(buses[index], &value);
            }
            if (result == READ_NO_PRESENCE) {
                ++s_stats[index].no_presence;
            } else if (result == READ_CRC_ERROR) {
                ++s_stats[index].crc_errors;
            }
            /* 85.0 C is the power-on scratchpad value: ignore it until the
             * probe has produced at least one other reading. */
            if ((result == READ_OK) && !s_ever_valid[index] &&
                (value == DS18B20_POWER_ON_C)) {
                result = READ_OUT_OF_RANGE;
            }
            if (result == READ_OK) {
                s_ever_valid[index] = true;
            }
            publish(index, result == READ_OK, value);
        }
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(DT_TEMPERATURE_PERIOD_MS));
    }
    return NULL; /* not reached */
}

void DS18B20_init(void)
{
    uint8_t index;

    GPIO_init();
    for (index = 0u; index < 3u; ++index) {
        releaseBus(buses[index]);
    }
}

bool DS18B20_isPresent(uint8_t index)
{
    return (index < 3u) && resetPulse(buses[index]);
}

bool DS18B20_startTask(void)
{
    pthread_t thread;
    pthread_attr_t attributes;
    struct sched_param priority;

    priority.sched_priority = TEMPERATURE_TASK_PRIORITY;
    if (pthread_attr_init(&attributes) != 0) {
        return false;
    }
    (void)pthread_attr_setschedparam(&attributes, &priority);
    (void)pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_DETACHED);
    (void)pthread_attr_setstacksize(&attributes, TEMPERATURE_TASK_STACK_BYTES);
    return pthread_create(&thread, &attributes, temperatureTask, NULL) == 0;
}

void DS18B20_get(DS18B20_Readings *out)
{
    uintptr_t key;

    if (out == NULL) {
        return;
    }
    key = HwiP_disable();
    *out = s_latest;
    HwiP_restore(key);
}

void DS18B20_getStats(uint8_t index, DS18B20_Stats *out)
{
    uintptr_t key;

    if ((out == NULL) || (index > 2u)) {
        return;
    }
    key = HwiP_disable();
    *out = s_stats[index];
    HwiP_restore(key);
}

uint32_t DS18B20_switchOverheadUs(void)
{
    return s_switch_us;
}
