#ifndef ACQUISITION_H_
#define ACQUISITION_H_

/* The one compile-time mode is intentionally used so diagnostics never mix
 * with the machine-readable CSV stream. */
typedef enum {
    ACQ_MODE_STREAM = 0,
    ACQ_MODE_I2C_SCAN,
    ACQ_MODE_ADXL345,
    ACQ_MODE_LOADCELLS,
    ACQ_MODE_TEMPERATURES,
    ACQ_MODE_MOTOR
} Acquisition_Mode;

void Acquisition_run(Acquisition_Mode mode);

#endif /* ACQUISITION_H_ */
