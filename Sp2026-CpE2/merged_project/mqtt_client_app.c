/*
 * Copyright (C) 2016-2021, Texas Instruments Incorporated
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 *
 * *  Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 *
 * *  Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 *
 * *  Neither the name of Texas Instruments Incorporated nor the names of
 *    its contributors may be used to endorse or promote products derived
 *    from this software without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 * AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
 * THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
 * PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
 * CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
 * EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
 * PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
 * OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
 * WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
 * OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE,
 * EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 */

/*****************************************************************************

   Application Name     -   MQTT Client
   Application Overview -   The device is running a MQTT client which is
                           connected to the online broker. Three LEDs on the
                           device can be controlled from a web client by
                           publishing msg on appropriate topics. Similarly,
                           message can be published on pre-configured topics
                           by pressing the switch buttons on the device.

   Application Details  - Refer to 'MQTT Client' README.html

*****************************************************************************/
#include <stdlib.h>
#include <stdio.h>
#include <pthread.h>
#include <unistd.h>
#include <mqueue.h>
#include <assert.h>

#include <ti/drivers/SPI.h>
#include <ti/drivers/GPIO.h>
#include <ti/drivers/Timer.h>
#include <ti/drivers/PWM.h>
#include <ti/drivers/crypto/CryptoCC32XX.h>
#include <ti/drivers/net/wifi/simplelink.h>
#include <ti/drivers/net/wifi/slnetifwifi.h>
#include <ti/drivers/net/wifi/slwificonn.h>
#include <ti/net/slnet.h>
#include <ti/net/slnetif.h>
#include <ti/net/slnetconn.h>
#include <ti/net/mqtt/mqttclient.h>


#include "FreeRTOS.h"
#include "task.h"

#include "ifmod/uart_if.h"
#include "ifmod/wifi_if.h"
#include "ifmod/mqtt_if.h"
#include "ifmod/debug_if.h"
#include "ifmod/ota_if.h"
#include "ifmod/utils_if.h"
#include "ifmod/ota_vendors.h"

#include "ti_drivers_config.h"

#undef DEBUG_IF_NAME
#define DEBUG_IF_NAME       "MQTT_APP"
#undef DEBUG_IF_SEVERITY
#define DEBUG_IF_SEVERITY   E_INFO

extern int32_t ti_net_SlNet_initConfig();

static void StartOTA(char* topic, char* payload, uint8_t qos);
static void StartCloudOTA();
static void StartLocalOTA();
static void StartInternalUpdate();

pthread_t gSlNetConnThread;
bool gNewImageLoaded = false;
#define SLNETCONN_TIMEOUT               10 // 10 Second Timeout
#define SLNETCONN_TASK_STACK_SIZE       (1200)


#define APPLICATION_NAME         "MQTT client"
#define APPLICATION_VERSION      "2.2.0"
/*
 * Schema bumped to v2.0.0 in Week 11: AES-128-GCM (AEAD) replaces the
 * Week 10 AES-128-ECB + inner HMAC-SHA256 stack.  Wire format is now a
 * plaintext outer JSON envelope:
 *   {
 *     "schema_version":"2.0.0",
 *     "device_id":"...","seq_num":N,"timestamp_ms":T,
 *     "ciphertext":"<UPPERCASE_HEX of (IV[12]||CT[N]||TAG[16])>"
 *   }
 * device_id|seq_num|timestamp_ms is bound to the GCM tag as Additional
 * Authenticated Data (AAD), so tampering with any of those outer fields
 * fails GCM verification on the host.  The 16-byte tag also covers the
 * inner ciphertext for telemetry integrity, which makes the legacy
 * inner HMAC-SHA256 layer redundant -- it has been removed.
 */
#define SCHEMA_VERSION           "2.0.0"
#define DEVICE_ID                "CC3220SF_NODE_01"

/* Vibration motor / DTHE / fault-injection constants merged from CpE-1 */
#define MOTOR_PERIOD_US          10000
#define GCM_IV_LEN               12   /* 96-bit standard GCM nonce */
#define GCM_TAG_LEN              16   /* 128-bit authentication tag */
#define FAULT_DROP_EVERY         15
#define FAULT_CORRUPT_EVERY      10
#define FAULT_DELAY_EVERY        20

/* AES-128-GCM key for payload encryption -- must match the AES_KEY
 * constant in broker/host_receiver.py byte-for-byte.
 * (16 bytes = "LabKey12LabKey12") */
static const uint8_t AES_KEY[16] = {
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32,
    0x4C,0x61,0x62,0x4B,0x65,0x79,0x31,0x32
};

#define MQTT_SECURE_CLIENT

#define MQTT_MODULE_TASK_PRIORITY   2
#define MQTT_MODULE_TASK_STACK_SIZE 2048

#define MQTT_WILL_TOPIC             "cc32xx_will_topic"
#define MQTT_WILL_MSG               "will_msg_works"
#define MQTT_WILL_QOS               MQTT_QOS_2
#define MQTT_WILL_RETAIN            false

#define MQTT_CLIENT_PASSWORD        NULL
#define MQTT_CLIENT_USERNAME        NULL
#define MQTT_CLIENT_KEEPALIVE       0
#define MQTT_CLIENT_CLEAN_CONNECT   true
#define MQTT_CLIENT_MQTT_V3_1       true
#define MQTT_CLIENT_BLOCKING_SEND   true

#ifndef MQTT_SECURE_CLIENT
#define MQTT_CONNECTION_FLAGS           MQTTCLIENT_NETCONN_IP4
#define MQTT_CONNECTION_ADDRESS         "10.0.0.123" //"mqtt.eclipse.org"
#define MQTT_CONNECTION_PORT_NUMBER     1883
#else
#define MQTT_CONNECTION_FLAGS           MQTTCLIENT_NETCONN_IP4 | MQTTCLIENT_NETCONN_SEC | MQTTCLIENT_NETCONN_SKIP_CERTIFICATE_CATALOG_VERIFICATION
#define MQTT_CONNECTION_ADDRESS         "10.0.0.123"
#define MQTT_CONNECTION_PORT_NUMBER     8883
#endif

//#define OTA_DEFAULT_METHOD              StartCloudOTA
//#define OTA_DEFAULT_METHOD              StartLocalOTA
//#define OTA_DEFAULT_METHOD              StartInternalUpdate


typedef struct {
    float temperature_c;
    float humidity;
} DHT11_Data_t;

// Global tracking variables for the telemetry packet
static uint32_t g_seq_num = 0;
static uint32_t g_timestamp_ms = 0;

/* === Week 11: vibration motor + AES-128-GCM hardware crypto === */
static CryptoCC32XX_Handle g_cryptoHandle = NULL;
static PWM_Handle          g_motorPwm     = NULL;
static const uint16_t      g_duties[]     = {7000, 8000, 9000, 10000};
static uint8_t             g_dutyIdx      = 0;

/* Scratch buffers (file-scope to keep the publish-thread stack small).
 *
 *   s_innerJson  : plaintext inner JSON (telemetry only) before encrypt.
 *   s_gcmIn      : [AAD || plaintext] handed to CryptoCC32XX_encrypt --
 *                  the driver expects AAD prefixed in the same buffer
 *                  (see CryptoCC32XX.c MAP_AESDataProcessAE call).
 *   s_gcmOut     : ciphertext output buffer (same length as plaintext).
 *   s_iv         : per-publish 96-bit GCM nonce from the NWP TRNG.
 *   s_outbuf     : final outer JSON envelope published over MQTT/TLS. */
static char    s_innerJson[384];
static uint8_t s_gcmIn[512];
static uint8_t s_gcmOut[512];
static uint8_t s_iv[GCM_IV_LEN];
static char    s_aad[96];
static char    s_outbuf[1600];



mqd_t appQueue;
volatile int connected;
volatile int deinit;
Timer_Handle timer0;
volatile int longPress = 0;

/* Client ID                                                                 */
/* If ClientId isn't set, the MAC address of the device will be copied into  */
/* the ClientID parameter.                                                   */
char ClientId[13] = "clientId123";

enum{
    APP_MQTT_PUBLISH,
    APP_MQTT_CON_TOGGLE,
    APP_MQTT_DEINIT,
    APP_BTN_HANDLER,
    APP_OTA_TRIGGER,
};

struct msgQueue
{
    int   event;
    char* payload;
};

MQTT_IF_InitParams_t mqttInitParams =
{
     MQTT_MODULE_TASK_STACK_SIZE,   // stack size for mqtt module - default is 2048
     MQTT_MODULE_TASK_PRIORITY      // thread priority for MQTT   - default is 2
};

MQTTClient_Will mqttWillParams =
{
     MQTT_WILL_TOPIC,    // will topic
     MQTT_WILL_MSG,      // will message
     MQTT_WILL_QOS,      // will QoS
     MQTT_WILL_RETAIN    // retain flag
};

MQTT_IF_ClientParams_t mqttClientParams =
{
     ClientId,                  // client ID
     MQTT_CLIENT_USERNAME,      // user name
     MQTT_CLIENT_PASSWORD,      // password
     MQTT_CLIENT_KEEPALIVE,     // keep-alive time
     MQTT_CLIENT_CLEAN_CONNECT, // clean connect flag
     MQTT_CLIENT_MQTT_V3_1,     // true = 3.1, false = 3.1.1
     MQTT_CLIENT_BLOCKING_SEND, // blocking send flag
     &mqttWillParams            // will parameters
};

#ifndef MQTT_SECURE_CLIENT
MQTTClient_ConnParams mqttConnParams =
{
     MQTT_CONNECTION_FLAGS,         // connection flags
     MQTT_CONNECTION_ADDRESS,       // server address
     MQTT_CONNECTION_PORT_NUMBER,   // port number of MQTT server
     0,                             // method for secure socket
     0,                             // cipher for secure socket
     0,                             // number of files for secure connection
     NULL                           // secure files
};
#else
/*
 * In order to connect to an MQTT broker securely, the MQTTCLIENT_NETCONN_SEC flag,
 * method for secure socket, cipher, secure files, number of secure files must be set
 * and the certificates must be programmed to the file system.
 *
 * The first parameter is a bit mask which configures the server address type and security mode.
 * Server address type: IPv4, IPv6 and URL must be declared with the corresponding flag.
 * All flags can be found in mqttclient.h.
 *
 * The flag MQTTCLIENT_NETCONN_SEC enables the security (TLS) which includes domain name
 * verification and certificate catalog verification. Those verifications can be skipped by
 * adding to the bit mask: MQTTCLIENT_NETCONN_SKIP_DOMAIN_NAME_VERIFICATION and
 * MQTTCLIENT_NETCONN_SKIP_CERTIFICATE_CATALOG_VERIFICATION.
 *
 * Note: The domain name verification requires URL Server address type otherwise, this
 * verification will be disabled.
 *
 * Secure clients require time configuration in order to verify the server certificate validity (date)
 */

/* Day of month (DD format) range 1-31                                       */
#define DAY                      17
/* Month (MM format) in the range of 1-12                                    */
#define MONTH                    4
/* Year (YYYY format)                                                        */
#define YEAR                     2026
/* Hours in the range of 0-23                                                */
#define HOUR                     12
/* Minutes in the range of 0-59                                              */
#define MINUTES                  00
/* Seconds in the range of 0-59                                              */
#define SEC                      00

char *MQTTClient_secureFiles[1] = {"ca-cert.pem"};

MQTTClient_ConnParams mqttConnParams =
{
    MQTT_CONNECTION_FLAGS,                  // connection flags
    MQTT_CONNECTION_ADDRESS,                // server address
    MQTT_CONNECTION_PORT_NUMBER,            // port number of MQTT server
    SLNETSOCK_SEC_METHOD_TLSV1_2,            // method for secure socket
    SLNETSOCK_SEC_CIPHER_FULL_LIST,         // cipher for secure socket
    1,                                      // number of files for secure connection
    MQTTClient_secureFiles                  // secure files
};

void setTime() {

    SlDateTime_t dateTime = {0};
    dateTime.tm_day = (uint32_t)DAY;
    dateTime.tm_mon = (uint32_t)MONTH;
    dateTime.tm_year = (uint32_t)YEAR;
    dateTime.tm_hour = (uint32_t)HOUR;
    dateTime.tm_min = (uint32_t)MINUTES;
    dateTime.tm_sec = (uint32_t)SEC;
    sl_DeviceSet(SL_DEVICE_GENERAL, SL_DEVICE_GENERAL_DATE_TIME,
                 sizeof(SlDateTime_t), (uint8_t *)(&dateTime));
}
#endif


// ====================================================================
// --- SENSOR HARDWARE ABSTRACTION LAYER (HAL) ---
// ====================================================================
/* * The Sensor Stub:
 * Right now this simulates realistic fluctuating sensor data.
 * Later, you will replace the contents of this function with
 * your actual DHT11 GPIO read logic.
 */
int32_t DHT11_Read(DHT11_Data_t *sensorData) {
    // Generate slight random fluctuations to simulate real-world physics
    sensorData->temperature_c = 24.0f + ((float)(rand() % 20) / 10.0f);
    sensorData->humidity = 45.0f + ((float)(rand() % 50) / 10.0f);
    return 0; // Return 0 on successful read
}

/* * Pull `len` cryptographically-secure random bytes from the CC3220SF
 * NWP True Random Number Generator via sl_NetUtilGet().  Per the TI
 * SimpleLink Wi-Fi host driver API, SL_NETUTIL_TRUE_RANDOM (option 3 in
 * netutil.h) is sourced from the NWP hardware TRNG and is the same
 * entropy source that mbedtls_hardware_poll() uses inside the SDK.
 *
 * Requires the NWP to be powered up, i.e. callable only after Wi-Fi
 * has been brought up by WIFI_IF_init() / SlNetConn_start().
 *
 * Returns 0 on success, non-zero on failure.
 */
static int gcm_get_random(uint8_t *out, uint16_t len)
{
    uint16_t lenIO = len;
    int16_t  ret   = sl_NetUtilGet((uint16_t)SL_NETUTIL_TRUE_RANDOM,
                                   (uint32_t)0,
                                   out, &lenIO);
    if (ret != 0 || lenIO != len) {
        return -1;
    }
    return 0;
}

/* * Hex-encode `in` of length `inLen` into `out` as uppercase ASCII.
 * `out` must hold at least 2*inLen + 1 bytes (NUL terminator included).
 * Returns the number of chars written (excluding NUL), or 0 on overflow.
 */
static int bytes_to_upper_hex(const uint8_t *in, size_t inLen,
                              char *out, size_t outMax)
{
    static const char digits[] = "0123456789ABCDEF";
    if (outMax < (inLen * 2u + 1u)) return 0;
    size_t i;
    for (i = 0; i < inLen; i++) {
        out[2*i]     = digits[(in[i] >> 4) & 0x0F];
        out[2*i + 1] = digits[in[i] & 0x0F];
    }
    out[2*inLen] = '\0';
    return (int)(2 * inLen);
}

/* * AES-128-GCM encrypt the inner JSON payload + emit the outer envelope.
 *
 * Pipeline:
 *   1. Pull a fresh 12-byte GCM nonce from the NWP TRNG.
 *   2. Build the AAD canonical string "<device>|<seq>|<ts>" (ASCII).
 *   3. Concatenate [AAD || plaintext] into s_gcmIn -- the CryptoCC32XX
 *      driver consumes the AAD from the front of the input buffer
 *      (see MAP_AESDataProcessAE() call inside the SDK driver).
 *   4. CryptoCC32XX_encrypt(... AES_GCM ...) writes ciphertext to
 *      s_gcmOut and the 16-byte tag to params.aes.aadParams.tag.
 *   5. Hex-encode (IV || ciphertext || tag) and wrap into the outer
 *      JSON envelope written to outBuf.
 *
 * Returns the length of the outer JSON written (excluding NUL), or 0
 * on any error (TRNG failure, buffer overflow, hardware AES failure).
 */
static int gcm_encrypt_envelope(const char *plaintext, size_t plainLen,
                                uint32_t seq, uint32_t ts,
                                char *outBuf, size_t outBufSize)
{
    if (plaintext == NULL || outBuf == NULL || outBufSize < 1) return 0;

    if (gcm_get_random(s_iv, GCM_IV_LEN) != 0) {
        LOG_ERROR("TRNG failed -- cannot derive GCM nonce");
        return 0;
    }

    int aadLen = snprintf(s_aad, sizeof(s_aad),
                          "%s|%lu|%lu",
                          DEVICE_ID,
                          (unsigned long)seq,
                          (unsigned long)ts);
    if (aadLen <= 0 || (size_t)aadLen >= sizeof(s_aad)) return 0;

    if ((size_t)aadLen + plainLen > sizeof(s_gcmIn)) return 0;
    memcpy(s_gcmIn, s_aad, (size_t)aadLen);
    memcpy(s_gcmIn + aadLen, plaintext, plainLen);

    CryptoCC32XX_EncryptParams encParams;
    memset(&encParams, 0, sizeof(encParams));
    encParams.aes.keySize           = CryptoCC32XX_AES_KEY_SIZE_128BIT;
    encParams.aes.pKey              = AES_KEY;
    encParams.aes.pIV               = s_iv;
    encParams.aes.aadParams.input.len = (size_t)aadLen;

    size_t cipherLen = plainLen;
    int ret = CryptoCC32XX_encrypt(g_cryptoHandle,
                                   CryptoCC32XX_AES_GCM,
                                   s_gcmIn, plainLen,
                                   s_gcmOut, &cipherLen,
                                   &encParams);
    if (ret != CryptoCC32XX_STATUS_SUCCESS || cipherLen != plainLen) {
        LOG_ERROR("CryptoCC32XX_encrypt(AES_GCM) failed (%d)", ret);
        return 0;
    }

    /* Hex-encode IV || ciphertext || tag into a stack-friendly buffer
     * inside s_outbuf so we can splice it into the outer envelope. */
    size_t blobLen = (size_t)GCM_IV_LEN + cipherLen + (size_t)GCM_TAG_LEN;
    if (blobLen * 2u + 1u > sizeof(s_gcmIn)) return 0;
    /* Reuse s_gcmIn as a scratch hex buffer now that the encrypt is
     * done -- saves another file-scope buffer. */
    char *hexBuf = (char *)s_gcmIn;
    int p = 0;
    p += bytes_to_upper_hex(s_iv, GCM_IV_LEN,
                            hexBuf + p, sizeof(s_gcmIn) - (size_t)p);
    if (p == 0) return 0;
    int q = bytes_to_upper_hex(s_gcmOut, cipherLen,
                               hexBuf + p, sizeof(s_gcmIn) - (size_t)p);
    if (q == 0) return 0;
    p += q;
    q = bytes_to_upper_hex(encParams.aes.aadParams.tag, GCM_TAG_LEN,
                           hexBuf + p, sizeof(s_gcmIn) - (size_t)p);
    if (q == 0) return 0;
    p += q;

    int outLen = snprintf(outBuf, outBufSize,
        "{\"schema_version\":\"" SCHEMA_VERSION "\","
        "\"device_id\":\"" DEVICE_ID "\","
        "\"seq_num\":%lu,\"timestamp_ms\":%lu,"
        "\"ciphertext\":\"%s\"}",
        (unsigned long)seq,
        (unsigned long)ts,
        hexBuf);

    if (outLen <= 0 || (size_t)outLen >= outBufSize) return 0;
    return outLen;
}

/* * The Inner Payload Formatter:
 * Builds the *inner* JSON that gets handed to gcm_encrypt_envelope().
 *
 * Schema v2.0.0 (Week 11): inner JSON only carries telemetry fields.
 * device_id / seq_num / timestamp_ms move to the *outer* envelope and
 * are bound to the GCM tag as Additional Authenticated Data (AAD), so
 * the legacy inner HMAC is no longer required.  The CORRUPT fault still
 * flips a byte of the inner JSON pre-encrypt so the host sees an inner
 * parse failure even though the GCM tag itself is valid.
 *
 * Returns a "fault" code so the caller knows whether to inject CORRUPT
 * or DROP (skip transmit entirely):
 *   0 = normal, 1 = CORRUPT, 2 = DROP
 */
#define FAULT_NONE     0
#define FAULT_CORRUPT  1
#define FAULT_DROP     2

static int buildTelemetryPayload(char *payloadBuffer, size_t bufferSize,
                                 DHT11_Data_t *sensorData,
                                 uint16_t duty_us, uint16_t period_us)
{
    int fault = FAULT_NONE;

    g_seq_num++;
    g_timestamp_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);

    /* Fault: DROP -- skip transmit entirely so the host sees a seq gap. */
    if ((g_seq_num % FAULT_DROP_EVERY) == 0) {
        return FAULT_DROP;
    }

    int len = snprintf(payloadBuffer, bufferSize,
        "{\"schema_version\":\"" SCHEMA_VERSION "\","
        "\"telemetry\":{"
            "\"temperature_c\":%.1f,\"humidity\":%.1f,"
            "\"pwm_duty_us\":%u,\"pwm_period_us\":%u"
        "}}",
        sensorData->temperature_c, sensorData->humidity,
        (unsigned)duty_us, (unsigned)period_us);
    if (len <= 0 || (size_t)len >= bufferSize) {
        return FAULT_DROP;
    }

    /* Fault: CORRUPT -- flip a byte of the inner JSON before encryption.
     * GCM still produces a valid tag over the corrupted bytes, so the
     * host decrypt succeeds; the inner JSON.parse() fails and the host
     * logs a [JSON FAIL] row equivalent to the v1.x [HMAC FAIL]. */
    if ((g_seq_num % FAULT_CORRUPT_EVERY) == 0) {
        if (len > 4) {
            payloadBuffer[4] ^= 0xFF;
        }
        fault = FAULT_CORRUPT;
    }

    return fault;
}

//*****************************************************************************
//
//! \brief The Function Handles the Fatal errors
//!
//! \param[in]  slFatalErrorEvent - Pointer to Fatal Error Event info
//!
//! \return None
//!
//*****************************************************************************

void SimpleLinkSockEventHandler(SlSockEvent_t *pSock)
{
    if ( pSock->Event == SL_SOCKET_ASYNC_EVENT)
    {
        switch (pSock->SocketAsyncEvent.SockAsyncData.Type)
        {
        case SL_SSL_NOTIFICATION_WRONG_ROOT_CA:
            /* on socket error Restart OTA */
            LOG_INFO("SL_SOCKET_ASYNC_EVENT: ERROR - WRONG ROOT CA");
            LOG_INFO("Please install the following Root Certificate:");
            LOG_INFO(" %s\n\r", pSock->SocketAsyncEvent.SockAsyncData.pExtraInfo);
            break;
        default:
            /* on socket error Restart OTA */
            LOG_INFO("SL_SOCKET_ASYNC_EVENT socket event %d", pSock->Event);
        }
    }
}

void SimpleLinkHttpServerEventHandler(
        SlNetAppHttpServerEvent_t *pHttpEvent,
        SlNetAppHttpServerResponse_t *
        pHttpResponse)
{
    /* Unused in this application */
}

void SimpleLinkNetAppRequestMemFreeEventHandler(_u8 *buffer)
{
    /* Unused in this application */
}

//*****************************************************************************
//!
//! Set the ClientId with its own mac address
//! This routine converts the mac address which is given
//! by an integer type variable in hexadecimal base to ASCII
//! representation, and copies it into the ClientId parameter.
//!
//! \param  macAddress  -   Points to string Hex.
//!
//! \return void.
//!
//*****************************************************************************
int32_t SetClientIdNamefromMacAddress()
{
    int32_t ret = 0;
    uint8_t Client_Mac_Name[2];
    uint8_t Index;
    uint16_t macAddressLen = SL_MAC_ADDR_LEN;
    uint8_t macAddress[SL_MAC_ADDR_LEN];

    /*Get the device Mac address */
    ret = sl_NetCfgGet(SL_NETCFG_MAC_ADDRESS_GET, 0, &macAddressLen,
                       &macAddress[0]);

    /*When ClientID isn't set, use the mac address as ClientID               */
    if(ClientId[0] == '\0')
    {
        /*6 bytes is the length of the mac address                           */
        for(Index = 0; Index < SL_MAC_ADDR_LEN; Index++)
        {
            /*Each mac address byte contains two hexadecimal characters      */
            /*Copy the 4 MSB - the most significant character                */
            Client_Mac_Name[0] = (macAddress[Index] >> 4) & 0xf;
            /*Copy the 4 LSB - the least significant character               */
            Client_Mac_Name[1] = macAddress[Index] & 0xf;

            if(Client_Mac_Name[0] > 9)
            {
                /*Converts and copies from number that is greater than 9 in  */
                /*hexadecimal representation (a to f) into ascii character   */
                ClientId[2 * Index] = Client_Mac_Name[0] + 'a' - 10;
            }
            else
            {
                /*Converts and copies from number 0 - 9 in hexadecimal       */
                /*representation into ascii character                        */
                ClientId[2 * Index] = Client_Mac_Name[0] + '0';
            }
            if(Client_Mac_Name[1] > 9)
            {
                /*Converts and copies from number that is greater than 9 in  */
                /*hexadecimal representation (a to f) into ascii character   */
                ClientId[2 * Index + 1] = Client_Mac_Name[1] + 'a' - 10;
            }
            else
            {
                /*Converts and copies from number 0 - 9 in hexadecimal       */
                /*representation into ascii character                        */
                ClientId[2 * Index + 1] = Client_Mac_Name[1] + '0';
            }
        }
    }
    return(ret);
}

void timerCallback(Timer_Handle myHandle)
{
    longPress = 1;
}

// this timer callback toggles the LED once per second until the device connects to an AP
void timerLEDCallback(Timer_Handle myHandle)
{
    GPIO_toggle(CONFIG_GPIO_LED_0);
}

void pushButtonPublishHandler(uint_least8_t index)
{
    int ret;
    struct msgQueue queueElement;

    GPIO_disableInt(CONFIG_GPIO_BUTTON_0);

    queueElement.event = APP_MQTT_PUBLISH;
    ret = mq_send(appQueue, (const char*)&queueElement, sizeof(struct msgQueue), 0);
    if(ret < 0){
        LOG_ERROR("msg queue send error %d", ret);
    }
    queueElement.event = APP_OTA_TRIGGER;
    ret = mq_send(appQueue, (const char*)&queueElement, sizeof(struct msgQueue), 0);
    if(ret < 0){
        LOG_ERROR("msg queue send error %d", ret);
    }
}

void pushButtonConnectionHandler(uint_least8_t index)
{
    int ret;
    struct msgQueue queueElement;

    GPIO_disableInt(CONFIG_GPIO_BUTTON_1);

    ret = Timer_start(timer0);
    if(ret < 0){
        LOG_ERROR("failed to start the timer\r\n");
    }

    queueElement.event = APP_BTN_HANDLER;

    ret = mq_send(appQueue, (const char*)&queueElement, sizeof(struct msgQueue), 0);
    if(ret < 0){
        LOG_ERROR("msg queue send error %d", ret);
    }
}

int detectLongPress(){

    int buttonPressed;

    do{
        buttonPressed = GPIO_read(CONFIG_GPIO_BUTTON_1);
    }while(buttonPressed && !longPress);

    // disabling the timer in case the callback has not yet triggered to avoid updating longPress
    Timer_stop(timer0);

    if(longPress == 1){
        longPress = 0;
        return 1;
    }
    else{
        return 0;
    }
}


void MQTT_EventCallback(int32_t event){

    struct msgQueue queueElement;

    switch(event){

        case MQTT_EVENT_CONNACK:
        {
            deinit = 0;
            connected = 1;
            LOG_INFO("MQTT_EVENT_CONNACK\r\n");
            GPIO_clearInt(CONFIG_GPIO_BUTTON_1);
            GPIO_enableInt(CONFIG_GPIO_BUTTON_1);
            break;
        }

        case MQTT_EVENT_SUBACK:
        {
            LOG_INFO("MQTT_EVENT_SUBACK\r\n");
            break;
        }

        case MQTT_EVENT_PUBACK:
        {
            LOG_INFO("MQTT_EVENT_PUBACK\r\n");
            break;
        }

        case MQTT_EVENT_UNSUBACK:
        {
            LOG_INFO("MQTT_EVENT_UNSUBACK\r\n");
            break;
        }

        case MQTT_EVENT_CLIENT_DISCONNECT:
        {
            connected = 0;
            LOG_INFO("MQTT_EVENT_CLIENT_DISCONNECT\r\n");
            if(deinit == 0){
                GPIO_clearInt(CONFIG_GPIO_BUTTON_1);
                GPIO_enableInt(CONFIG_GPIO_BUTTON_1);
            }
            break;
        }

        case MQTT_EVENT_SERVER_DISCONNECT:
        {
            connected = 0;

            LOG_INFO("MQTT_EVENT_SERVER_DISCONNECT\r\n");

            queueElement.event = APP_MQTT_CON_TOGGLE;
            int res = mq_send(appQueue, (const char*)&queueElement, sizeof(struct msgQueue), 0);
            if(res < 0){
                LOG_ERROR("msg queue send error %d", res);
            }
            break;
        }

        case MQTT_EVENT_DESTROY:
        {
            LOG_INFO("MQTT_EVENT_DESTROY\r\n");
            break;
        }
    }
}

/*
 * Subscribe topic callbacks
 * Topic and payload data is deleted after topic callbacks return.
 * User must copy the topic or payload data if it needs to be saved.
 */
void BrokerCB(char* topic, char* payload, uint8_t qos){
    LOG_INFO("TOPIC: %s PAYLOAD: %s QOS: %d\r\n", topic, payload, qos);
}

void ToggleLED1CB(char* topic, char* payload, uint8_t qos){
    GPIO_toggle(CONFIG_GPIO_LED_0);
    LOG_INFO("TOPIC: %s PAYLOAD: %s QOS: %d\r\n", topic, payload, qos);
}

/* ToggleLED2CB / ToggleLED3CB removed in Week 10 merge: CONFIG_GPIO_LED_1
 * and CONFIG_GPIO_LED_2 no longer exist (pins reassigned to CONFIG_PWM_0). */

int32_t DisplayAppBanner(char* appName, char* appVersion){

    int32_t ret = 0;
    uint8_t macAddress[SL_MAC_ADDR_LEN];
    uint16_t macAddressLen = SL_MAC_ADDR_LEN;
    uint16_t ConfigSize = 0;
    uint8_t ConfigOpt = SL_DEVICE_GENERAL_VERSION;
    SlDeviceVersion_t ver = {0};

    ConfigSize = sizeof(SlDeviceVersion_t);

    // get the device version info and MAC address
    ret = sl_DeviceGet(SL_DEVICE_GENERAL, &ConfigOpt, &ConfigSize, (uint8_t*)(&ver));
    ret |= (int32_t)sl_NetCfgGet(SL_NETCFG_MAC_ADDRESS_GET, 0, &macAddressLen, &macAddress[0]);

    UART_PRINT("\n\r\t============================================\n\r");
    UART_PRINT("\t   %s Example Ver: %s",appName, appVersion);
    UART_PRINT("\n\r\t============================================\n\r\n\r");

    UART_PRINT("\t CHIP: 0x%x\n\r",ver.ChipId);
    UART_PRINT("\t MAC:  %d.%d.%d.%d\n\r",ver.FwVersion[0],ver.FwVersion[1],
               ver.FwVersion[2],
               ver.FwVersion[3]);
    UART_PRINT("\t PHY:  %d.%d.%d.%d\n\r",ver.PhyVersion[0],ver.PhyVersion[1],
               ver.PhyVersion[2],
               ver.PhyVersion[3]);
    UART_PRINT("\t NWP:  %d.%d.%d.%d\n\r",ver.NwpVersion[0],ver.NwpVersion[1],
               ver.NwpVersion[2],
               ver.NwpVersion[3]);
    UART_PRINT("\t ROM:  %d\n\r",ver.RomVersion);
    UART_PRINT("\t HOST: %s\n\r", SL_DRIVER_VERSION);
    UART_PRINT("\t MAC address: %02x:%02x:%02x:%02x:%02x:%02x\r\n", macAddress[0],
               macAddress[1], macAddress[2], macAddress[3], macAddress[4],
               macAddress[5]);
    UART_PRINT("\n\r\t============================================\n\r");

    return(ret);
}

//*****************************************************************************
//
//! \brief  SlWifiConn Event Handler
//!
//*****************************************************************************
static void SlNetConnEventHandler(uint32_t ifID, SlNetConnStatus_e netStatus, void* data)
{
    switch(netStatus)
    {
    case SLNETCONN_STATUS_CONNECTED_MAC:
        UART_PRINT("[SlNetConnEventHandler] I/F %d - CONNECTED (MAC LEVEL)!\n\r", ifID);
    break;
    case SLNETCONN_STATUS_CONNECTED_IP:
        UART_PRINT("[SlNetConnEventHandler] I/F %d - CONNECTED (IP LEVEL)!\n\r", ifID);
    break;
    case SLNETCONN_STATUS_CONNECTED_INTERNET:
        UART_PRINT("[SlNetConnEventHandler] I/F %d - CONNECTED (INTERNET LEVEL)!\n\r", ifID);
    break;
    case SLNETCONN_STATUS_WAITING_FOR_CONNECTION:
    case SLNETCONN_STATUS_DISCONNECTED:
        UART_PRINT("[SlNetConnEventHandler] I/F %d - DISCONNECTED!\n\r", ifID);
    break;
    default:
        UART_PRINT("[SlNetConnEventHandler] I/F %d - UNKNOWN STATUS\n\r", ifID);
    break;
    }
}

#if OTA_SUPPORT

void OtaCallback(otaNotif_e notification, OtaEventParam_u *pParams)
{

    SlNetConnStatus_e status;
    int retVal;

    switch(notification)
    {
    case OTA_NOTIF_IMAGE_PENDING_COMMIT:
         LOG_INFO("OTA_NOTIF_IMAGE_PENDING_COMMIT");
         retVal = SlNetConn_getStatus(true, &status);
         if (retVal == 0 && status == SLNETCONN_STATUS_CONNECTED_INTERNET)
         {
             OTA_IF_commit();
         }
         else
         {
             OTA_IF_rollback();
             LOG_ERROR("Error Testing the new version - reverting to old version (%d)", retVal);
         }
         break;
    case OTA_NOTIF_IMAGE_DOWNLOADED:
    {
        struct msgQueue queueElement;
        gNewImageLoaded = true;
        LOG_INFO("OTA_NOTIF_IMAGE_DOWNLOADED");
        /* Closing the MQTT - will take the main thread out of its execution loop, then
         * the gNewImageLoaded will mark that new Update is ready for installation
         * (which involves MCU Reset)
         */
        queueElement.event = APP_MQTT_DEINIT;
        retVal = mq_send(appQueue, (const char*)&queueElement, sizeof(struct msgQueue), 0);
        assert (retVal == 0);
        break;
    }
    case OTA_NOTIF_GETLINK_ERROR:
        LOG_ERROR("OTA_NOTIF_GETLINK_ERROR (%d)", pParams->err.errorCode);
        break;
    case OTA_NOTIF_DOWNLOAD_ERROR:
        LOG_ERROR("OTA_NOTIF_DOWNLOAD_ERROR (%d)", pParams->err.errorCode);
        break;
    case OTA_NOTIF_INSTALL_ERROR:
        LOG_ERROR("OTA_NOTIF_INSTALL_ERROR (%d)", pParams->err.errorCode);
        break;
   case OTA_NOTIF_COMMIT_ERROR:
         LOG_ERROR("OTA_NOTIF_COMMIT_ERROR {%d)", pParams->err.errorCode);
         break;
    default:
        LOG_INFO("OTA_NOTIF not handled Id %d", notification);
        break;
    }
}
#endif

static void StartCloudOTA()
{
#if CLOUD_OTA_SUPPORT
    LOG_INFO("Starting Cloud OTA");
    OTA_IF_downloadImageByCloudVendor(OTA_GITHUB_getDownloadLink, OTA_DROPBOX_getDownloadLink, 0);
#else
    LOG_WARNING("Cloud OTA is not enabled. Please enable CLOUD_OTA_SUPPORT macro in ota_settings.h");
#endif
}

static void StartLocalOTA()
{
#if LOCAL_OTA_SUPPORT
    LOG_INFO("Starting Local OTA");
    OTA_IF_uploadImage(0); // use default HTTP port and no security
#else
    LOG_WARNING("Local OTA is not enabled. Enable LOCAL_OTA_SUPPORT macro. Please enable CLOUD_OTA_SUPPORT macro in ota_settings.h");
#endif
}

static void StartInternalUpdate()
{
#if INTERNAL_UPDATE_SUPPORT
    TarFileParams_t tarFileParams;

    tarFileParams.pPath =  "/otaImages/cc3235sf.tar";
    tarFileParams.token = 0;
    tarFileParams.pVersion = NULL;
    LOG_INFO("Starting Internal Update");
    OTA_IF_readImage(&tarFileParams, 0); // use default HTTP port and no security
#else
    LOG_WARNING("Internal Update is not enabled. Please enable INTERNAL_UPDATE_SUPPORT macro in ota_settings.h");
#endif
}

static void StartOTA(char* topic, char* payload, uint8_t qos)
{
    if(topic != NULL)
    {
        LOG_INFO("Trigger OTA...(MQTT:: %s)", payload);
        if(strcmp(payload, "cloud") == 0)
        {
            StartCloudOTA();
        }
        else if(strcmp(payload, "local") == 0)
        {
            StartLocalOTA();
        }
        else if(strcmp(payload, "internal") == 0)
        {
            StartInternalUpdate();
        }
        else
        {
            /* Unknown payload - mark as NULL to use the default method */
            LOG_WARNING("Unknown payload - using the default OTA method");
            topic = NULL;
        }
    }
    else
    {
        LOG_INFO("Trigger OTA...(button press)");
    }
    /* The following is the default for button press or unknown MQTT payload */
    if(topic == NULL)
    {
#ifdef OTA_DEFAULT_METHOD
        OTA_DEFAULT_METHOD();
#else
        LOG_WARNING("No default OTA method is defined.");
        LOG_WARNING("Set OTA_DEFAULT_METHOD to one of: StartCloudOTA / StartLocalOTA / StartInternalUpdate");

#endif
    }
}

void mainThread(void * args)
{
    int32_t ret;
    int32_t conn_Failure = 0;
    mq_attr attr;
    Timer_Params params;
    struct msgQueue queueElement;
    MQTTClient_Handle mqttClientHandle = NULL;

    InitTerm();

    GPIO_init();
    SPI_init();
    Timer_init();
    PWM_init();
    CryptoCC32XX_init();

    GPIO_setCallback(CONFIG_GPIO_BUTTON_0, pushButtonPublishHandler);
    GPIO_setCallback(CONFIG_GPIO_BUTTON_1, pushButtonConnectionHandler);

    GPIO_write(CONFIG_GPIO_LED_0, CONFIG_GPIO_LED_OFF);

    /* === Week 11: open DTHE hardware crypto handle for AES-128-GCM === */
    g_cryptoHandle = CryptoCC32XX_open(CONFIG_Crypto_0, CryptoCC32XX_AES);
    if (g_cryptoHandle == NULL) {
        LOG_ERROR("CryptoCC32XX_open failed -- AES-GCM unavailable");
        while (1) {}
    }

    /* === Week 10 merge: bring up vibration motor PWM === */
    {
        PWM_Params pwmParams;
        PWM_Params_init(&pwmParams);
        pwmParams.dutyUnits   = PWM_DUTY_US;
        pwmParams.dutyValue   = 0;
        pwmParams.periodUnits = PWM_PERIOD_US;
        pwmParams.periodValue = MOTOR_PERIOD_US;
        g_motorPwm = PWM_open(CONFIG_PWM_0, &pwmParams);
        if (g_motorPwm == NULL) {
            LOG_ERROR("PWM_open failed -- motor unavailable");
            while (1) {}
        }
        PWM_start(g_motorPwm);
    }

    // configuring the timer to toggle an LED until the AP is connected
    Timer_Params_init(&params);
    params.period = 1500000;
    params.periodUnits = Timer_PERIOD_US;
    params.timerMode = Timer_ONESHOT_CALLBACK;
    params.timerCallback = (Timer_CallBackFxn)timerCallback;

    timer0 = Timer_open(CONFIG_TIMER_0, &params);
    if (timer0 == NULL) {
        LOG_ERROR("failed to initialize timer\r\n");
        while(1);
    }

    attr.mq_maxmsg = 10;
    attr.mq_msgsize = sizeof(struct msgQueue);
    appQueue = mq_open("appQueue", O_CREAT, 0, &attr);
    if(((int)appQueue) <= 0){
        while(1);
    }

    /* Enable SlNet framework */
    ret = ti_net_SlNet_initConfig();
    if(0 != ret)
    {
        LOG_ERROR("Failed to initialize SlNetSock\n\r");
    }

    /* Enable SlWifiConn */
    ret = WIFI_IF_init();
    assert (ret == 0);

    /* To get the NWP content (version + MAC),
     * The DisplayAppBanner should be called after WIFI_IF_init() after sl_Start() */
    DisplayAppBanner(APPLICATION_NAME, APPLICATION_VERSION);


    /* Enable SlNetConn */
    ret = SlNetConn_init(0);
    assert (ret == 0);

    gSlNetConnThread = OS_createTask(1, SLNETCONN_TASK_STACK_SIZE, SlNetConn_process, NULL, OS_TASK_FLAG_DETACHED);
    assert(gSlNetConnThread);

    
    ret = SlNetConn_start(SLNETCONN_SERVICE_LVL_IP, SlNetConnEventHandler, SLNETCONN_TIMEOUT, 0);

    /* If Failure to acquire AP Connection, verify no pending OTA commit by initializing OTA library then return to attempting to connect to the AP */
    if(ret != 0)
    {
        LOG_INFO("failed to Connect to AP: Error Code: %d. Verifying no pending OTA commits then re-attempting", ret);
        conn_Failure = 1;

    }

#if OTA_SUPPORT
    HTTPSRV_IF_params_t *pHttpSrvParams = NULL;
#if LOCAL_OTA_SUPPORT
    HTTPSRV_IF_params_t httpsSrvParams;
    httpsSrvParams.pClientRootCa = NULL;
    httpsSrvParams.pServerCert = "dummy-root-ca-cert";
    httpsSrvParams.pServerKey = "dummy-root-ca-cert-key";
    httpsSrvParams.primaryPort = 443;
    httpsSrvParams.secondaryPort = 80;
    pHttpSrvParams = &httpsSrvParams;
#endif
    ret = OTA_IF_init(pHttpSrvParams, OtaCallback, 0, NULL);
    if(ret < 0){
        LOG_INFO("failed to init OTA_IF");
        while(1);
    }
#endif

    /* Loop attempt to establish AP Connection */
    while(conn_Failure != 0)
    {
        conn_Failure = SlNetConn_start(SLNETCONN_SERVICE_LVL_IP, SlNetConnEventHandler, SLNETCONN_TIMEOUT, 0);
        LOG_INFO("failed to Connect to AP: Error Code: %d. Retrying...",conn_Failure);
    }

/* AP Connection Success, continue MQTT Application */
MQTT_DEMO:

    ret = MQTT_IF_Init(mqttInitParams);
    if(ret < 0){
        while(1);
    }

#ifdef MQTT_SECURE_CLIENT
    setTime();
#endif

    /*
     * In case a persistent session is being used, subscribe is called before connect so that the module
     * is aware of the topic callbacks the user is using. This is important because if the broker is holding
     * messages for the client, after CONNACK the client may receive the messages before the module is aware
     * of the topic callbacks. The user may still call subscribe after connect but have to be aware of this.
     */
    ret = MQTT_IF_Subscribe(mqttClientHandle, "Broker/To/cc32xx", MQTT_QOS_2, BrokerCB);
    /* LED1/LED2 toggle topics removed in Week 10 merge: those GPIO pins
     * are now claimed by CONFIG_PWM_0 (vibration motor). LED0 stays as
     * the connection-status indicator. */
    ret |= MQTT_IF_Subscribe(mqttClientHandle, "cc32xx/ToggleLED0", MQTT_QOS_2, ToggleLED1CB);
    ret |= MQTT_IF_Subscribe(mqttClientHandle, "cc32xx/OTA", MQTT_QOS_2, StartOTA);
    if(ret < 0){
        while(1);
    }
    else{
        LOG_INFO("Subscribed to all topics successfully\r\n");
    }

    do {
        ret = SlNetConn_waitForConnection(SLNETCONN_SERVICE_LVL_IP, SLNETCONN_TIMEOUT);
    } while(ret != 0);
    LOG_INFO("Wi-Fi connection is UP");

    mqttClientHandle = MQTT_IF_Connect(mqttClientParams, mqttConnParams, MQTT_EventCallback);
    if((int)mqttClientHandle < 0){
        LOG_ERROR("MQTT_IF_Connect Error (%d)\r\n", mqttClientHandle);
    }
    else
    {

        // wait for CONNACK
        while(connected == 0);
        LOG_INFO("MQTT connection is UP");

        GPIO_enableInt(CONFIG_GPIO_BUTTON_0);

        while(1){

            mq_receive(appQueue, (char*)&queueElement, sizeof(struct msgQueue), NULL);

            if(queueElement.event == APP_MQTT_PUBLISH){
                DHT11_Data_t currentData;
                uint16_t     dutyNow = g_duties[g_dutyIdx];

                /* 1. Drive the motor at the current duty level. */
                PWM_setDuty(g_motorPwm, dutyNow);

                /* 2. Read sensor (simulated DHT11). */
                if (DHT11_Read(&currentData) == 0) {

                    /* 3. Build the inner telemetry JSON. May inject
                     *    CORRUPT (byte-flip) or DROP (skip). */
                    int fault = buildTelemetryPayload(s_innerJson,
                                                     sizeof(s_innerJson),
                                                     &currentData,
                                                     dutyNow,
                                                     MOTOR_PERIOD_US);

                    if (fault == FAULT_DROP) {
                        /* Skip MQTT publish entirely -- broker sees seq gap. */
                        UART_PRINT("[FAULT] DROP seq=%u\r\n", (unsigned)g_seq_num);
                    } else {
                        if (fault == FAULT_CORRUPT) {
                            UART_PRINT("[FAULT] CORRUPT seq=%u (inner JSON parse will fail at host)\r\n",
                                       (unsigned)g_seq_num);
                        }

                        /* 4. AES-128-GCM encrypt + wrap in outer envelope. */
                        int outLen = gcm_encrypt_envelope(s_innerJson,
                                                          strlen(s_innerJson),
                                                          g_seq_num,
                                                          g_timestamp_ms,
                                                          s_outbuf,
                                                          sizeof(s_outbuf));
                        if (outLen > 0) {
                            /* 5. Publish authenticated envelope over MQTT/TLS. */
                            MQTT_IF_Publish(mqttClientHandle,
                                            "cc32xx/telemetry",
                                            s_outbuf,
                                            outLen,
                                            MQTT_QOS_2);
                        } else {
                            LOG_ERROR("AES-GCM encrypt failed seq=%u",
                                      (unsigned)g_seq_num);
                        }

                        /* 6. DELAY fault: extra 2s sleep after transmit. */
                        if ((g_seq_num % FAULT_DELAY_EVERY) == 0) {
                            UART_PRINT("[FAULT] DELAY seq=%u\r\n",
                                       (unsigned)g_seq_num);
                            usleep(2000000);
                        }
                    }
                }

                /* 7. Step to next motor duty and pace at the 3000ms loop rate. */
                g_dutyIdx = (g_dutyIdx + 1) % (sizeof(g_duties) / sizeof(g_duties[0]));
                usleep(3000000);

                struct msgQueue nextQueueElement;
                nextQueueElement.event = APP_MQTT_PUBLISH;
                mq_send(appQueue, (const char*)&nextQueueElement, sizeof(struct msgQueue), 0);

                // Clear the interrupt so the button doesn't lock up
                GPIO_clearInt(CONFIG_GPIO_BUTTON_0);
                GPIO_enableInt(CONFIG_GPIO_BUTTON_0);
            }
            else if(queueElement.event == APP_MQTT_CON_TOGGLE){

                LOG_TRACE("APP_MQTT_CON_TOGGLE %d\r\n", connected);


                if(connected){
                    ret = MQTT_IF_Disconnect(mqttClientHandle);
                    if(ret >= 0){
                        connected = 0;
                    }
                }
                else{
                    mqttClientHandle = MQTT_IF_Connect(mqttClientParams, mqttConnParams, MQTT_EventCallback);
                    if((int)mqttClientHandle >= 0)
                    {
                        connected = 1;
                    }
                    /* If failed to re-connect to mqtt start over (this will also include waiting for
                     * the wi-fi connection (in case failure of AP connection caused the disconnection )
                     *  */
                    if(connected == 0)
                        break;
                }
            }
            else if(queueElement.event == APP_MQTT_DEINIT){
                break;
            }
            else if(queueElement.event == APP_OTA_TRIGGER){
                StartOTA(NULL, NULL, 0);
            }
            else if(queueElement.event == APP_BTN_HANDLER){

                struct msgQueue queueElement;

                ret = detectLongPress();
                if(ret == 0){

                    LOG_TRACE("APP_BTN_HANDLER SHORT PRESS\r\n");
                    queueElement.event = APP_MQTT_CON_TOGGLE;
                }
                else{

                    LOG_TRACE("APP_BTN_HANDLER LONG PRESS\r\n");
                    queueElement.event = APP_MQTT_DEINIT;
                }

                ret = mq_send(appQueue, (const char*)&queueElement, sizeof(struct msgQueue), 0);
                if(ret < 0){
                    LOG_ERROR("msg queue send error %d", ret);
                }
            }
        }
    }
    deinit = 1;
    if(connected){
        MQTT_IF_Disconnect(mqttClientHandle);
    }
    MQTT_IF_Deinit();

#if OTA_SUPPORT
    if(gNewImageLoaded)
    {
        SlNetConn_stop(SlNetConnEventHandler);
        OTA_IF_install();
    }
#endif

    LOG_INFO("looping the MQTT functionality of the example for demonstration purposes only\r\n");
    sleep(1);
    goto MQTT_DEMO;
}

//*****************************************************************************
//
// Close the Doxygen group.
//! @}
//
//*****************************************************************************
