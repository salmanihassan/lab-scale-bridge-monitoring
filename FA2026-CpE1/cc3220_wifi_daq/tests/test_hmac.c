/*
 * RFC 4231 HMAC-SHA256 test vectors for src/dt_hmac.c.
 *   gcc -std=c99 -Wall -I../src -o test_hmac test_hmac.c ../src/dt_hmac.c && ./test_hmac
 */
#include <stdio.h>
#include <string.h>

#include "dt_hmac.h"

static int run(const char *name, const uint8_t *key, size_t kl, const uint8_t *msg, size_t ml,
               const char *expect)
{
    uint8_t mac[32];
    char hex[65];

    DT_hmacSha256(key, kl, msg, ml, mac);
    DT_toHex(mac, 32u, hex);
    printf("%s %s\n", strcmp(hex, expect) == 0 ? "PASS" : "FAIL", name);
    return strcmp(hex, expect) != 0;
}

int main(void)
{
    uint8_t k1[20], k2[] = "Jefe", k3[20], k4[25], k6[131];
    uint8_t m3[50], m4[50];
    int fails = 0;
    unsigned i;

    memset(k1, 0x0b, sizeof(k1));
    memset(k3, 0xaa, sizeof(k3));
    memset(m3, 0xdd, sizeof(m3));
    for (i = 0; i < 25; ++i) { k4[i] = (uint8_t)(i + 1); }
    memset(m4, 0xcd, sizeof(m4));
    memset(k6, 0xaa, sizeof(k6));

    fails += run("RFC4231 case 1", k1, 20, (const uint8_t *)"Hi There", 8,
                 "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7");
    fails += run("RFC4231 case 2", k2, 4, (const uint8_t *)"what do ya want for nothing?", 28,
                 "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843");
    fails += run("RFC4231 case 3", k3, 20, m3, 50,
                 "773ea91e36800e46854db8ebd09181a72959098b3ef8c122d9635514ced565fe");
    fails += run("RFC4231 case 4", k4, 25, m4, 50,
                 "82558a389a443c0ea4cc819899f2083a85f0faa3e578f8077a2e3ff46729665b");
    fails += run("RFC4231 case 6 (key > block)", k6, 131,
                 (const uint8_t *)"Test Using Larger Than Block-Size Key - Hash Key First", 54,
                 "60e431591ee0b67f0d8a26aacbf5b77f8e0bc6213728c5140546040f0ee37f54");
    fails += run("RFC4231 case 7 (key and data > block)", k6, 131,
                 (const uint8_t *)"This is a test using a larger than block-size key and a larger than "
                 "block-size data. The key needs to be hashed before being used by the HMAC algorithm.", 152,
                 "9b09ffa71b942fcb27635fbcd5b0e944bfdc63644f0713938a7f51535c3a35e2");
    printf("%s\n", fails ? "FAILED" : "ALL PASS");
    return fails != 0;
}
