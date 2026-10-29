/*
 * Host test for src/payload.c (any gcc):
 *   gcc -std=c99 -Wall -I../src -o test_payload test_payload.c ../src/payload.c
 *   ./test_payload worst.json typical.json
 * Writes a worst-case batch and a typical batch as signed JSON for
 * test_receiver.py. Test key: bytes 0x00..0x1f, kid "ktest" (test_receiver.py
 * uses the same values).
 *   gcc -std=c99 -Wall -I../src -o test_payload test_payload.c ../src/payload.c ../src/dt_hmac.c
 */
#include <stdio.h>
#include <string.h>

#include "payload.h"

static DT_Batch b;
static uint8_t key[32];
#define KID "ktest"
static char out[DT_PAYLOAD_MAX];

static int writeFile(const char *path, const char *text)
{
    FILE *f = fopen(path, "w");
    if (f == NULL) {
        return -1;
    }
    fputs(text, f);
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    int len, fails = 0;
    unsigned i;

    for (i = 0; i < sizeof(key); ++i) {
        key[i] = (uint8_t)i;
    }

    /* Worst case: widest numbers everywhere. */
    memset(&b, 0, sizeof(b));
    b.seq = 4294967295u;
    b.t0_ms = 4294967295u;
    b.n = DT_BATCH_SAMPLES;
    for (i = 0; i < DT_BATCH_SAMPLES; ++i) {
        b.s[i].dt_ms = 65535u;
        b.s[i].ax = b.s[i].ay = b.s[i].az = -32768;
        b.s[i].l1 = b.s[i].l2 = -8388608;
        b.s[i].flags = DT_SAMPLE_ACCEL_OK | DT_SAMPLE_L1_VALID | DT_SAMPLE_L2_VALID |
                       DT_SAMPLE_L1_NEW | DT_SAMPLE_L2_NEW;
    }
    for (i = 0; i < 3; ++i) {
        b.temp_c[i] = -55.0f;
        b.temp_ok[i] = true;
    }
    b.accel_fail_total = b.late_slots_total = b.dropped_total = 4294967295u;
    b.pub_fail_total = b.not_connected_total = 4294967295u;
    len = Payload_encode(&b, "CC3220SF_NODE_01", KID, 0xFFFFFFFFu, 4294967295u, out, sizeof(out));
    len = Payload_sign(out, len, sizeof(out), key, sizeof(key));
    printf("worst case signed: %d bytes (buffer %u, MQTT buffer 6656)\n", len, (unsigned)sizeof(out));
    if ((len < 0) || (len > 6656 - 64)) {
        puts("FAIL worst case does not fit");
        ++fails;
    } else if (argc > 1) {
        writeFile(argv[1], out);
    }

    /* Too-small buffer must report failure, not overflow. */
    if (Payload_encode(&b, "CC3220SF_NODE_01", KID, 1u, 1u, out, 1000u) != -1) {
        puts("FAIL short buffer not detected");
        ++fails;
    }

    /* Signing must refuse a buffer with no room for the MAC, and a non-payload. */
    {
        static char small[96] = "{\"a\":1}";
        if (Payload_sign(small, 7, 6u + DT_MAC_TAIL_LEN, key, sizeof(key)) != -1) {
            puts("FAIL sign with no room for the terminator not detected");
            ++fails;
        }
        if (Payload_sign(small, 7, 7u + DT_MAC_TAIL_LEN, key, sizeof(key)) != 6 + (int)DT_MAC_TAIL_LEN) {
            puts("FAIL sign into an exactly sized buffer");
            ++fails;
        }
        strcpy(small, "{\"a\":1");
        if (Payload_sign(small, 6, sizeof(small), key, sizeof(key)) != -1) {
            puts("FAIL sign of text without a closing brace not detected");
            ++fails;
        }
    }

    /* Typical: realistic values, one failed accel read, load 2 not yet valid, temp 2 failed. */
    memset(&b, 0, sizeof(b));
    b.seq = 41u;
    b.t0_ms = 123450u;
    b.n = DT_BATCH_SAMPLES;
    for (i = 0; i < DT_BATCH_SAMPLES; ++i) {
        b.s[i].dt_ms = (uint16_t)(i * 10u);
        b.s[i].ax = (int16_t)(-130 + (int)(i % 3u));
        b.s[i].ay = 58;
        b.s[i].az = 208;
        b.s[i].l1 = 319500 + (int32_t)(i % 7u);
        b.s[i].l2 = 639400;
        b.s[i].flags = DT_SAMPLE_ACCEL_OK | DT_SAMPLE_L1_VALID;
        if ((i % 8u) == 0u) {
            b.s[i].flags |= DT_SAMPLE_L1_NEW;
        }
        if (i >= 5u) {
            b.s[i].flags |= DT_SAMPLE_L2_VALID;
        }
    }
    b.s[17].flags &= (uint8_t)~DT_SAMPLE_ACCEL_OK;
    b.temp_c[0] = 30.5f;  b.temp_ok[0] = true;
    b.temp_c[1] = 0.0f;   b.temp_ok[1] = false;
    b.temp_c[2] = 29.69f; b.temp_ok[2] = true;
    b.accel_fail_total = 1u;
    len = Payload_encode(&b, "CC3220SF_NODE_01", KID, 0x1a2b3c4du, 124450u, out, sizeof(out));
    len = Payload_sign(out, len, sizeof(out), key, sizeof(key));
    printf("typical signed: %d bytes\n", len);
    if (len < 0) {
        puts("FAIL typical");
        ++fails;
    } else if (argc > 2) {
        writeFile(argv[2], out);
    }

    printf("%s\n", fails ? "FAILED" : "PASS");
    return fails != 0;
}
