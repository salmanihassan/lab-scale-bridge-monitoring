#ifndef SAMPLER_H_
#define SAMPLER_H_

#include <stdbool.h>
#include <stdint.h>

#include "dt_batch.h"

/* Opens the sensors, prints the startup self-check on the console and
 * starts the 100 Hz sampler and the temperature task. Sampling starts at
 * once, whether or not Wi-Fi is up. */
bool Sampler_start(void);

/* Publisher side: wait up to timeout_ms for a finished batch (NULL if none),
 * then hand it back with Sampler_release() when it has been sent or dropped. */
DT_Batch *Sampler_takeReady(uint32_t timeout_ms);
void Sampler_release(DT_Batch *batch);

/* Counted into the diagnostics of later batches. */
void Sampler_notePublishFailed(void);
void Sampler_noteNotConnected(void);

uint32_t Sampler_uptimeMs(void);

#endif /* SAMPLER_H_ */
