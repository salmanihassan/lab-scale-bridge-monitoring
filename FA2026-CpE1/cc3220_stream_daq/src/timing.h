#ifndef TIMING_H_
#define TIMING_H_

/*
 * Microsecond busy-wait for the bit-banged sensors (HX711 clock, DS18B20 1-Wire).
 *
 * Why this exists: on FreeRTOS, ClockP_usleep() and usleep() round up to whole
 * scheduler ticks (1 ms here). The original drivers used ClockP_usleep(1) for
 * the HX711 half clock and ClockP_usleep(6..70) for 1-Wire slots, which really
 * waited about 1 ms each. That holds HX711 SCK high far past its 60 us
 * power-down limit, and misses every 1-Wire timing window.
 *
 * The Cortex-M4 DWT cycle counter is used when it runs. If it does not, the
 * driverlib UtilsDelay() loop is used instead (less exact, still microseconds).
 */

#include <stdbool.h>
#include <stdint.h>

#define DT_CPU_HZ 80000000u /* CC3220SF Cortex-M4 core clock */

/* Call once before any sensor driver. Returns true if the cycle counter runs. */
bool Timing_init(void);
bool Timing_cycleCounterOk(void);

/* Current cycle count (0 when the cycle counter is unavailable). */
uint32_t Timing_now(void);

/* Spin until 'us' microseconds after 'start' (a Timing_now() value).
 * Without the cycle counter this waits 'us' from the call instead. */
void Timing_waitUntil(uint32_t start, uint32_t us);

/* Spin for 'us' microseconds. */
void Timing_delayUs(uint32_t us);

/* Cycles between two Timing_now() values, converted to whole microseconds. */
uint32_t Timing_elapsedUs(uint32_t start, uint32_t end);

#endif /* TIMING_H_ */
