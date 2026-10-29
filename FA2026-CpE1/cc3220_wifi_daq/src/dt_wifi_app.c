/*
 * Bridge digital twin node: real sensor data over Wi-Fi and MQTT.
 *
 * Stage 2 (secured link), on top of stage 1:
 *   - every batch is signed with HMAC-SHA256 (payload.c, dt_hmac.c), key and
 *     key id from secrets.h, which host/dt_setup_security.py generates.
 *   - the board logs in to Mosquitto with its own user name and password, and
 *     the broker's ACL only lets that user write bridge/<DEVICE_ID>/#.
 *   - DT_USE_TLS 1 (the default): TLS 1.2 to port 8883, server certificate
 *     checked against the project CA (compiled in, copied to the network
 *     processor's file system at boot). DT_USE_TLS 0 is stage 2a: the same
 *     login and signatures over plain port 1883, for bring-up and comparison.
 *
 * Based on the SimpleLink CC32xx SDK 7.10 mqtt_client example (Wi-Fi and MQTT
 * plumbing, ifmod/ helpers used unchanged). Changes from the example:
 *   - Wi-Fi only needs IP level (the SDK example waits for internet access,
 *     which never comes on an isolated project router).
 *   - no OTA, no buttons, no LED topics.
 *   - the 100 Hz sampler (sampler.c) starts at boot, independent of the network.
 *   - a publisher task sends one JSON batch per second (payload.c) on
 *     bridge/<DEVICE_ID>/batch, QoS 1.
 *   - a retained status topic bridge/<DEVICE_ID>/status: "online" after each
 *     connect, "offline" set as the MQTT will.
 *   - reconnects by itself after a broker or Wi-Fi drop, with no busy-waiting.
 *
 * Console (XDS110 UART, 115200 baud) shows the startup self-check, the
 * connection progress and one status line every 10 s.
 */
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>
#include <mqueue.h>

#include <ti/drivers/GPIO.h>
#include <ti/drivers/SPI.h>
#include <ti/drivers/net/wifi/simplelink.h>
#include <ti/drivers/net/wifi/slnetifwifi.h>
#include <ti/drivers/net/wifi/slwificonn.h>
#include <ti/net/slnet.h>
#include <ti/net/slnetif.h>
#include <ti/net/slnetconn.h>
#include <ti/net/mqtt/mqttclient.h>

#include "uart_if.h"
#include "wifi_if.h"
#include "mqtt_if.h"
#include "debug_if.h"
#include "utils_if.h"

#include "ti_drivers_config.h"

#include "network_config.h"
#include "board_config.h"
#include "payload.h"
#include "sampler.h"
#include "secrets.h"
#include "tls_files.h"

#ifndef DT_USE_TLS
#define DT_USE_TLS          1
#endif
#ifndef DT_BROKER_TLS_PORT
#define DT_BROKER_TLS_PORT  8883
#endif

#if DT_USE_TLS
#define DT_LINK_PORT        DT_BROKER_TLS_PORT
#define DT_LINK_MODE        "TLS 1.2 + login + HMAC"
#else
#define DT_LINK_PORT        DT_BROKER_PORT
#define DT_LINK_MODE        "plain TCP + login + HMAC (stage 2a, no encryption)"
#endif

#undef DEBUG_IF_NAME
#define DEBUG_IF_NAME       "DT_APP"
#undef DEBUG_IF_SEVERITY
#define DEBUG_IF_SEVERITY   E_INFO

#define APP_NAME            "Bridge DT Wi-Fi node"
#define APP_VERSION         "0.2.0"

#define TOPIC_BATCH         "bridge/" DT_DEVICE_ID "/batch"
#define TOPIC_STATUS        "bridge/" DT_DEVICE_ID "/status"

#define SLNETCONN_TIMEOUT_S         10
#define SLNETCONN_TASK_STACK_SIZE   1200
#define MQTT_MODULE_TASK_PRIORITY   2
#define MQTT_MODULE_TASK_STACK_SIZE 2048
#define RECONNECT_DELAY_S           2u
#define STATUS_PERIOD_MS            10000u

extern int32_t ti_net_SlNet_initConfig();

/* ------------------------------------------------------------ MQTT parameters */

static char s_clientId[13] = "dtnode01";

static MQTT_IF_InitParams_t s_mqttInitParams = {
    MQTT_MODULE_TASK_STACK_SIZE,
    MQTT_MODULE_TASK_PRIORITY
};

static MQTTClient_Will s_will = {
    TOPIC_STATUS,
    "offline",
    MQTT_QOS_1,
    true        /* retained, so a dashboard sees "offline" after a drop */
};

static MQTT_IF_ClientParams_t s_clientParams = {
    s_clientId,
    DT_MQTT_USER,
    DT_MQTT_PASSWORD,
    30,         /* keep-alive (s): lets both sides notice a dead link */
    true,       /* clean session */
    true,       /* MQTT 3.1 (as the SDK example) */
    true,       /* blocking send: QoS 1 publish returns after PUBACK */
    &s_will
};

#if DT_USE_TLS
/* Only the project CA is trusted (no TI certificate catalog). Domain name
 * checking is skipped by the SDK when connecting by IP address, so the chain
 * check against the CA is what authenticates the broker.
 * Ciphers: forward secrecy and AEAD only. The SDK's "full list" would also
 * offer RC4 and static-RSA suites. */
#define DT_TLS_CIPHERS (SLNETSOCK_SEC_CIPHER_TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256 | \
                        SLNETSOCK_SEC_CIPHER_TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384 | \
                        SLNETSOCK_SEC_CIPHER_TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256)

static char *const s_secureFiles[1] = { DT_CA_FILE_NAME };

static MQTTClient_ConnParams s_connParams = {
    MQTTCLIENT_NETCONN_IP4 | MQTTCLIENT_NETCONN_SEC |
        MQTTCLIENT_NETCONN_SKIP_CERTIFICATE_CATALOG_VERIFICATION,
    DT_BROKER_IP,
    DT_BROKER_TLS_PORT,
    SLNETSOCK_SEC_METHOD_TLSV1_2,
    DT_TLS_CIPHERS,
    1,              /* one file: the root CA, so the SDK sets PEER_ROOT_CA */
    s_secureFiles
};
#else
static MQTTClient_ConnParams s_connParams = {
    MQTTCLIENT_NETCONN_IP4,
    DT_BROKER_IP,
    DT_BROKER_PORT,
    0, 0, 0, NULL   /* stage 2a: no TLS */
};
#endif

/* ------------------------------------------------------------ shared state */

enum { APP_EVT_DISCONNECTED = 1 };
struct AppMsg { int event; uint32_t gen; };

static mqd_t s_appQueue;
static volatile int s_connected;      /* set by mainThread only after an accepted CONNACK */
static volatile int s_linkDown;       /* any disconnect seen since the current attempt began */
static volatile uint32_t s_connGen;   /* connection attempt number, tags queue messages */
static volatile MQTTClient_Handle s_mqtt;
static uint32_t s_bootId;

static volatile uint32_t s_published;
static volatile uint32_t s_publishErrors;
static volatile uint32_t s_skippedOffline;
static volatile uint32_t s_lastSeq;

/* ------------------------------------------------------------ SimpleLink event stubs */
/* wifi_if.c handles WLAN, NetApp, general and fatal events. These remain. */

void SimpleLinkSockEventHandler(SlSockEvent_t *pSock)
{
    (void)pSock;
}

void SimpleLinkHttpServerEventHandler(SlNetAppHttpServerEvent_t *pHttpEvent,
                                      SlNetAppHttpServerResponse_t *pHttpResponse)
{
    (void)pHttpEvent;
    (void)pHttpResponse;
}

void SimpleLinkNetAppRequestEventHandler(SlNetAppRequest_t *pNetAppRequest,
                                         SlNetAppResponse_t *pNetAppResponse)
{
    (void)pNetAppRequest;
    (void)pNetAppResponse;
}

void SimpleLinkNetAppRequestMemFreeEventHandler(_u8 *buffer)
{
    (void)buffer;
}

/* ------------------------------------------------------------ callbacks */

static void SlNetConnEventHandler(uint32_t ifID, SlNetConnStatus_e netStatus, void *data)
{
    (void)data;
    switch (netStatus) {
    case SLNETCONN_STATUS_CONNECTED_MAC:
        UART_PRINT("[DT] Wi-Fi: associated with the access point\r\n");
        break;
    case SLNETCONN_STATUS_CONNECTED_IP:
        UART_PRINT("[DT] Wi-Fi: got an IP address\r\n");
        break;
    case SLNETCONN_STATUS_CONNECTED_INTERNET:
        UART_PRINT("[DT] Wi-Fi: internet reachable (not required)\r\n");
        break;
    case SLNETCONN_STATUS_WAITING_FOR_CONNECTION:
    case SLNETCONN_STATUS_DISCONNECTED:
        UART_PRINT("[DT] Wi-Fi: disconnected (I/F %d)\r\n", (int)ifID);
        break;
    default:
        break;
    }
}

static void MqttEventCallback(int32_t event)
{
    struct AppMsg msg;

    /* CONNACK is not used here: the SDK raises it for a refused login too.
     * MQTT_IF_Connect() returns >= 0 only for an accepted CONNACK. */
    switch (event) {
    case MQTT_EVENT_SERVER_DISCONNECT:
    case MQTT_EVENT_CLIENT_DISCONNECT:
        s_linkDown = 1;
        if (s_connected) {
            s_connected = 0;
            msg.event = APP_EVT_DISCONNECTED;
            msg.gen = s_connGen;
            (void)mq_send(s_appQueue, (const char *)&msg, sizeof(msg), 0);
        }
        break;
    default:
        break;
    }
}

/* ------------------------------------------------------------ publisher task */

static void *publisherTask(void *arg)
{
    static char payload[DT_PAYLOAD_MAX];
    uint32_t lastStatus = 0u;

    (void)arg;
    for (;;) {
        DT_Batch *b = Sampler_takeReady(1000u);
        const uint32_t now = Sampler_uptimeMs();

        if (b != NULL) {
            s_lastSeq = b->seq;
            if (!s_connected || (s_mqtt == NULL)) {
                ++s_skippedOffline;
                Sampler_noteNotConnected();
            } else {
                int len = Payload_encode(b, DT_DEVICE_ID, DT_HMAC_KID, s_bootId, now,
                                         payload, sizeof(payload));
                if (len >= 0) {
                    len = Payload_sign(payload, len, sizeof(payload), DT_HMAC_KEY, sizeof(DT_HMAC_KEY));
                }
                if (len < 0) {
                    ++s_publishErrors;
                    Sampler_notePublishFailed();
                    LOG_ERROR("batch %lu did not fit in the payload buffer", (unsigned long)b->seq);
                } else if (MQTT_IF_Publish(s_mqtt, TOPIC_BATCH, payload,
                                           (unsigned short)len, MQTT_QOS_1) < 0) {
                    ++s_publishErrors;
                    Sampler_notePublishFailed();
                } else {
                    ++s_published;
                }
            }
            Sampler_release(b);
        }

        if ((uint32_t)(now - lastStatus) >= STATUS_PERIOD_MS) {
            lastStatus = now;
            UART_PRINT("[DT] t=%lus mqtt=%s last_seq=%lu published=%lu errors=%lu offline=%lu\r\n",
                       (unsigned long)(now / 1000u), s_connected ? "up" : "down",
                       (unsigned long)s_lastSeq, (unsigned long)s_published,
                       (unsigned long)s_publishErrors, (unsigned long)s_skippedOffline);
        }
    }
    return NULL; /* not reached */
}

/* ------------------------------------------------------------ helpers */

static void printBanner(void)
{
    uint8_t mac[SL_MAC_ADDR_LEN];
    uint16_t macLen = SL_MAC_ADDR_LEN;

    (void)sl_NetCfgGet(SL_NETCFG_MAC_ADDRESS_GET, 0, &macLen, &mac[0]);
    UART_PRINT("\r\n[DT] ==== %s %s ====\r\n", APP_NAME, APP_VERSION);
    UART_PRINT("[DT] device %s, MAC %02x:%02x:%02x:%02x:%02x:%02x, boot_id %08lx\r\n",
               DT_DEVICE_ID, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5],
               (unsigned long)s_bootId);
    UART_PRINT("[DT] network \"%s\", broker %s:%d, topic %s\r\n",
               DT_WIFI_SSID, DT_BROKER_IP, (int)DT_LINK_PORT, TOPIC_BATCH);
    UART_PRINT("[DT] security: %s, MQTT user %s, key id %s\r\n",
               DT_LINK_MODE, DT_MQTT_USER, DT_HMAC_KID);
}

static uint32_t randomBootId(void)
{
    uint32_t r = 0u;
    uint16_t len = sizeof(r);

    if (sl_NetUtilGet(SL_NETUTIL_TRUE_RANDOM, 0, (uint8_t *)&r, &len) < 0) {
        r = Sampler_uptimeMs() ^ 0xA5A5A5A5u; /* fallback, should not happen */
    }
    return r;
}

static void explainConnectError(int32_t err)
{
    switch (err) {
    case -111:
        UART_PRINT("[DT] MQTT: connection refused. Is Mosquitto running with the stage 2 config, "
                   "and port %d open in the laptop firewall?\r\n", (int)DT_LINK_PORT);
        break;
    case -4:
    case -5:
        UART_PRINT("[DT] MQTT: the broker refused the login (or a library error %d). The Mosquitto "
                   "log says which. If the password was refused: rerun dt_setup_security.py, "
                   "rebuild, reflash, restart Mosquitto.\r\n", (int)err);
        break;
    case SLNETERR_ESEC_UNKNOWN_ROOT_CA:
        UART_PRINT("[DT] TLS: the broker's certificate is not from the project CA in this "
                   "firmware (%d). Rebuild after the last dt_setup_security.py run.\r\n", (int)err);
        break;
    case SLNETERR_ESEC_DATE_ERROR:
        UART_PRINT("[DT] TLS: certificate date check failed (%d). Board clock is the build "
                   "time: rebuild if the certificates are newer than this firmware.\r\n", (int)err);
        break;
    default:
        UART_PRINT("[DT] MQTT: connect failed (%d)\r\n", (int)err);
        break;
    }
}

static bool startTask(void *(*fn)(void *), int prio, size_t stack)
{
    pthread_t t;
    pthread_attr_t attr;
    struct sched_param p;

    p.sched_priority = prio;
    (void)pthread_attr_init(&attr);
    (void)pthread_attr_setschedparam(&attr, &p);
    (void)pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    (void)pthread_attr_setstacksize(&attr, stack);
    return pthread_create(&t, &attr, fn, NULL) == 0;
}

/* ------------------------------------------------------------ main thread */

void *mainThread(void *arg)
{
    mq_attr attr;
    struct AppMsg msg;
    pthread_t slNetConnThread;
    int32_t ret;

    (void)arg;
    InitTerm();
    GPIO_init();
    SPI_init();
    GPIO_write(CONFIG_GPIO_LED_0, CONFIG_GPIO_LED_OFF);

    attr.mq_maxmsg = 4;
    attr.mq_msgsize = sizeof(struct AppMsg);
    s_appQueue = mq_open("dtApp", O_CREAT, 0, &attr);
    if (((int)s_appQueue) <= 0) {
        UART_PRINT("[DT] FATAL: app queue\r\n");
        for (;;) { sleep(1); }
    }

    ret = ti_net_SlNet_initConfig();
    if (ret != 0) {
        LOG_ERROR("SlNetSock init failed (%d)", (int)ret);
    }
    ret = WIFI_IF_init();               /* starts the network processor (sl_Start) */
    if (ret != 0) {
        UART_PRINT("[DT] FATAL: WIFI_IF_init failed (%d)\r\n", (int)ret);
        for (;;) { sleep(1); }
    }
    s_bootId = randomBootId();
    printBanner();

#if DT_USE_TLS
    TlsFiles_setClockFromBuild();
    ret = TlsFiles_installCa(DT_CA_FILE_NAME, DT_CA_PEM, (uint32_t)(sizeof(DT_CA_PEM) - 1u));
    if (ret < 0) {
        UART_PRINT("[DT] TLS: could not store the CA certificate (%d), connections will fail\r\n",
                   (int)ret);
    } else {
        UART_PRINT("[DT] TLS: CA certificate %s %s\r\n", DT_CA_FILE_NAME,
                   (ret == 0) ? "already up to date" : "written to the network processor");
    }
#endif

    /* Sensors run from here on, whether or not the network ever comes up. */
    if (!Sampler_start()) {
        UART_PRINT("[DT] FATAL: sampler did not start\r\n");
        for (;;) { sleep(1); }
    }
    if (!startTask(publisherTask, DT_PUBLISH_TASK_PRIORITY, DT_PUBLISH_TASK_STACK_BYTES)) {
        UART_PRINT("[DT] FATAL: publisher did not start\r\n");
        for (;;) { sleep(1); }
    }

    ret = SlNetConn_init(0);
    if (ret != 0) {
        UART_PRINT("[DT] FATAL: SlNetConn_init failed (%d)\r\n", (int)ret);
        for (;;) { sleep(1); }
    }
    slNetConnThread = OS_createTask(1, SLNETCONN_TASK_STACK_SIZE, SlNetConn_process, NULL,
                                    OS_TASK_FLAG_DETACHED);
    (void)slNetConnThread;

    /* IP level is enough: the project network has no internet uplink.
     * SlNetConn_start() registers one standing request and keeps retrying in
     * the background: 0 = connected, 1 = still trying (not an error), negative
     * = the request itself failed. It must not be called again while the
     * request is active (the first build did, which flooded the console). */
    UART_PRINT("[DT] Wi-Fi: connecting to \"%s\"...\r\n", DT_WIFI_SSID);
    ret = SlNetConn_start(SLNETCONN_SERVICE_LVL_IP, SlNetConnEventHandler, SLNETCONN_TIMEOUT_S, 0);
    while (ret < 0) {
        UART_PRINT("[DT] Wi-Fi: connection request failed (%d), retrying\r\n", (int)ret);
        sleep(RECONNECT_DELAY_S);
        ret = SlNetConn_start(SLNETCONN_SERVICE_LVL_IP, SlNetConnEventHandler, SLNETCONN_TIMEOUT_S, 0);
    }

    if (MQTT_IF_Init(s_mqttInitParams) < 0) {
        UART_PRINT("[DT] FATAL: MQTT_IF_Init failed\r\n");
        for (;;) { sleep(1); }
    }

    for (;;) {
        MQTTClient_Handle h;

        for (;;) {
            ret = SlNetConn_waitForConnection(SLNETCONN_SERVICE_LVL_IP, SLNETCONN_TIMEOUT_S);
            if (ret == 0) {
                break;
            }
            UART_PRINT("[DT] Wi-Fi: not connected yet (check name, password, 2.4 GHz)\r\n");
            if (ret < 0) {
                sleep(RECONNECT_DELAY_S); /* never spin if the call fails at once */
            }
        }

        UART_PRINT("[DT] MQTT: connecting to %s:%d...\r\n", DT_BROKER_IP, (int)DT_LINK_PORT);
        s_connected = 0;
        s_linkDown = 0;
        ++s_connGen;
        /* Blocks until the TLS handshake and the CONNACK are done. A failed
         * attempt is cleaned up by the SDK's MQTT context thread. */
        h = MQTT_IF_Connect(s_clientParams, s_connParams, MqttEventCallback);
        if ((int)h < 0) {
            explainConnectError((int32_t)(int)h);
            sleep(RECONNECT_DELAY_S);
            continue;
        }
        s_mqtt = h;
        s_connected = 1;
        if (s_linkDown) {           /* dropped between CONNACK and here */
            s_connected = 0;
            s_mqtt = NULL;
            UART_PRINT("[DT] MQTT: link dropped right after connecting, retrying\r\n");
            sleep(RECONNECT_DELAY_S);
            continue;
        }

        (void)MQTT_IF_Publish(h, TOPIC_STATUS, "online", 6, MQTT_QOS_1 | MQTT_PUBLISH_RETAIN);
        GPIO_write(CONFIG_GPIO_LED_0, CONFIG_GPIO_LED_ON);
        UART_PRINT("[DT] MQTT: connected, publishing on %s\r\n", TOPIC_BATCH);

        /* Sleep until the broker or the network drops us. Messages left over
         * from an earlier connection carry an older gen and are ignored. */
        do {
            (void)mq_receive(s_appQueue, (char *)&msg, sizeof(msg), NULL);
        } while ((msg.event != APP_EVT_DISCONNECTED) || (msg.gen != s_connGen));

        s_mqtt = NULL;
        GPIO_write(CONFIG_GPIO_LED_0, CONFIG_GPIO_LED_OFF);
        UART_PRINT("[DT] MQTT: disconnected, will reconnect\r\n");
        sleep(RECONNECT_DELAY_S); /* lets the MQTT context thread clean up first */
    }
}
