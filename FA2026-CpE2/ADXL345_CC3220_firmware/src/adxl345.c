/*
 * adxl345.c
 * See adxl345.h. Register values are from the ADXL345 data sheet (Rev. G).
 * Based on the ME-2 cc3220_daq driver, with two changes that came out of the 10/9 bench failure:
 * the bus scan uses a 1-byte register read (not a zero-length write), and the bus runs at 100 kHz.
 *
 * If the compiler reports "no member named 'targetAddress'" your SDK is older than 6.20:
 * add ADXL345_OLD_I2C_FIELD to the project's predefined symbols.
 */
#include "adxl345.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

#include <ti/drivers/I2C.h>
#include "ti_drivers_config.h"

#ifdef ADXL345_OLD_I2C_FIELD
#define SET_TARGET(t, a) ((t).slaveAddress = (a))
#else
#define SET_TARGET(t, a) ((t).targetAddress = (a))
#endif

#define REG_DEVID        0x00u
#define REG_BW_RATE      0x2Cu
#define REG_POWER_CTL    0x2Du
#define REG_DATA_FORMAT  0x31u
#define REG_DATAX0       0x32u

#define DEVID_VALUE      0xE5u
#define RATE_100_HZ      0x0Au
#define FORMAT_FULL_2G   0x08u
#define MEASURE_ON       0x08u
#define G_PER_COUNT      0.00390625f     /* 1/256 g, full resolution */

static I2C_Handle s_i2c;
static uint8_t    s_addr;
static bool       s_present;

/* ------------------------------------------------------------------ bus helpers */

static bool openBus(void)
{
    I2C_Params params;
    if (s_i2c != NULL) {
        return true;
    }
    I2C_init();
    I2C_Params_init(&params);
    params.bitRate = I2C_100kHz;
    s_i2c = I2C_open(CONFIG_I2C_0, &params);
    return s_i2c != NULL;
}

static bool xfer(uint8_t address, const uint8_t *wr, size_t wn, uint8_t *rd, size_t rn)
{
    I2C_Transaction t;
    memset(&t, 0, sizeof(t));
    SET_TARGET(t, address);
    t.writeBuf = (void *)wr;
    t.writeCount = wn;
    t.readBuf = rd;
    t.readCount = rn;
    return I2C_transfer(s_i2c, &t);
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

/* ------------------------------------------------------------------ driver */

bool ADXL345_init(void)
{
    static const uint8_t candidates[2] = { 0x53u, 0x1Du };
    uint8_t i, id;

    if (!openBus()) {
        return false;
    }
    s_present = false;
    s_addr = 0u;
    for (i = 0u; i < 2u; ++i) {
        id = 0u;
        if (readRegs(candidates[i], REG_DEVID, &id, 1u) && (id == DEVID_VALUE)) {
            s_addr = candidates[i];
            s_present = true;
            break;
        }
    }
    if (!s_present) {
        return false;
    }
    /* Configure first, start measuring last. */
    if (!writeReg(s_addr, REG_BW_RATE, RATE_100_HZ) ||
        !writeReg(s_addr, REG_DATA_FORMAT, FORMAT_FULL_2G) ||
        !writeReg(s_addr, REG_POWER_CTL, MEASURE_ON)) {
        s_present = false;
        return false;
    }
    return true;
}

bool ADXL345_read(ADXL345_Sample *s)
{
    uint8_t d[6];
    if ((s == NULL) || !s_present || !readRegs(s_addr, REG_DATAX0, d, sizeof(d))) {
        return false;
    }
    s->x_raw = (int16_t)((uint16_t)d[0] | ((uint16_t)d[1] << 8));
    s->y_raw = (int16_t)((uint16_t)d[2] | ((uint16_t)d[3] << 8));
    s->z_raw = (int16_t)((uint16_t)d[4] | ((uint16_t)d[5] << 8));
    s->x_g = (float)s->x_raw * G_PER_COUNT;
    s->y_g = (float)s->y_raw * G_PER_COUNT;
    s->z_g = (float)s->z_raw * G_PER_COUNT;
    return true;
}

uint8_t ADXL345_address(void)
{
    return s_present ? s_addr : 0u;
}

void ADXL345_scan(void (*report)(uint8_t address))
{
    uint8_t address, byte;
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

/* ------------------------------------------------------------------ hardware test */

static void say(const char *fmt, ...)
{
    char line[200];
    va_list args;
    va_start(args, fmt);
    (void)vsnprintf(line, sizeof(line), fmt, args);
    va_end(args);
    ADXL345_puts(line);
}

static unsigned s_found;

static void onFound(uint8_t address)
{
    ++s_found;
    say("  device answers at 0x%02X%s\r\n", address,
        (address == 0x53u || address == 0x1Du) ? "   <- ADXL345 address" : "");
}

static void countdown(const char *prompt)
{
    int i;
    say("%s\r\n", prompt);
    for (i = 3; i > 0; --i) {
        say("  starting in %d...\r\n", i);
        sleep(1);
    }
}

void ADXL345_bringup(void)
{
    ADXL345_Sample s;
    unsigned n, tries;
    float mean[3] = { 0.0f, 0.0f, 0.0f }, m2[3] = { 0.0f, 0.0f, 0.0f };
    float v[3], delta, mag, sd[3], peak = 0.0f;
    bool idOk, magOk, stillOk, shakeOk;
    int k;

    say("\r\n=== ADXL345 hardware test ===\r\n");

    say("Step 1: I2C scan (the LaunchPad's own sensors usually show up at 0x18 and 0x49)\r\n");
    s_found = 0u;
    ADXL345_scan(onFound);
    say("  %u device(s) found\r\n", s_found);
    if (s_found == 0u) {
        say("FAIL: nothing answers on the bus. Check the I2C pull-up jumpers and that P01/P02 are not in use "
            "(LED or PWM code on header 9/10).\r\n");
        return;
    }

    say("Step 2: identify the ADXL345\r\n");
    idOk = ADXL345_init();
    if (!idOk) {
        say("FAIL: no ADXL345 (DEVID 0xE5) at 0x53 or 0x1D. Check module power (about 3 V), CS = 3V3, SDO = GND, "
            "SCL -> P01, SDA -> P02, and try swapping SDA/SCL.\r\n");
        return;
    }
    say("  ADXL345 found at 0x%02X, DEVID = 0xE5\r\n", ADXL345_address());

    countdown("Step 3: lay the board FLAT and keep it STILL for 10 s");
    for (n = 0u, tries = 0u; n < 100u && tries < 200u; ++tries) {
        usleep(100000);
        if (!ADXL345_read(&s)) {
            continue;
        }
        v[0] = s.x_g; v[1] = s.y_g; v[2] = s.z_g;
        ++n;
        for (k = 0; k < 3; ++k) {                      /* Welford running mean and variance */
            delta = v[k] - mean[k];
            mean[k] += delta / (float)n;
            m2[k] += delta * (v[k] - mean[k]);
        }
    }
    if (n < 100u) {
        say("FAIL: only %u of 100 readings succeeded (bus drops out; check wiring and pull-ups).\r\n", n);
        return;
    }
    for (k = 0; k < 3; ++k) {
        sd[k] = sqrtf(m2[k] / (float)(n - 1u));
    }
    mag = sqrtf(mean[0] * mean[0] + mean[1] * mean[1] + mean[2] * mean[2]);
    say("  mean  x=%.3f y=%.3f z=%.3f g   |g|=%.3f (expect 1.00)\r\n", mean[0], mean[1], mean[2], mag);
    say("  noise x=%.4f y=%.4f z=%.4f g   (expect under 0.05 when still)\r\n", sd[0], sd[1], sd[2]);
    magOk = fabsf(mag - 1.0f) <= 0.10f;
    stillOk = (sd[0] < 0.05f) && (sd[1] < 0.05f) && (sd[2] < 0.05f);

    countdown("Step 4: SHAKE the board for 5 s");
    for (n = 0u, tries = 0u; n < 50u && tries < 100u; ++tries) {
        usleep(100000);
        if (!ADXL345_read(&s)) {
            continue;
        }
        ++n;
        mag = sqrtf(s.x_g * s.x_g + s.y_g * s.y_g + s.z_g * s.z_g);
        if (fabsf(mag - 1.0f) > peak) {
            peak = fabsf(mag - 1.0f);
        }
    }
    say("  peak deviation from 1 g while shaking: %.3f g (expect over 0.30)\r\n", peak);
    shakeOk = peak > 0.30f;

    say("\r\n--- RESULT ---\r\n");
    say("  identity (DEVID 0xE5): %s\r\n", idOk ? "PASS" : "FAIL");
    say("  gravity about 1 g:      %s\r\n", magOk ? "PASS" : "FAIL (check orientation/scale)");
    say("  noise when still:       %s\r\n", stillOk ? "PASS" : "FAIL (board moved, or noisy wiring)");
    say("  responds to shaking:    %s\r\n", shakeOk ? "PASS" : "FAIL (shake harder)");
    say("ADXL345 hardware test: %s\r\n", (idOk && magOk && stillOk && shakeOk) ? "PASS" : "FAIL");
}
