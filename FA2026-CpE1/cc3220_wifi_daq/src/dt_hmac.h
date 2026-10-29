#ifndef DT_HMAC_H_
#define DT_HMAC_H_

/*
 * SHA-256 (FIPS 180-4) and HMAC-SHA256 (RFC 2104), portable C, no key inside.
 * Checked against the RFC 4231 test vectors in tests/test_hmac.c.
 */

#include <stddef.h>
#include <stdint.h>

#define DT_SHA256_DIGEST_SIZE 32u

void DT_hmacSha256(const uint8_t *key, size_t keyLen,
                   const uint8_t *msg, size_t msgLen,
                   uint8_t out[DT_SHA256_DIGEST_SIZE]);

/* Writes 2*len lowercase hex characters plus a terminating NUL. */
void DT_toHex(const uint8_t *bytes, size_t len, char *hex);

#endif /* DT_HMAC_H_ */
