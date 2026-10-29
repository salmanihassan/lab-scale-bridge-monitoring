/*
 * ADXL345 on the LaunchPad I2C bus (SCL P01 / header 9, SDA P02 / header 10).
 *
 * Same API as the ME-2 cc3220_daq driver, with the changes from CpE-2's
 * FA2026-CpE2/ADXL345_CC3220_firmware/src/adxl345.c, which passed its hardware
 * test on this board on Oct 26 2026:
 *   - bus at 100 kHz instead of 400 kHz;
 *   - the bus scan reads one register instead of a zero-length write
 *     (the CC32xx I2C driver cannot detect devices with a zero-length write);
 *   - the chip is configured first and switched to measure mode last.
 * Register values: ADXL345 data sheet Rev. G. Full resolution, +/-2 g, 100 Hz.
 */
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

static bool openBus(void)
{
    I2C_Params params;

    if (i2c != NULL) {
        return true;
    }
    I2C_init();
    I2C_Params_init(&params);
    params.bitRate = I2C_100kHz;
    i2c = I2C_open(CONFIG_I2C_0, &params);
    return i2c != NULL;
}

static bool xfer(uint8_t address, const uint8_t *wr, size_t wn, uint8_t *rd, size_t rn)
{
    I2C_Transaction t;

    memset(&t, 0, sizeof(t));
    t.targetAddress = address;
    t.writeBuf = (void *)wr;
    t.writeCount = wn;
    t.readBuf = rd;
    t.readCount = rn;
    return I2C_transfer(i2c, &t);
}

static bool readRegs(uint8_t address, uint8_t reg, uint8_t *buf, size_t n)
{
    return xfer(address, &reg, 1u, buf, n);
}

static bool writeReg(uint8_t address, uint8_t reg, uint8_t value)
{
    uint8_t tx[2];

    tx[0] = reg;
    tx[1] = value;
    return xfer(address, tx, 2u, NULL, 0u);
}

bool ADXL345_init(void)
{
    uint8_t id;
    uint8_t index;

    present = false;
    activeAddress = 0u;
    if (!openBus()) {
        return false;
    }

    for (index = 0u; index < ADXL345_ADDRESS_COUNT; ++index) {
        id = 0u;
        probeResponded[index] = readRegs(adxl345Addresses[index], ADXL345_DEVID, &id, 1u);
        probeDeviceId[index] = id;
        if (!present && probeResponded[index] && (id == ADXL345_DEVID_VALUE)) {
            activeAddress = adxl345Addresses[index];
            present = true;
        }
    }
    if (!present) {
        return false;
    }

    /* Configure first, start measuring last. */
    if (!writeReg(activeAddress, ADXL345_BW_RATE, ADXL345_ODR_100_HZ) ||
        !writeReg(activeAddress, ADXL345_DATA_FORMAT, ADXL345_FULL_RES_2G) ||
        !writeReg(activeAddress, ADXL345_POWER_CTL, ADXL345_MEASURE)) {
        present = false;
        return false;
    }
    return true;
}

bool ADXL345_read(ADXL345_Sample *sample)
{
    uint8_t data[6];

    if ((sample == NULL) || !present ||
        !readRegs(activeAddress, ADXL345_DATAX0, data, sizeof(data))) {
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
    return present ? activeAddress : 0u;
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
    uint8_t address;
    uint8_t byte;

    if ((report == NULL) || !openBus()) {
        return;
    }
    for (address = 0x08u; address < 0x78u; ++address) {
        byte = 0u;
        if (readRegs(address, 0x00u, &byte, 1u)) {
            report(address);
        }
    }
}
