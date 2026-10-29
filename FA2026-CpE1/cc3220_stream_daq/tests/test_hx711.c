#include "../src/loadcells.c"
#include "sim.h"
#include <stdio.h>
int main(void) {
    int32_t vals[] = {0, 1, -1, 123456, -123456, 8388607, -8388608, 500000, -2};
    double ovs[] = {0.05, 0.3, 1.0, 1.5};
    int fails = 0, n = 0; double worst_high = 0, worst_crit = 0;
    HX711_init();
    for (unsigned o = 0; o < 4; o++) for (int ef = 0; ef < 3; ef++) for (unsigned k = 0; k < sizeof vals / sizeof *vals; k++) {
        int32_t got = 12345678; bool ok;
        sim_reset(); ov_write_us = ovs[o]; ov_read_us = ovs[o]; edge_frac = ef / 2.0;
        hx_load(0, vals[k]);
        ok = readDevice(&devices[0], &got);
        n++;
        if (!ok || got != vals[k] || hx_powerdown) { fails++; printf("FAIL ov=%.2f ef=%d v=%ld got=%ld ok=%d pd=%d\n", ovs[o], ef, (long)vals[k], (long)got, ok, hx_powerdown); }
        if (hx_max_high_us > worst_high) worst_high = hx_max_high_us;
        if (crit_max_us > worst_crit) worst_crit = crit_max_us;
    }
    /* not ready -> poll returns no fresh, waitAndRead times out */
    { HX711_Readings r = {0}; int32_t raw; sim_reset(); HX711_poll(&r);
      if (r.fresh[0] || r.valid[0] || r.fresh[1]) { fails++; puts("FAIL not-ready poll"); }
      double t0 = now_us(); bool ok = HX711_waitAndRead(1, 50, &raw);
      if (ok || now_us() - t0 < 50000) { fails++; puts("FAIL waitAndRead timeout"); }
      hx_load(1, -777); HX711_poll(&r);
      if (!r.fresh[1] || r.raw[1] != -777 || r.fresh[0]) { fails++; puts("FAIL poll device 2"); }
      HX711_poll(&r); if (r.fresh[1] || !r.valid[1] || r.raw[1] != -777) { fails++; puts("FAIL fresh flag clear / value hold"); }
    }
    printf("HX711: %d/%d read cases pass, max SCK high %.2f us (limit 60), max interrupts-off %.1f us\n", n - (fails), n, worst_high, worst_crit);
    return fails != 0;
}
