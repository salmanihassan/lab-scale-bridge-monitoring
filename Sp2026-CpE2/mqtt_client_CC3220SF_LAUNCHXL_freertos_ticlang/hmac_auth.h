/*
 * hmac_auth.h -- Self-contained HMAC-SHA256 for CC3220SF telemetry authentication
 *
 * Header-only implementation: all functions are static so no CCS build
 * configuration changes are required.  Just #include "hmac_auth.h".
 *
 * SHA-256 core follows FIPS 180-4.
 * HMAC wrapper follows RFC 2104.
 */

#ifndef HMAC_AUTH_H
#define HMAC_AUTH_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* ------------------------------------------------------------------ */
/*  Pre-shared key (PSK) -- 32 bytes                                  */
/*  Must match the key in host_receiver.py exactly.                   */
/* ------------------------------------------------------------------ */
static const uint8_t HMAC_KEY[32] = {
    0x4d, 0x79, 0x53, 0x65, 0x63, 0x75, 0x72, 0x65,  /* MySe cure */
    0x44, 0x69, 0x67, 0x69, 0x74, 0x61, 0x6c, 0x54,  /* Digi talT */
    0x77, 0x69, 0x6e, 0x4b, 0x65, 0x79, 0x32, 0x30,  /* winK ey20 */
    0x32, 0x36, 0x21, 0x40, 0x23, 0x24, 0x25, 0x5e    /* 26!@ #$%^ */
};

/* ------------------------------------------------------------------ */
/*  SHA-256 implementation (FIPS 180-4)                               */
/* ------------------------------------------------------------------ */

#define SHA256_BLOCK_SIZE  64
#define SHA256_DIGEST_SIZE 32

typedef struct {
    uint32_t state[8];
    uint64_t bitcount;
    uint8_t  buffer[SHA256_BLOCK_SIZE];
} sha256_ctx;

/**
 * Long-term plan: In Week 10,
 * the key will be provisioned through the CC3220SF's secure file system at boot time rather than compiled into the source code.
 * Eventually each device would have its own unique key derived from a master secret, with rotation support.
 */
static const uint32_t sha256_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
    0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
    0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
    0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
    0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
    0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
};

#define ROR32(x, n) (((x) >> (n)) | ((x) << (32 - (n))))
#define CH(x, y, z)  (((x) & (y)) ^ (~(x) & (z)))
#define MAJ(x, y, z) (((x) & (y)) ^ ((x) & (z)) ^ ((y) & (z)))
#define EP0(x)  (ROR32(x, 2)  ^ ROR32(x, 13) ^ ROR32(x, 22))
#define EP1(x)  (ROR32(x, 6)  ^ ROR32(x, 11) ^ ROR32(x, 25))
#define SIG0(x) (ROR32(x, 7)  ^ ROR32(x, 18) ^ ((x) >> 3))
#define SIG1(x) (ROR32(x, 17) ^ ROR32(x, 19) ^ ((x) >> 10))

static void sha256_transform(sha256_ctx *ctx, const uint8_t block[64])
{
    uint32_t w[64], a, b, c, d, e, f, g, h, t1, t2;
    int i;

    for (i = 0; i < 16; i++) {
        w[i] = ((uint32_t)block[i * 4] << 24) |
               ((uint32_t)block[i * 4 + 1] << 16) |
               ((uint32_t)block[i * 4 + 2] << 8) |
               ((uint32_t)block[i * 4 + 3]);
    }
    for (i = 16; i < 64; i++) {
        w[i] = SIG1(w[i - 2]) + w[i - 7] + SIG0(w[i - 15]) + w[i - 16];
    }

    a = ctx->state[0]; b = ctx->state[1];
    c = ctx->state[2]; d = ctx->state[3];
    e = ctx->state[4]; f = ctx->state[5];
    g = ctx->state[6]; h = ctx->state[7];

    for (i = 0; i < 64; i++) {
        t1 = h + EP1(e) + CH(e, f, g) + sha256_k[i] + w[i];
        t2 = EP0(a) + MAJ(a, b, c);
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }

    ctx->state[0] += a; ctx->state[1] += b;
    ctx->state[2] += c; ctx->state[3] += d;
    ctx->state[4] += e; ctx->state[5] += f;
    ctx->state[6] += g; ctx->state[7] += h;
}

static void sha256_init(sha256_ctx *ctx)
{
    ctx->bitcount = 0;
    ctx->state[0] = 0x6a09e667; ctx->state[1] = 0xbb67ae85;
    ctx->state[2] = 0x3c6ef372; ctx->state[3] = 0xa54ff53a;
    ctx->state[4] = 0x510e527f; ctx->state[5] = 0x9b05688c;
    ctx->state[6] = 0x1f83d9ab; ctx->state[7] = 0x5be0cd19;
}

static void sha256_update(sha256_ctx *ctx, const uint8_t *data, size_t len)
{
    size_t i;
    size_t idx = (size_t)((ctx->bitcount / 8) % SHA256_BLOCK_SIZE);

    ctx->bitcount += (uint64_t)len * 8;

    for (i = 0; i < len; i++) {
        ctx->buffer[idx++] = data[i];
        if (idx == SHA256_BLOCK_SIZE) {
            sha256_transform(ctx, ctx->buffer);
            idx = 0;
        }
    }
}

static void sha256_final(sha256_ctx *ctx, uint8_t digest[SHA256_DIGEST_SIZE])
{
    size_t idx = (size_t)((ctx->bitcount / 8) % SHA256_BLOCK_SIZE);
    int i;

    ctx->buffer[idx++] = 0x80;

    if (idx > 56) {
        while (idx < SHA256_BLOCK_SIZE)
            ctx->buffer[idx++] = 0x00;
        sha256_transform(ctx, ctx->buffer);
        idx = 0;
    }

    while (idx < 56)
        ctx->buffer[idx++] = 0x00;

    for (i = 7; i >= 0; i--)
        ctx->buffer[idx++] = (uint8_t)(ctx->bitcount >> (i * 8));

    sha256_transform(ctx, ctx->buffer);

    for (i = 0; i < 8; i++) {
        digest[i * 4]     = (uint8_t)(ctx->state[i] >> 24);
        digest[i * 4 + 1] = (uint8_t)(ctx->state[i] >> 16);
        digest[i * 4 + 2] = (uint8_t)(ctx->state[i] >> 8);
        digest[i * 4 + 3] = (uint8_t)(ctx->state[i]);
    }
}

/* ------------------------------------------------------------------ */
/*  HMAC-SHA256 (RFC 2104)                                            */
/* ------------------------------------------------------------------ */

static void hmac_sha256(const uint8_t *key, size_t key_len,
                        const uint8_t *msg, size_t msg_len,
                        uint8_t out[SHA256_DIGEST_SIZE])
{
    sha256_ctx ctx;
    uint8_t k_pad[SHA256_BLOCK_SIZE];
    uint8_t tk[SHA256_DIGEST_SIZE];
    size_t i;

    /* Keys longer than block size are hashed first */
    if (key_len > SHA256_BLOCK_SIZE) {
        sha256_init(&ctx);
        sha256_update(&ctx, key, key_len);
        sha256_final(&ctx, tk);
        key = tk;
        key_len = SHA256_DIGEST_SIZE;
    }

    /* Inner pass: H((K ^ ipad) || message) */
    memset(k_pad, 0x36, SHA256_BLOCK_SIZE);
    for (i = 0; i < key_len; i++)
        k_pad[i] ^= key[i];

    sha256_init(&ctx);
    sha256_update(&ctx, k_pad, SHA256_BLOCK_SIZE);
    sha256_update(&ctx, msg, msg_len);
    sha256_final(&ctx, out);

    /* Outer pass: H((K ^ opad) || inner_hash) */
    memset(k_pad, 0x5c, SHA256_BLOCK_SIZE);
    for (i = 0; i < key_len; i++)
        k_pad[i] ^= key[i];

    sha256_init(&ctx);
    sha256_update(&ctx, k_pad, SHA256_BLOCK_SIZE);
    sha256_update(&ctx, out, SHA256_DIGEST_SIZE);
    sha256_final(&ctx, out);
}

/* ------------------------------------------------------------------ */
/*  Utility: binary digest -> lowercase hex string                    */
/* ------------------------------------------------------------------ */

static void bytes_to_hex(const uint8_t *bytes, size_t len, char *hex_str)
{
    static const char hex_chars[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < len; i++) {
        hex_str[i * 2]     = hex_chars[(bytes[i] >> 4) & 0x0F];
        hex_str[i * 2 + 1] = hex_chars[bytes[i] & 0x0F];
    }
    hex_str[len * 2] = '\0';
}

#endif /* HMAC_AUTH_H */
