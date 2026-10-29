#ifndef PAYLOAD_H_
#define PAYLOAD_H_

#include <stddef.h>
#include <stdint.h>

#include "dt_batch.h"

#define DT_SCHEMA            "dt-batch/1.1"
#define DT_PAYLOAD_MAX       6144u   /* worst case for 100 samples is about 5,100 bytes */

/* ,"mac":"<64 hex>"} replaces the closing brace: 8 + 64 + 2 characters. */
#define DT_MAC_TAIL_LEN      74u

/*
 * Encodes one batch as JSON (see README, "Packet format"). kid names the
 * HMAC key that will sign it and is part of the signed bytes.
 * Returns the length written (without the terminating NUL), or -1 if the
 * buffer was too small, in which case nothing should be published.
 */
int Payload_encode(const DT_Batch *b, const char *device_id, const char *kid,
                   uint32_t boot_id, uint32_t uptime_ms, char *out, size_t cap);

/*
 * Signs an encoded payload in place. The HMAC-SHA256 covers every byte
 * before the closing brace, which is then replaced by ,"mac":"<hex>"}.
 * A receiver therefore verifies the bytes before the last ,"mac":" exactly
 * as they arrived, with no JSON re-serialisation.
 * Returns the new length, or -1 if len is not a payload or cap is too small.
 */
int Payload_sign(char *out, int len, size_t cap, const uint8_t *key, size_t keyLen);

#endif /* PAYLOAD_H_ */
