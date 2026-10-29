/*
 * 100 Hz sampler: accelerometer and both load cells every 10 ms, the three
 * temperatures once per second (own task), collected into one-second batches.
 *
 * Batches circulate through a small pool. The sampler fills one, then hands
 * it to the publisher through readyQ and takes an empty one from freeQ. If no
 * empty batch is available (publisher stuck on the network), the batch just
 * filled is discarded and counted, so sampling never waits for the network.
 * Every batch gets a sequence number when it starts, discarded ones included,
 * so the receiver can see and count every gap.
 */
#include "sampler.h"

#include "accelerometer.h"
#include "board_config.h"
#include "loadcells.h"
#include "temperature.h"
#include "timing.h"

#include <pthread.h>
#include <string.h>

#include <FreeRTOS.h>
#include <queue.h>
#include <task.h>

#include "uart_if.h"

#define POOL_SIZE 4u

static DT_Batch s_pool[POOL_SIZE];
static QueueHandle_t s_freeQ;
static QueueHandle_t s_readyQ;

static volatile uint32_t s_accelFail;
static volatile uint32_t s_lateSlots;
static volatile uint32_t s_dropped;
static volatile uint32_t s_pubFail;
static volatile uint32_t s_notConnected;

static const char *const s_loadPins[2] = { "DT P03, SCK P61", "DT P05, SCK P62" };
static const char *const s_tempPins[3] = { "P63", "P53", "P50" };

uint32_t Sampler_uptimeMs(void)
{
    return (uint32_t)xTaskGetTickCount() * (uint32_t)portTICK_PERIOD_MS;
}

static void closeBatch(DT_Batch *b)
{
    DS18B20_Readings t;
    uint8_t k;

    DS18B20_get(&t);
    for (k = 0u; k < 3u; ++k) {
        b->temp_c[k] = t.celsius[k];
        b->temp_ok[k] = t.valid[k];
    }
    b->accel_fail_total = s_accelFail;
    b->late_slots_total = s_lateSlots;
    b->dropped_total = s_dropped;
    b->pub_fail_total = s_pubFail;
    b->not_connected_total = s_notConnected;
}

static void *samplerTask(void *arg)
{
    static uint32_t seq;
    HX711_Readings loads;
    ADXL345_Sample a;
    DT_Batch *cur = NULL;
    TickType_t lastWake;
    const TickType_t period = pdMS_TO_TICKS(DT_SAMPLE_PERIOD_MS);

    (void)arg;
    memset(&loads, 0, sizeof(loads));
    (void)xQueueReceive(s_freeQ, &cur, portMAX_DELAY);
    cur->seq = seq++;
    cur->n = 0u;

    lastWake = xTaskGetTickCount();
    for (;;) {
        const uint32_t now = Sampler_uptimeMs();
        DT_Sample *s;

        if (cur->n == 0u) {
            cur->t0_ms = now;
        }
        s = &cur->s[cur->n];
        s->dt_ms = (uint16_t)(now - cur->t0_ms);
        s->flags = 0u;

        /* Accelerometer first so its sample time is closest to dt_ms. */
        if (ADXL345_read(&a)) {
            s->ax = a.x_raw;
            s->ay = a.y_raw;
            s->az = a.z_raw;
            s->flags |= DT_SAMPLE_ACCEL_OK;
        } else {
            s->ax = s->ay = s->az = 0;
            ++s_accelFail;
        }

        /* A ready HX711 is read within 10 ms of finishing a conversion;
         * a not-ready one costs a single pin read. */
        HX711_poll(&loads);
        s->l1 = loads.raw[0];
        s->l2 = loads.raw[1];
        if (loads.valid[0]) { s->flags |= DT_SAMPLE_L1_VALID; }
        if (loads.valid[1]) { s->flags |= DT_SAMPLE_L2_VALID; }
        if (loads.fresh[0]) { s->flags |= DT_SAMPLE_L1_NEW; }
        if (loads.fresh[1]) { s->flags |= DT_SAMPLE_L2_NEW; }

        if (++cur->n >= DT_BATCH_SAMPLES) {
            DT_Batch *next = NULL;

            closeBatch(cur);
            if (xQueueReceive(s_freeQ, &next, 0) == pdPASS) {
                (void)xQueueSend(s_readyQ, &cur, 0); /* cannot be full: POOL_SIZE slots */
                cur = next;
            } else {
                ++s_dropped; /* publisher holds every buffer: discard this second */
            }
            cur->seq = seq++;
            cur->n = 0u;
        }

        /* A slot is late if this pass ran past the next 10 ms boundary. */
        if ((TickType_t)(xTaskGetTickCount() - lastWake) >= period) {
            ++s_lateSlots;
        }
        vTaskDelayUntil(&lastWake, period);
    }
    return NULL; /* not reached */
}

static void selfCheck(bool accelOk)
{
    uint8_t i;

    UART_PRINT("[DT] timing: %s\r\n", Timing_cycleCounterOk()
               ? "cycle counter running" : "cycle counter NOT running, UtilsDelay fallback");
    if (accelOk) {
        UART_PRINT("[DT] ADXL345: found at 0x%02x\r\n", (unsigned)ADXL345_getAddress());
    } else {
        UART_PRINT("[DT] ADXL345: NOT FOUND (SCL P01, SDA P02, VCC/CS 3V3, SDO GND)\r\n");
    }
    for (i = 0u; i < 2u; ++i) {
        int32_t raw = 0;
        if (HX711_waitAndRead(i, DT_HX711_READY_TIMEOUT_MS, &raw)) {
            UART_PRINT("[DT] HX711 Load %u (%s): ready, raw=%ld%s\r\n", (unsigned)(i + 1u),
                       s_loadPins[i], (long)raw,
                       ((raw == -1) || (raw == 0)) ? "  <- looks like a wiring fault" : "");
        } else {
            UART_PRINT("[DT] HX711 Load %u (%s): NOT RESPONDING (check VCC, GND, DT)\r\n",
                       (unsigned)(i + 1u), s_loadPins[i]);
        }
    }
    for (i = 0u; i < 3u; ++i) {
        UART_PRINT("[DT] DS18B20 Temp %u (%s): %s\r\n", (unsigned)(i + 1u), s_tempPins[i],
                   DS18B20_isPresent(i) ? "present" : "NOT FOUND (4.7k pull-up to 3V3?)");
    }
}

bool Sampler_start(void)
{
    pthread_t thread;
    pthread_attr_t attr;
    struct sched_param prio;
    uint32_t i;
    bool accelOk;

    s_freeQ = xQueueCreate(POOL_SIZE, sizeof(DT_Batch *));
    s_readyQ = xQueueCreate(POOL_SIZE, sizeof(DT_Batch *));
    if ((s_freeQ == NULL) || (s_readyQ == NULL)) {
        UART_PRINT("[DT] queue allocation failed\r\n");
        return false;
    }
    for (i = 0u; i < POOL_SIZE; ++i) {
        DT_Batch *b = &s_pool[i];
        (void)xQueueSend(s_freeQ, &b, 0);
    }

    (void)Timing_init();
    accelOk = ADXL345_init();
    HX711_init();
    DS18B20_init();
    selfCheck(accelOk);

    if (!DS18B20_startTask()) {
        UART_PRINT("[DT] temperature task did not start; temperatures will be null\r\n");
    }

    prio.sched_priority = DT_SAMPLER_TASK_PRIORITY;
    (void)pthread_attr_init(&attr);
    (void)pthread_attr_setschedparam(&attr, &prio);
    (void)pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    (void)pthread_attr_setstacksize(&attr, DT_SAMPLER_TASK_STACK_BYTES);
    if (pthread_create(&thread, &attr, samplerTask, NULL) != 0) {
        UART_PRINT("[DT] sampler task did not start\r\n");
        return false;
    }
    return true;
}

DT_Batch *Sampler_takeReady(uint32_t timeout_ms)
{
    DT_Batch *b = NULL;

    if (xQueueReceive(s_readyQ, &b, pdMS_TO_TICKS(timeout_ms)) != pdPASS) {
        return NULL;
    }
    return b;
}

void Sampler_release(DT_Batch *batch)
{
    if (batch != NULL) {
        (void)xQueueSend(s_freeQ, &batch, 0);
    }
}

void Sampler_notePublishFailed(void)
{
    ++s_pubFail;
}

void Sampler_noteNotConnected(void)
{
    ++s_notConnected;
}
