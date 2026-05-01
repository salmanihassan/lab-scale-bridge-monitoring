#include <stdint.h>
#include <stddef.h>
#include <unistd.h>  /* for usleep */

/* Driver Header files */
#include <ti/drivers/GPIO.h>
#include <ti/drivers/UART2.h>

/* Driver configuration */
#include "ti_drivers_config.h"



void *mainThread(void *arg0)
{
    char msg[] = "Hello from CC3220SF!\r\n";
    UART2_Handle uart;
    UART2_Params uartParams;

    /* Initialize drivers */
    GPIO_init();

    /* Configure LED pin as output, starting LOW (off) */
    GPIO_setConfig(CONFIG_GPIO_LED_0, GPIO_CFG_OUT_STD | GPIO_CFG_OUT_LOW);

    /* Setup UART */
    UART2_Params_init(&uartParams);
    uartParams.baudRate = 115200;
    uart = UART2_open(CONFIG_UART2_0, &uartParams);

    while (1)
    {
        /* Toggle the LED */
        GPIO_toggle(CONFIG_GPIO_LED_0);

        /* Print over serial */
        UART2_write(uart, msg, sizeof(msg) - 1, NULL);

        /* Wait 500ms */
        usleep(500000);
    }

    return (NULL);
}
