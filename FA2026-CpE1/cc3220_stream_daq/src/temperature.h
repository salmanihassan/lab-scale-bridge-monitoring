#ifndef TEMPERATURE_H_
#define TEMPERATURE_H_

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    float celsius[3];
    bool valid[3];       /* false until a reading passes its CRC, and after a failed read */
} DS18B20_Readings;

typedef struct {
    uint32_t reads;          /* read attempts per probe */
    uint32_t no_presence;    /* probe did not answer the reset pulse */
    uint32_t crc_errors;     /* scratchpad CRC mismatch (bit timing or wiring noise) */
} DS18B20_Stats;

/* Releases the three 1-Wire lines (P63, P53, P50). Call Timing_init() first. */
void DS18B20_init(void);

/* Sends one reset pulse on probe 0..2 and reports whether it answered. */
bool DS18B20_isPresent(uint8_t index);

/* Starts the background task: convert all three every DT_TEMPERATURE_PERIOD_MS,
 * read them DT_DS18B20_CONVERSION_MS later. Runs below the 100 Hz loop so it
 * never delays a sample row; each 1-Wire bit slot is protected on its own. */
bool DS18B20_startTask(void);

/* Copies the latest readings (consistent snapshot). */
void DS18B20_get(DS18B20_Readings *out);
void DS18B20_getStats(uint8_t index, DS18B20_Stats *out);

/* Worst-case time GPIO_setConfig() took during the last direction switch
 * measurement, in microseconds (0 if the cycle counter is unavailable). */
uint32_t DS18B20_switchOverheadUs(void);

#endif /* TEMPERATURE_H_ */
