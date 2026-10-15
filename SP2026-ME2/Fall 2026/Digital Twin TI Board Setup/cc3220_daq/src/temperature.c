#include "temperature.h"
#include "board_config.h"

#include <ti/drivers/GPIO.h>
#include <ti/drivers/dpl/ClockP.h>
#include "ti_drivers_config.h"

#define OW_RESET_LOW_US       480u
#define OW_RESET_SAMPLE_US     70u
#define OW_RESET_RECOVERY_US  410u
#define OW_SLOT_US             70u
#define OW_WRITE_1_LOW_US       6u
#define OW_WRITE_0_LOW_US      60u
#define OW_READ_LOW_US          6u
#define OW_READ_SAMPLE_US       9u
#define DS18B20_SKIP_ROM       0xCCu
#define DS18B20_CONVERT_T      0x44u
#define DS18B20_READ_SCRATCH   0xBEu

static const uint_least8_t buses[3] = {
    CONFIG_DS18B20_1, CONFIG_DS18B20_2, CONFIG_DS18B20_3
};
static bool converting;
static uint32_t conversion_started_ms;
static uint32_t next_request_ms;

static void releaseBus(uint_least8_t pin)
{
    GPIO_setConfig(pin, GPIO_CFG_INPUT);
}

static void driveLow(uint_least8_t pin)
{
    GPIO_setConfig(pin, GPIO_CFG_OUTPUT | GPIO_CFG_OUT_LOW);
}

static bool reset(uint_least8_t pin)
{
    bool presence;
    driveLow(pin);
    ClockP_usleep(OW_RESET_LOW_US);
    releaseBus(pin);
    ClockP_usleep(OW_RESET_SAMPLE_US);
    presence = (GPIO_read(pin) == 0u);
    ClockP_usleep(OW_RESET_RECOVERY_US);
    return presence;
}

static void writeBit(uint_least8_t pin, bool one)
{
    driveLow(pin);
    ClockP_usleep(one ? OW_WRITE_1_LOW_US : OW_WRITE_0_LOW_US);
    releaseBus(pin);
    ClockP_usleep(one ? (OW_SLOT_US - OW_WRITE_1_LOW_US) :
                        (OW_SLOT_US - OW_WRITE_0_LOW_US));
}

static bool readBit(uint_least8_t pin)
{
    bool bit;
    driveLow(pin);
    ClockP_usleep(OW_READ_LOW_US);
    releaseBus(pin);
    ClockP_usleep(OW_READ_SAMPLE_US);
    bit = (GPIO_read(pin) != 0u);
    ClockP_usleep(OW_SLOT_US - OW_READ_LOW_US - OW_READ_SAMPLE_US);
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
    if (!reset(pin)) {
        return false;
    }
    writeByte(pin, DS18B20_SKIP_ROM);
    writeByte(pin, DS18B20_CONVERT_T);
    return true;
}

static bool readTemperature(uint_least8_t pin, float *celsius)
{
    uint8_t scratch[9];
    uint8_t index;
    int16_t raw;
    if (!reset(pin)) {
        return false;
    }
    writeByte(pin, DS18B20_SKIP_ROM);
    writeByte(pin, DS18B20_READ_SCRATCH);
    for (index = 0u; index < sizeof(scratch); ++index) {
        scratch[index] = readByte(pin);
    }
    if (crc8(scratch, 8u) != scratch[8]) {
        return false;
    }
    raw = (int16_t)((uint16_t)scratch[0] | ((uint16_t)scratch[1] << 8));
    *celsius = (float)raw / 16.0f;
    return (*celsius >= -55.0f) && (*celsius <= 125.0f);
}

void DS18B20_init(void)
{
    uint8_t index;
    GPIO_init();
    for (index = 0u; index < 3u; ++index) {
        releaseBus(buses[index]);
    }
    converting = false;
    next_request_ms = 0u;
}

void DS18B20_service(uint32_t now_ms, DS18B20_Readings *readings)
{
    uint8_t index;
    if (readings == NULL) {
        return;
    }
    if (converting && ((uint32_t)(now_ms - conversion_started_ms) >=
                       DT_DS18B20_CONVERSION_MS)) {
        for (index = 0u; index < 3u; ++index) {
            float value;
            if (readTemperature(buses[index], &value)) {
                readings->celsius[index] = value;
                readings->valid[index] = true;
            } else {
                readings->valid[index] = false;
            }
        }
        converting = false;
    }
    if (!converting && ((int32_t)(now_ms - next_request_ms) >= 0)) {
        for (index = 0u; index < 3u; ++index) {
            (void)startConversion(buses[index]);
        }
        conversion_started_ms = now_ms;
        next_request_ms = now_ms + DT_TEMPERATURE_PERIOD_MS;
        converting = true;
    }
}
