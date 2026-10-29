#ifndef DT_BATCH_H_
#define DT_BATCH_H_

/*
 * One second of sensor data: the unit that is published as one MQTT message.
 */

#include <stdbool.h>
#include <stdint.h>

#include "board_config.h"

typedef struct {
    uint16_t dt_ms;      /* sample time minus batch t0, in ms */
    int16_t  ax, ay, az; /* ADXL345 raw counts, 1/256 g each (full resolution, +/-2 g) */
    int32_t  l1, l2;     /* HX711 raw counts, last conversion (gain 128, channel A) */
    uint8_t  flags;      /* DT_SAMPLE_* bits below */
} DT_Sample;

#define DT_SAMPLE_ACCEL_OK   0x01u  /* accelerometer read succeeded for this sample */
#define DT_SAMPLE_L1_VALID   0x02u  /* load 1 has reported at least once */
#define DT_SAMPLE_L2_VALID   0x04u
#define DT_SAMPLE_L1_NEW     0x08u  /* load 1 delivered a new conversion on this sample */
#define DT_SAMPLE_L2_NEW     0x10u

typedef struct {
    uint32_t seq;            /* batch number since boot, starts at 0, never reused */
    uint32_t t0_ms;          /* board time of the first sample (ms since boot) */
    uint16_t n;              /* number of samples filled */
    DT_Sample s[DT_BATCH_SAMPLES];

    float    temp_c[3];      /* DS18B20 readings at the end of the batch */
    bool     temp_ok[3];

    /* Running diagnostics since boot, copied in when the batch closes. */
    uint32_t accel_fail_total;   /* accelerometer reads that failed */
    uint32_t late_slots_total;   /* 10 ms slots that started late */
    uint32_t dropped_total;      /* batches discarded because no buffer was free */
    uint32_t pub_fail_total;     /* batches the publisher could not send */
    uint32_t not_connected_total;/* batches discarded while MQTT was down */
} DT_Batch;

#endif /* DT_BATCH_H_ */
