#ifndef ACCELEROMETER_H_
#define ACCELEROMETER_H_

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int16_t x_raw;
    int16_t y_raw;
    int16_t z_raw;
    float x_g;
    float y_g;
    float z_g;
} ADXL345_Sample;

bool ADXL345_init(void);
bool ADXL345_read(ADXL345_Sample *sample);
bool ADXL345_isPresent(void);
uint8_t ADXL345_getAddress(void);
bool ADXL345_probeResponded(uint8_t address, uint8_t *device_id);
void ADXL345_scanBus(void (*report)(uint8_t address));

#endif /* ACCELEROMETER_H_ */
