#include <unistd.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <ti/drivers/PWM.h>
#include <ti/drivers/UART2.h>
#include "ti_drivers_config.h"

#define MOTOR_PERIOD_US  10000

/* === Week 9: Lightweight XOR encryption === */
static const uint8_t ENC_KEY[] = {0x4C, 0x61, 0x62, 0x4B, 0x65, 0x79, 0x31, 0x32};
#define ENC_KEY_LEN 8

static void xor_encrypt(const char *input, uint8_t *output, size_t len) {
    size_t i;
    for(i = 0; i < len; i++) {
        output[i] = (uint8_t)input[i] ^ ENC_KEY[i % ENC_KEY_LEN];
    }
}

static uint32_t g_seq_num = 0;
static uint32_t g_now_ms  = 0;

void *mainThread(void *arg0)
{
    PWM_Handle motorPwm = NULL;
    PWM_Params pwmParams;
    UART2_Handle uart;
    UART2_Params uartParams;
    char plaintext[128];
    uint8_t ciphertext[128];
    char hexbuf[257];
    int len, i;

    UART2_Params_init(&uartParams);
    uartParams.baudRate = 115200;
    uart = UART2_open(CONFIG_UART2_0, &uartParams);
    if (uart == NULL) { while (1) {} }

    UART2_write(uart, "=== Firmware v1.0.0 | Week 9: Encrypted Telemetry ===\r\n", 55, NULL);

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

        /* Build plaintext packet */
        len = snprintf(plaintext, sizeof(plaintext),
            "SEQ=%lu,TS=%lu,DUTY=%d,PERIOD=%d",
            g_seq_num, g_now_ms, duties[idx], MOTOR_PERIOD_US);

        /* XOR encrypt */
        xor_encrypt(plaintext, ciphertext, len);

        /* Convert to hex for UART transmission */
        for(i = 0; i < len; i++) {
            snprintf(hexbuf + (i*2), 3, "%02X", ciphertext[i]);
        }
        hexbuf[len*2] = '\0';

        /* Send encrypted packet */
        char outbuf[300];
        int outlen = snprintf(outbuf, sizeof(outbuf),
            "[ENC] %s\r\n", hexbuf);
        UART2_write(uart, outbuf, outlen, NULL);

        idx = (idx + 1) % 4;
        usleep(3000000);
    }
}
