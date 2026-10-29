#ifndef MOCK_GPIO_H
#define MOCK_GPIO_H
#include <stdint.h>
typedef uint32_t GPIO_PinConfig;
#define GPIO_CFG_INPUT    0x1u
#define GPIO_CFG_OUTPUT   0x2u
#define GPIO_CFG_OUT_LOW  0x0u
void GPIO_init(void);
int GPIO_setConfig(uint_least8_t index, GPIO_PinConfig cfg);
uint_fast8_t GPIO_read(uint_least8_t index);
void GPIO_write(uint_least8_t index, unsigned int value);
#endif
