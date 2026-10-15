#ifndef LOADCELLS_H_
#define LOADCELLS_H_

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int32_t raw[2];
    bool valid[2];
} HX711_Readings;

void HX711_init(void);
/* Polls two independent devices. It returns promptly if a device is not ready. */
void HX711_poll(HX711_Readings *readings);

#endif /* LOADCELLS_H_ */
