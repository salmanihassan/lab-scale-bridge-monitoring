#ifndef BOARD_CONFIG_H_
#define BOARD_CONFIG_H_

/*
 * Sensor timing for the Wi-Fi build. Pin routing lives in dt_wifi.syscfg and
 * is the same as the serial stream build (FA2026-CpE1/cc3220_stream_daq).
 */

#define DT_ACCEL_I2C_ADDRESS          0x53u
#define DT_SAMPLE_RATE_HZ             100u
#define DT_SAMPLE_PERIOD_MS           (1000u / DT_SAMPLE_RATE_HZ)
#define DT_BATCH_SAMPLES              100u   /* one MQTT packet per second */
#define DT_TEMPERATURE_PERIOD_MS      1000u
#define DT_DS18B20_CONVERSION_MS      750u   /* 12-bit worst case */

/* HX711: SCK high and low time per bit (us). Must stay well under 60 us. */
#define DT_HX711_HALF_CYCLE_US        1u
#define DT_HX711_READY_TIMEOUT_MS     1000u

/* Task priorities (FreeRTOS, 0 = idle, 9 = SimpleLink spawn task).
 * The sampler sits above MQTT (2) and the connection tasks (1) so network
 * work never delays a 10 ms sample. The publisher sits at the MQTT level. */
#define DT_SAMPLER_TASK_PRIORITY      5
#define DT_SAMPLER_TASK_STACK_BYTES   1536u
#define DT_PUBLISH_TASK_PRIORITY      2
#define DT_PUBLISH_TASK_STACK_BYTES   3072u   /* snprintf + HMAC-SHA256 (about 700 B) */

#endif /* BOARD_CONFIG_H_ */
