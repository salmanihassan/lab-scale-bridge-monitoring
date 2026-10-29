#include "dt_hmac.h"

#include <string.h>

typedef struct {
    uint32_t state[8];
    uint64_t bits;
    uint8_t buf[64];
    size_t used;
} Sha256;

static const uint32_t K[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u, 0xab1c5ed5u,
    0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu, 0x9bdc06a7u, 0xc19bf174u,
    0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu, 0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau,
    0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u, 0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u,
    0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu, 0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u,
    0xa2bfe8a1u, 0xa81a664bu, 0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u,
    0x19a4c116u, 0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u, 0xc67178f2u
};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32u - (n))))

static void transform(Sha256 *s, const uint8_t *p)
{
    uint32_t w[64], a, b, c, d, e, f, g, h;
    unsigned i;

    for (i = 0u; i < 16u; ++i) {
        w[i] = ((uint32_t)p[4u * i] << 24) | ((uint32_t)p[4u * i + 1u] << 16) |
               ((uint32_t)p[4u * i + 2u] << 8) | (uint32_t)p[4u * i + 3u];
    }
    for (i = 16u; i < 64u; ++i) {
        const uint32_t s0 = ROR(w[i - 15u], 7) ^ ROR(w[i - 15u], 18) ^ (w[i - 15u] >> 3);
        const uint32_t s1 = ROR(w[i - 2u], 17) ^ ROR(w[i - 2u], 19) ^ (w[i - 2u] >> 10);
        w[i] = w[i - 16u] + s0 + w[i - 7u] + s1;
    }
    a = s->state[0]; b = s->state[1]; c = s->state[2]; d = s->state[3];
    e = s->state[4]; f = s->state[5]; g = s->state[6]; h = s->state[7];
    for (i = 0u; i < 64u; ++i) {
        const uint32_t t1 = h + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        const uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    s->state[0] += a; s->state[1] += b; s->state[2] += c; s->state[3] += d;
    s->state[4] += e; s->state[5] += f; s->state[6] += g; s->state[7] += h;
}

static void init(Sha256 *s)
{
    static const uint32_t iv[8] = {
        0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
        0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u
    };
    memcpy(s->state, iv, sizeof(iv));
    s->bits = 0u;
    s->used = 0u;
}

static void update(Sha256 *s, const uint8_t *p, size_t n)
{
    s->bits += (uint64_t)n * 8u;
    while (n > 0u) {
        size_t take = 64u - s->used;
        if (take > n) {
            take = n;
        }
        memcpy(&s->buf[s->used], p, take);
        s->used += take;
        p += take;
        n -= take;
        if (s->used == 64u) {
            transform(s, s->buf);
            s->used = 0u;
        }
    }
}

static void final(Sha256 *s, uint8_t out[32])
{
    const uint64_t bits = s->bits;
    static const uint8_t pad0 = 0x00u;
    const uint8_t pad80 = 0x80u;
    uint8_t len[8];
    unsigned i;

    update(s, &pad80, 1u);
    while (s->used != 56u) {
        update(s, &pad0, 1u);
    }
    for (i = 0u; i < 8u; ++i) {
        len[i] = (uint8_t)(bits >> (56u - 8u * i));
    }
    update(s, len, 8u);
    for (i = 0u; i < 8u; ++i) {
        out[4u * i] = (uint8_t)(s->state[i] >> 24);
        out[4u * i + 1u] = (uint8_t)(s->state[i] >> 16);
        out[4u * i + 2u] = (uint8_t)(s->state[i] >> 8);
        out[4u * i + 3u] = (uint8_t)s->state[i];
    }
}

void DT_hmacSha256(const uint8_t *key, size_t keyLen,
                   const uint8_t *msg, size_t msgLen,
                   uint8_t out[DT_SHA256_DIGEST_SIZE])
{
    Sha256 s;
    uint8_t k[64];
    uint8_t pad[64];
    uint8_t inner[32];
    unsigned i;

    memset(k, 0, sizeof(k));
    if (keyLen > 64u) {
        init(&s);
        update(&s, key, keyLen);
        final(&s, k);
    } else {
        memcpy(k, key, keyLen);
    }

    for (i = 0u; i < 64u; ++i) {
        pad[i] = (uint8_t)(k[i] ^ 0x36u);
    }
    init(&s);
    update(&s, pad, 64u);
    update(&s, msg, msgLen);
    final(&s, inner);

    for (i = 0u; i < 64u; ++i) {
        pad[i] = (uint8_t)(k[i] ^ 0x5cu);
    }
    init(&s);
    update(&s, pad, 64u);
    update(&s, inner, 32u);
    final(&s, out);

    memset(k, 0, sizeof(k));
    memset(pad, 0, sizeof(pad));
}

void DT_toHex(const uint8_t *bytes, size_t len, char *hex)
{
    static const char digits[] = "0123456789abcdef";
    size_t i;

    for (i = 0u; i < len; ++i) {
        hex[2u * i] = digits[bytes[i] >> 4];
        hex[2u * i + 1u] = digits[bytes[i] & 0x0Fu];
    }
    hex[2u * len] = '\0';
}
