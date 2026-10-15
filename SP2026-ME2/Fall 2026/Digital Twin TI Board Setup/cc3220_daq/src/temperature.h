#ifndef TEMPERATURE_H_
#define TEMPERATURE_H_

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    float celsius[3];
    bool valid[3];
} DS18B20_Readings;

void DS18B20_init(void);
/* Starts a conversion approximately once per second and reads it later without
 * waiting for the 12-bit 750-ms conversion to finish. */
void DS18B20_service(uint32_t now_ms, DS18B20_Readings *readings);

#endif /* TEMPERATURE_H_ */
