#include "accelerometer.h"
#include "board_config.h"

#include <string.h>
#include <ti/drivers/I2C.h>
#include "ti_drivers_config.h"

#define ADXL345_DEVID          0x00u
#define ADXL345_BW_RATE        0x2Cu
#define ADXL345_POWER_CTL      0x2Du
#define ADXL345_DATA_FORMAT    0x31u
#define ADXL345_DATAX0         0x32u
#define ADXL345_DEVID_VALUE    0xE5u
#define ADXL345_MEASURE        0x08u
#define ADXL345_FULL_RES_2G    0x08u
#define ADXL345_ODR_100_HZ     0x0Au
#define ADXL345_G_PER_LSB      0.00390625f
#define ADXL345_ADDRESS_COUNT  2u

static I2C_Handle i2c;
static bool present;
static uint8_t activeAddress;
static const uint8_t adxl345Addresses[ADXL345_ADDRESS_COUNT] = { 0x53u, 0x1Du };
static bool probeResponded[ADXL345_ADDRESS_COUNT];
static uint8_t probeDeviceId[ADXL345_ADDRESS_COUNT];

static bool transferTo(uint8_t address, uint8_t reg, void *read_buf,
                       size_t read_count, const void *write_data,
                       size_t write_count)
{
    uint8_t tx[2];
    I2C_Transaction t = {0};

    tx[0] = reg;
    if (write_count != 0u) {
        tx[1] = *(const uint8_t *)write_data;
    }
    t.targetAddress = address;
    t.writeBuf = tx;
    t.writeCount = 1u + write_count;
    t.readBuf = read_buf;
    t.readCount = read_count;
    return I2C_transfer(i2c, &t);
}

static bool transfer(uint8_t reg, void *read_buf, size_t read_count,
                     const void *write_data, size_t write_count)
{
    return transferTo(activeAddress, reg, read_buf, read_count,
                      write_data, write_count);
}

static bool writeRegister(uint8_t reg, uint8_t value)
{
    return transfer(reg, NULL, 0u, &value, 1u);
}

bool ADXL345_init(void)
{
    I2C_Params params;
    uint8_t id;
    uint8_t index;

    I2C_init();
    I2C_Params_init(&params);
    params.bitRate = I2C_400kHz;
    i2c = I2C_open(CONFIG_I2C_0, &params);
    if (i2c == NULL) {
        return false;
    }

    present = false;
    activeAddress = 0u;
    for (index = 0u; index < ADXL345_ADDRESS_COUNT; ++index) {
        id = 0u;
        probeResponded[index] = transferTo(adxl345Addresses[index], ADXL345_DEVID,
                                           &id, sizeof(id), NULL, 0u);
        probeDeviceId[index] = id;
        if (!present && probeResponded[index] && (id == ADXL345_DEVID_VALUE)) {
            activeAddress = adxl345Addresses[index];
            present = true;
        }
    }
    if (!present) {
        return false;
    }

    /* Values are taken from the ADXL345 Rev. G data sheet: measurement,
     * full resolution +/-2g, then 100-Hz output rate. */
    if (!writeRegister(ADXL345_POWER_CTL, ADXL345_MEASURE) ||
        !writeRegister(ADXL345_DATA_FORMAT, ADXL345_FULL_RES_2G) ||
        !writeRegister(ADXL345_BW_RATE, ADXL345_ODR_100_HZ)) {
        present = false;
        return false;
    }
    return true;
}

bool ADXL345_read(ADXL345_Sample *sample)
{
    uint8_t data[6];
    if ((sample == NULL) || !present ||
        !transfer(ADXL345_DATAX0, data, sizeof(data), NULL, 0u)) {
        return false;
    }
    sample->x_raw = (int16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
    sample->y_raw = (int16_t)((uint16_t)data[2] | ((uint16_t)data[3] << 8));
    sample->z_raw = (int16_t)((uint16_t)data[4] | ((uint16_t)data[5] << 8));
    sample->x_g = (float)sample->x_raw * ADXL345_G_PER_LSB;
    sample->y_g = (float)sample->y_raw * ADXL345_G_PER_LSB;
    sample->z_g = (float)sample->z_raw * ADXL345_G_PER_LSB;
    return true;
}

bool ADXL345_isPresent(void)
{
    return present;
}

uint8_t ADXL345_getAddress(void)
{
    return activeAddress;
}

bool ADXL345_probeResponded(uint8_t address, uint8_t *device_id)
{
    uint8_t index;

    for (index = 0u; index < ADXL345_ADDRESS_COUNT; ++index) {
        if (adxl345Addresses[index] == address) {
            if (device_id != NULL) {
                *device_id = probeDeviceId[index];
            }
            return probeResponded[index];
        }
    }
    return false;
}

void ADXL345_scanBus(void (*report)(uint8_t address))
{
    I2C_Transaction t = {0};
    uint8_t byte;
    uint8_t address;
    if ((i2c == NULL) || (report == NULL)) {
        return;
    }
    for (address = 0x08u; address < 0x78u; ++address) {
        t.targetAddress = address;
        t.writeBuf = &byte;
        t.writeCount = 0u;
        t.readBuf = NULL;
        t.readCount = 0u;
        if (I2C_transfer(i2c, &t)) {
            report(address);
        }
    }
}
