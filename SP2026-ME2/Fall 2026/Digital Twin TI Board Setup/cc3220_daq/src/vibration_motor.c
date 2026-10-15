#include "vibration_motor.h"
#include "board_config.h"

#include <ti/drivers/GPIO.h>
#include "ti_drivers_config.h"

static uint16_t excitation_hz;
static uint8_t strength;
static uint32_t next_toggle_ms;
static bool motor_on;

static void applyGate(bool enable)
{
    GPIO_write(CONFIG_MOTOR_EN, enable ? 1u : 0u);
}

void VibrationMotor_init(void)
{
    GPIO_init();
    applyGate(false);
}

void VibrationMotor_start(uint16_t frequency, uint8_t new_strength)
{
    excitation_hz = frequency;
    strength = new_strength;
    motor_on = false;
    next_toggle_ms = 0u;
    applyGate(false);
}

void VibrationMotor_stop(void)
{
    excitation_hz = 0u;
    motor_on = false;
    applyGate(false);
}

void VibrationMotor_service(uint32_t now_ms)
{
    uint32_t half_period_ms;
    if (excitation_hz == 0u) {
        return;
    }
    half_period_ms = 500u / excitation_hz;
    if (half_period_ms == 0u) {
        half_period_ms = 1u;
    }
    if ((next_toggle_ms == 0u) || ((int32_t)(now_ms - next_toggle_ms) >= 0)) {
        motor_on = !motor_on;
        /* P18 is the only isolated route on the stock board but is not a
         * timer PWM pin.  It gates a transistor at the requested envelope;
         * strength is retained in the telemetry/API for a future external
         * PWM driver and does not reduce the GPIO high level. */
        applyGate(motor_on && (strength != 0u));
        next_toggle_ms = now_ms + half_period_ms;
    }
}

bool VibrationMotor_isOn(void)
{
    return motor_on;
}

uint8_t VibrationMotor_strength(void)
{
    return strength;
}
