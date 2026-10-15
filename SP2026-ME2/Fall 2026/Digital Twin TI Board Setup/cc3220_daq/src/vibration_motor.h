#ifndef VIBRATION_MOTOR_H_
#define VIBRATION_MOTOR_H_

#include <stdbool.h>
#include <stdint.h>

void VibrationMotor_init(void);
void VibrationMotor_start(uint16_t excitation_hz, uint8_t strength_0_to_255);
void VibrationMotor_stop(void);
void VibrationMotor_service(uint32_t now_ms);
bool VibrationMotor_isOn(void);
uint8_t VibrationMotor_strength(void);

#endif /* VIBRATION_MOTOR_H_ */
