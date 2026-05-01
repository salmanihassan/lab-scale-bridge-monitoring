/*
 *  ======== pwmled2.c ========
 *  Vibration Motor PWM Driver
 *  Week 12: Digital Twin Integration — matches teammate MQTT schema v1.0.0
 */
#include <unistd.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>

#include <ti/drivers/PWM.h>
#include <ti/drivers/UART2.h>
#include <ti/drivers/crypto/CryptoCC32XX.h>
#include "hmac_auth.h"
#include "ti_drivers_config.h"

#define MOTOR_PERIOD_US  10000
#define AES_BLOCK_SIZE   16
#define SCHEMA_VERSION   "1.0.0"
#define DEVICE_ID        "CC3220SF_NODE_01"

/* AES-128 key for transport encryption */
static const uint8_t AES_KEY[16] = {
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32,
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32
};

/* Fault injection config */
#define FAULT_DROP_EVERY    15
#define FAULT_CORRUPT_EVERY 10
#define FAULT_DELAY_EVERY   20

static CryptoCC32XX_Handle cryptoHandle = NULL;
static uint32_t g_seq_num = 0;
static uint32_t g_now_ms  = 0;

/* PKCS7 padding */
static size_t pkcs7_pad(const char *input, size_t inLen, uint8_t *output, size_t outMax) {
    size_t padded = ((inLen / AES_BLOCK_SIZE) + 1) * AES_BLOCK_SIZE;
    if (padded > outMax) return 0;
    memcpy(output, input, inLen);
    uint8_t padByte = (uint8_t)(padded - inLen);
    memset(output + inLen, padByte, padded - inLen);
    return padded;
}

/* Simulate temperature and humidity */
static float sim_temperature(void) {
    return 24.0f + ((float)(rand() % 20) / 10.0f);
}
static float sim_humidity(void) {
    return 45.0f + ((float)(rand() % 50) / 10.0f);
}

/* Static buffers */
static char    s_canonical[192];
static char    s_json[384];
static uint8_t s_padded[512];
static uint8_t s_cipher[512];
static char    s_outbuf[1200];
static uint8_t s_digest[SHA256_DIGEST_SIZE];
static char    s_hmac_hex[SHA256_DIGEST_SIZE * 2 + 1];

void *mainThread(void *arg0)
{
    PWM_Handle motorPwm = NULL;
    PWM_Params pwmParams;
    UART2_Handle uart;
    UART2_Params uartParams;
    int outlen, i;
    size_t paddedLen, cipherLen;

    /* Init UART */
    UART2_Params_init(&uartParams);
    uartParams.baudRate = 115200;
    uart = UART2_open(CONFIG_UART2_0, &uartParams);
    if (uart == NULL) { while (1) {} }

    UART2_write(uart, "=== Firmware v1.0.0 | Week 12: Digital Twin Integration ===\r\n", 61, NULL);

    /* Init crypto */
    CryptoCC32XX_init();
    cryptoHandle = CryptoCC32XX_open(CONFIG_Crypto_0, CryptoCC32XX_AES);
    if (cryptoHandle == NULL) {
        UART2_write(uart, "ERROR: Crypto open failed\r\n", 27, NULL);
        while (1) {}
    }

    /* Init PWM */
    PWM_init();
    PWM_Params_init(&pwmParams);
    pwmParams.dutyUnits   = PWM_DUTY_US;
    pwmParams.dutyValue   = 0;
    pwmParams.periodUnits = PWM_PERIOD_US;
    pwmParams.periodValue = MOTOR_PERIOD_US;

    motorPwm = PWM_open(CONFIG_PWM_0, &pwmParams);
    if (motorPwm == NULL) { while (1) {} }
    PWM_start(motorPwm);

    uint16_t duties[] = {7000, 8000, 9000, 10000};
    uint8_t idx = 0;

    while (1)
    {
        g_seq_num++;
        g_now_ms += 3000;

        PWM_setDuty(motorPwm, duties[idx]);

        /* Simulate sensor data */
        float temp     = sim_temperature();
        float humidity = sim_humidity();

        /* === Fault injection === */
        if (g_seq_num % FAULT_DROP_EVERY == 0) {
            UART2_write(uart, "[FAULT] DROP\r\n", 14, NULL);
            idx = (idx + 1) % 4;
            usleep(3000000);
            continue;
        }

        /* === Build canonical string for HMAC === */
        snprintf(s_canonical, sizeof(s_canonical),
            "%s|%lu|%lu|%.1f|%.1f",
            DEVICE_ID, g_seq_num, g_now_ms, temp, humidity);

        /* Corrupt before HMAC if fault */
        if (g_seq_num % FAULT_CORRUPT_EVERY == 0) {
            s_canonical[4] ^= 0xFF;
            UART2_write(uart, "[FAULT] CORRUPT\r\n", 17, NULL);
        }

        /* === Compute HMAC-SHA256 === */
        hmac_sha256(HMAC_KEY, sizeof(HMAC_KEY),
                    (const uint8_t *)s_canonical, strlen(s_canonical),
                    s_digest);
        bytes_to_hex(s_digest, SHA256_DIGEST_SIZE, s_hmac_hex);

        /* === Build JSON payload matching teammate schema === */
        snprintf(s_json, sizeof(s_json),
            "{\"schema_version\":\"%s\","
            "\"device_id\":\"%s\","
            "\"seq_num\":%lu,"
            "\"timestamp_ms\":%lu,"
            "\"telemetry\":{"
                "\"temperature_c\":%.1f,"
                "\"humidity\":%.1f,"
                "\"pwm_duty_us\":%d,"
                "\"pwm_period_us\":%d"
            "},"
            "\"hmac\":\"%s\"}",
            SCHEMA_VERSION, DEVICE_ID,
            g_seq_num, g_now_ms,
            temp, humidity,
            duties[idx], MOTOR_PERIOD_US,
            s_hmac_hex);

        /* === AES-128 encrypt the JSON === */
        size_t jsonLen = strlen(s_json);
        paddedLen = pkcs7_pad(s_json, jsonLen, s_padded, sizeof(s_padded));
        if (paddedLen == 0) {
            idx = (idx + 1) % 4;
            usleep(3000000);
            continue;
        }

        CryptoCC32XX_EncryptParams encParams;
        encParams.aes.keySize = CryptoCC32XX_AES_KEY_SIZE_128BIT;
        encParams.aes.pKey    = (uint32_t *)AES_KEY;
        encParams.aes.pIV     = NULL;

        cipherLen = paddedLen;
        int ret = CryptoCC32XX_encrypt(cryptoHandle,
                                       CryptoCC32XX_AES_ECB,
                                       s_padded, paddedLen,
                                       s_cipher, &cipherLen,
                                       &encParams);
        if (ret != CryptoCC32XX_STATUS_SUCCESS) {
            idx = (idx + 1) % 4;
            usleep(3000000);
            continue;
        }

        /* === Output encrypted packet === */
        outlen = snprintf(s_outbuf, sizeof(s_outbuf), "[AES] ");
        for (i = 0; i < (int)cipherLen; i++) {
            outlen += snprintf(s_outbuf + outlen, 3, "%02X", s_cipher[i]);
        }
        s_outbuf[outlen++] = '\r';
        s_outbuf[outlen++] = '\n';
        UART2_write(uart, s_outbuf, outlen, NULL);

        /* === Timing delay fault === */
        if (g_seq_num % FAULT_DELAY_EVERY == 0) {
            UART2_write(uart, "[FAULT] DELAY\r\n", 15, NULL);
            usleep(2000000);
        }

        idx = (idx + 1) % 4;
        usleep(3000000);
    }
}
