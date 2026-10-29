#include "../src/temperature.c"
#include <string.h>
#include "sim.h"
#include <stdio.h>
static void make_sp(uint8_t sp[9], int16_t raw) {
    sp[0] = (uint8_t)raw; sp[1] = (uint8_t)((uint16_t)raw >> 8); sp[2] = 0x4B; sp[3] = 0x46; sp[4] = 0x7F; sp[5] = 0xFF; sp[6] = 0x0F; sp[7] = 0x10;
    sp[8] = crc8(sp, 8);
}
int main(void) {
    int fails = 0;
    /* CRC against Maxim AN27 example ROM: 02 1C B8 01 00 00 00 -> A2 */
    { uint8_t rom[7] = {0x02, 0x1C, 0xB8, 0x01, 0x00, 0x00, 0x00}; uint8_t c = crc8(rom, 7);
      printf("crc8 known vector: %02X (expect A2) %s\n", c, c == 0xA2 ? "PASS" : "FAIL"); if (c != 0xA2) fails++; }
    { uint8_t ff[8]; memset(ff, 0xFF, 8); uint8_t c = crc8(ff, 8); printf("crc8 of 8x FF = %02X (must not be FF) %s\n", c, c != 0xFF ? "PASS" : "FAIL"); if (c == 0xFF) fails++; }
    double ovs[] = {0.5, 1, 2, 3, 4, 5, 6, 8, 10};
    double holds[] = {15, 30};
    int16_t raws[] = {401, -162, 0x07D0, 0};  /* 25.0625, -10.125, 125.0, 0.0 */
    printf("setConfig_us  edge  hold_us : result\n");
    for (unsigned h = 0; h < 2; h++) for (unsigned o = 0; o < sizeof ovs / sizeof *ovs; o++) for (int ef = 0; ef < 3; ef++) {
        int ok_all = 1; char why[300] = "";
        double cm = 0;
        for (unsigned k = 0; k < 4; k++) {
            uint8_t sp[9]; float v = -999; ReadResult r;
            make_sp(sp, raws[k]); sim_reset(); ov_setcfg_us = ovs[o]; edge_frac = ef / 2.0;
            ow_setup(6, 1, holds[h], sp);
            if (!startConversion(6) || ow_last_cmd != 0x44) { ok_all = 0; snprintf(why, sizeof why, "convert failed: %s", ow_err); break; }
            r = readTemperature(6, &v);
            if (r != READ_OK || v != raws[k] / 16.0f || ow_errors) { ok_all = 0; snprintf(why, sizeof why, "raw %d: result %d v=%.4f model: %s", raws[k], r, v, ow_errors ? ow_err : "-"); break; }
            if (crit_max_us > cm) cm = crit_max_us;
        }
        printf("%6.1f  %4.1f  %4.0f : %s  (w1 low max %.1f, w0 low min %.1f, read low max %.1f, slot min %.1f, irq-off max %.0f us) %s\n",
               ovs[o], ef / 2.0, holds[h], ok_all ? "PASS" : "FAIL", ow_w1_max, ow_w0_min, ow_rd_low_max, ow_slot_min, cm, why);
        if (!ok_all && ovs[o] <= 4) fails++;
    }
    /* absent probe, stuck-low bus */
    { float v; sim_reset(); ov_setcfg_us = 2; ow_setup(7, 0, 30, NULL);
      ReadResult r = readTemperature(7, &v); printf("absent probe -> %s\n", r == READ_NO_PRESENCE ? "NO_PRESENCE PASS" : "FAIL"); if (r != READ_NO_PRESENCE) fails++;
      ow_setup(8, 1, 30, NULL); ow_stuck_low(8, 1); r = readTemperature(8, &v); printf("stuck-low bus -> %s\n", r == READ_NO_PRESENCE ? "NO_PRESENCE PASS" : "FAIL"); if (r != READ_NO_PRESENCE) fails++; }
    /* all-zero scratchpad from a device answering with zeros */
    { uint8_t z[9] = {0}; float v; sim_reset(); ow_setup(6, 1, 30, z); startConversion(6);
      ReadResult r = readTemperature(6, &v); printf("all-zero scratchpad -> %s\n", r == READ_CRC_ERROR ? "rejected PASS" : "FAIL"); if (r != READ_CRC_ERROR) fails++; }
    return fails != 0;
}
