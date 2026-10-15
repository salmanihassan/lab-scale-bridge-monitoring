#include "loadcells.h"
#include "board_config.h"

#include <ti/drivers/GPIO.h>
#include <ti/drivers/dpl/ClockP.h>
#include "ti_drivers_config.h"

typedef struct {
    uint_least8_t dout;
    uint_least8_t clk;
} HX711_Device;

static const HX711_Device devices[2] = {
    { CONFIG_HX711_1_DOUT, CONFIG_HX711_1_CLK },
    { CONFIG_HX711_2_DOUT, CONFIG_HX711_2_CLK }
};

static bool readDevice(const HX711_Device *device, int32_t *result)
{
    uint32_t value = 0u;
    uint8_t bit;

    if (GPIO_read(device->dout) != 0u) {
        return false;
    }
    for (bit = 0u; bit < 24u; ++bit) {
        GPIO_write(device->clk, 1u);
        ClockP_usleep(DT_HX711_HALF_CYCLE_US);
        value = (value << 1) | (GPIO_read(device->dout) ? 1u : 0u);
        GPIO_write(device->clk, 0u);
        ClockP_usleep(DT_HX711_HALF_CYCLE_US);
    }
    /* 25th pulse selects gain=128/channel A for the next conversion. */
    GPIO_write(device->clk, 1u);
    ClockP_usleep(DT_HX711_HALF_CYCLE_US);
    GPIO_write(device->clk, 0u);
    *result = (int32_t)(value ^ 0x00800000u) - (int32_t)0x00800000u;
    return true;
}

void HX711_init(void)
{
    GPIO_init();
    GPIO_setConfig(CONFIG_HX711_1_DOUT, GPIO_CFG_INPUT);
    GPIO_setConfig(CONFIG_HX711_2_DOUT, GPIO_CFG_INPUT);
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
        if (readDevice(&devices[index], &raw)) {
            readings->raw[index] = raw;
            readings->valid[index] = true;
        }
    }
}
