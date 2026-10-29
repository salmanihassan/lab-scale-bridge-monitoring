/*
 * JSON encoding of one DT_Batch.
 *
 * Every append is a direct snprintf() call with a literal format string, on
 * purpose: the TI Arm Clang linker chooses the printf engine by reading those
 * literals (see the stream firmware README). The "%.2f" for temperatures pulls
 * in the full engine, which the console logging also relies on.
 */
#include "payload.h"

#include <stdio.h>

#include "dt_hmac.h"
#include <string.h>

#define APPEND(buf, cap, len, ...)                                            \
    do {                                                                      \
        if ((len) < (cap)) {                                                  \
            int n_ = snprintf((buf) + (len), (cap) - (len), __VA_ARGS__);     \
            if (n_ < 0) {                                                     \
                (len) = (cap);                                                \
            } else {                                                          \
                (len) += (size_t)n_;                                          \
            }                                                                 \
        }                                                                     \
    } while (0)

int Payload_encode(const DT_Batch *b, const char *device_id, const char *kid,
                   uint32_t boot_id, uint32_t uptime_ms, char *out, size_t cap)
{
    size_t len = 0u;
    uint16_t i;
    uint8_t k;

    if ((b == NULL) || (device_id == NULL) || (kid == NULL) || (out == NULL) || (cap == 0u)) {
        return -1;
    }

    APPEND(out, cap, len,
           "{\"schema\":\"" DT_SCHEMA "\",\"kid\":\"%s\",\"device_id\":\"%s\",\"boot_id\":\"%08lx\","
           "\"seq\":%lu,\"fs_hz\":%u,\"t0_ms\":%lu,\"n\":%u,\"accel_lsb_g\":0.00390625,",
           kid, device_id, (unsigned long)boot_id, (unsigned long)b->seq,
           (unsigned)DT_SAMPLE_RATE_HZ, (unsigned long)b->t0_ms, (unsigned)b->n);

    /* Sample time offsets from t0, in ms. */
    APPEND(out, cap, len, "\"dt_ms\":[");
    for (i = 0u; i < b->n; ++i) {
        APPEND(out, cap, len, "%s%u", (i != 0u) ? "," : "", (unsigned)b->s[i].dt_ms);
    }

    /* Accelerometer raw counts, null where the read failed. */
    for (k = 0u; k < 3u; ++k) {
        static const char *const names[3] = { "ax", "ay", "az" };
        APPEND(out, cap, len, "],\"%s\":[", names[k]);
        for (i = 0u; i < b->n; ++i) {
            const DT_Sample *s = &b->s[i];
            const int16_t v = (k == 0u) ? s->ax : ((k == 1u) ? s->ay : s->az);
            if ((s->flags & DT_SAMPLE_ACCEL_OK) != 0u) {
                APPEND(out, cap, len, "%s%d", (i != 0u) ? "," : "", (int)v);
            } else {
                APPEND(out, cap, len, "%snull", (i != 0u) ? "," : "");
            }
        }
    }

    /* Load cells: raw counts (null until the cell first reports). */
    for (k = 0u; k < 2u; ++k) {
        const uint8_t valid_bit = (k == 0u) ? DT_SAMPLE_L1_VALID : DT_SAMPLE_L2_VALID;
        APPEND(out, cap, len, "],\"l%u\":[", (unsigned)(k + 1u));
        for (i = 0u; i < b->n; ++i) {
            const DT_Sample *s = &b->s[i];
            if ((s->flags & valid_bit) != 0u) {
                APPEND(out, cap, len, "%s%ld", (i != 0u) ? "," : "",
                       (long)((k == 0u) ? s->l1 : s->l2));
            } else {
                APPEND(out, cap, len, "%snull", (i != 0u) ? "," : "");
            }
        }
    }
    APPEND(out, cap, len, "],");

    /* New-conversion markers, one character per sample. */
    for (k = 0u; k < 2u; ++k) {
        const uint8_t new_bit = (k == 0u) ? DT_SAMPLE_L1_NEW : DT_SAMPLE_L2_NEW;
        APPEND(out, cap, len, "\"l%u_new\":\"", (unsigned)(k + 1u));
        if (len + b->n + 3u < cap) {
            for (i = 0u; i < b->n; ++i) {
                out[len++] = ((b->s[i].flags & new_bit) != 0u) ? '1' : '0';
            }
            out[len] = '\0';
        } else {
            len = cap;
        }
        APPEND(out, cap, len, "\",");
    }

    /* Temperatures at the end of the batch (null if the probe failed). */
    APPEND(out, cap, len, "\"temp_c\":[");
    for (k = 0u; k < 3u; ++k) {
        if (b->temp_ok[k]) {
            APPEND(out, cap, len, "%s%.2f", (k != 0u) ? "," : "", (double)b->temp_c[k]);
        } else {
            APPEND(out, cap, len, "%snull", (k != 0u) ? "," : "");
        }
    }

    APPEND(out, cap, len,
           "],\"diag\":{\"uptime_ms\":%lu,\"accel_fail\":%lu,\"late_slots\":%lu,"
           "\"dropped\":%lu,\"pub_fail\":%lu,\"not_connected\":%lu}}",
           (unsigned long)uptime_ms, (unsigned long)b->accel_fail_total,
           (unsigned long)b->late_slots_total, (unsigned long)b->dropped_total,
           (unsigned long)b->pub_fail_total, (unsigned long)b->not_connected_total);

    if (len >= cap) {
        out[cap - 1u] = '\0';
        return -1;
    }
    return (int)len;
}

int Payload_sign(char *out, int len, size_t cap, const uint8_t *key, size_t keyLen)
{
    static const char head[] = ",\"mac\":\"";
    uint8_t mac[DT_SHA256_DIGEST_SIZE];
    size_t body;

    if ((out == NULL) || (key == NULL) || (len < 2) || (out[len - 1] != '}')) {
        return -1;
    }
    body = (size_t)len - 1u;                     /* everything before the closing brace */
    if (body + DT_MAC_TAIL_LEN + 1u > cap) {
        return -1;
    }
    DT_hmacSha256(key, keyLen, (const uint8_t *)out, body, mac);
    memcpy(&out[body], head, sizeof(head) - 1u);
    DT_toHex(mac, sizeof(mac), &out[body + sizeof(head) - 1u]);
    out[body + DT_MAC_TAIL_LEN - 2u] = '"';
    out[body + DT_MAC_TAIL_LEN - 1u] = '}';
    out[body + DT_MAC_TAIL_LEN] = '\0';
    return (int)(body + DT_MAC_TAIL_LEN);
}
