#ifndef LOADCELLS_H_
#define LOADCELLS_H_

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int32_t raw[2];    /* last 24-bit signed reading, gain 128, channel A */
    bool valid[2];     /* true once a reading has ever been received */
    bool fresh[2];     /* true only on the poll that received a new reading */
} HX711_Readings;

void HX711_init(void);

/* Polls both devices once. Returns immediately for a device that is not ready,
 * so it is safe to call every 10 ms. */
void HX711_poll(HX711_Readings *readings);

/* Waits up to timeout_ms for device 0 or 1 to signal data ready (DOUT low),
 * then reads it. Returns false if the device never became ready. */
bool HX711_waitAndRead(uint8_t index, uint32_t timeout_ms, int32_t *raw);

#endif /* LOADCELLS_H_ */
