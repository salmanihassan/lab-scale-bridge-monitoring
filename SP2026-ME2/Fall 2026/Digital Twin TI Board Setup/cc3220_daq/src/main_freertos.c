#include <stdint.h>
#include <pthread.h>
#include <FreeRTOS.h>
#include <task.h>
#include <ti/drivers/Board.h>

#include "acquisition.h"
#include "board_config.h"

#define MAIN_THREAD_STACK_BYTES 2048u

static void *mainThread(void *arg)
{
    (void)arg;
    Acquisition_run(DT_STARTUP_MODE);
    return NULL;
}

int main(void)
{
    pthread_t thread;
    pthread_attr_t attributes;
    struct sched_param priority;

    Board_init();
    priority.sched_priority = 2;
    (void)pthread_attr_init(&attributes);
    (void)pthread_attr_setschedparam(&attributes, &priority);
    (void)pthread_attr_setdetachstate(&attributes, PTHREAD_CREATE_DETACHED);
    (void)pthread_attr_setstacksize(&attributes, MAIN_THREAD_STACK_BYTES);
    if (pthread_create(&thread, &attributes, mainThread, NULL) != 0) {
        for (;;) { }
    }
    vTaskStartScheduler();
    return 0;
}
