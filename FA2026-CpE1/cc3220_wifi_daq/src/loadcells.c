/*
 * Two HX711 load-cell amplifiers, bit-banged.
 *   Load 1: DOUT header 4 / P03, SCK header 5 / P61
 *   Load 2: DOUT header 7 / P05, SCK header 8 / P62
 *
 * Reading protocol (HX711 data sheet): DOUT low means a conversion is ready.
 * 24 SCK pulses shift the result out MSB first, and a 25th pulse selects
 * channel A, gain 128 for the next conversion. This matches the Arduino HX711
 * library default that ME-2 used, so raw counts are comparable.
 *
 * Change from the ME-2 driver: bit timing uses a real microsecond wait
 * (timing.c) and interrupts are held off during the 25 pulses. The old
 * ClockP_usleep(1) waited a full 1 ms tick, which keeps SCK high long enough
 * (over 60 us) to put the HX711 into power-down in the middle of a read.
 */
#include "loadcells.h"
#include "board_config.h"
#include "timing.h"

#include <stddef.h>
#include <ti/drivers/GPIO.h>
#include <ti/drivers/dpl/ClockP.h>
#include <ti/drivers/dpl/HwiP.h>
#include "ti_drivers_config.h"

typedef struct {
    uint_least8_t dout;
    uint_least8_t clk;
} HX711_Device;

static const HX711_Device devices[2] = {
    { CONFIG_HX711_1_DOUT, CONFIG_HX711_1_CLK },
    { CONFIG_HX711_2_DOUT, CONFIG_HX711_2_CLK }
};

static bool isReady(const HX711_Device *device)
{
    return GPIO_read(device->dout) == 0u;
}

static bool readDevice(const HX711_Device *device, int32_t *result)
{
    uint32_t value = 0u;
    uint32_t t;
    uintptr_t key;
    uint8_t bit;

    if (!isReady(device)) {
        return false;
    }

    /* About 25 x 2 us plus GPIO overhead: well under the 60 us limit even
     * with interrupts off, and no interrupt can stretch an SCK high phase. */
    key = HwiP_disable();
    for (bit = 0u; bit < 25u; ++bit) {
        t = Timing_now();
        GPIO_write(device->clk, 1u);
        Timing_waitUntil(t, DT_HX711_HALF_CYCLE_US);
        if (bit < 24u) {
            value = (value << 1) | (GPIO_read(device->dout) ? 1u : 0u);
        }
        t = Timing_now();
        GPIO_write(device->clk, 0u);
        Timing_waitUntil(t, DT_HX711_HALF_CYCLE_US);
    }
    HwiP_restore(key);

    /* Sign-extend the 24-bit two's complement result. */
    *result = (int32_t)(value ^ 0x00800000u) - (int32_t)0x00800000u;
    return true;
}

void HX711_init(void)
{
    GPIO_init();
    GPIO_setConfig(CONFIG_HX711_1_DOUT, GPIO_CFG_INPUT);
    GPIO_setConfig(CONFIG_HX711_2_DOUT, GPIO_CFG_INPUT);
    /* SCK low keeps (or brings) the HX711 out of power-down. */
    GPIO_setConfig(CONFIG_HX711_1_CLK, GPIO_CFG_OUTPUT | GPIO_CFG_OUT_LOW);
    GPIO_setConfig(CONFIG_HX711_2_CLK, GPIO_CFG_OUTPUT | GPIO_CFG_OUT_LOW);
}

void HX711_poll(HX711_Readings *readings)
{
    uint8_t index;

    if (readings == NULL) {
        return;
    }
    for (index = 0u; index < 2u; ++index) {
        int32_t raw;
        readings->fresh[index] = false;
        if (readDevice(&devices[index], &raw)) {
            readings->raw[index] = raw;
            readings->valid[index] = true;
            readings->fresh[index] = true;
        }
    }
}

bool HX711_waitAndRead(uint8_t index, uint32_t timeout_ms, int32_t *raw)
{
    uint32_t waited_ms;

    if ((index > 1u) || (raw == NULL)) {
        return false;
    }
    for (waited_ms = 0u; waited_ms <= timeout_ms; ++waited_ms) {
        if (readDevice(&devices[index], raw)) {
            return true;
        }
        ClockP_usleep(1000u); /* one scheduler tick */
    }
    return false;
}
