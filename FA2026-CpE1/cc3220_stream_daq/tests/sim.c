#include "sim.h"
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include "ti/drivers/GPIO.h"
#include "ti/drivers/dpl/HwiP.h"
#include "ti/drivers/dpl/ClockP.h"
#include "FreeRTOS.h"
#include "task.h"
#include "timing.h"

uint64_t sim_cyc;
double ov_setcfg_us = 2, ov_write_us = 0.3, ov_read_us = 0.3, edge_frac = 0.5;
static void adv_us(double us) { sim_cyc += (uint64_t)(us * 80.0 + 0.5); }
double now_us(void) { return sim_cyc / 80.0; }

static int crit_depth; static uint64_t crit_start; double crit_max_us;
uintptr_t HwiP_disable(void) { if (crit_depth++ == 0) crit_start = sim_cyc; return 0; }
void HwiP_restore(uintptr_t k) { (void)k; if (--crit_depth == 0) { double d = (sim_cyc - crit_start) / 80.0; if (d > crit_max_us) crit_max_us = d; } }

bool Timing_init(void) { return true; }
bool Timing_cycleCounterOk(void) { return true; }
uint32_t Timing_now(void) { return (uint32_t)sim_cyc; }
void Timing_waitUntil(uint32_t start, uint32_t us) {
    uint32_t el = (uint32_t)sim_cyc - start, target = us * 80u;
    if (el < target) sim_cyc += target - el;
}
void Timing_delayUs(uint32_t us) { Timing_waitUntil(Timing_now(), us); }
uint32_t Timing_elapsedUs(uint32_t s, uint32_t e) { return (e - s) / 80u; }
void ClockP_usleep(uint32_t us) { adv_us(us); }
TickType_t xTaskGetTickCount(void) { return (TickType_t)(now_us() / 1000); }
void vTaskDelay(TickType_t t) { adv_us(t * 1000.0); }
void vTaskDelayUntil(TickType_t *w, TickType_t t) { *w += t; }

/* ---------------- HX711 model: dout pins 2,4 clk pins 3,5 */
typedef struct { int32_t value; int ready, pulses, sck, dout; uint64_t rise; } hx_t;
static hx_t hx[2];
double hx_max_high_us; int hx_powerdown;
void hx_load(int i, int32_t v) { hx[i].value = v; hx[i].ready = 1; hx[i].pulses = 0; hx[i].dout = 0; }
static void hx_clk(int i, int v) {
    hx_t *h = &hx[i];
    if (v && !h->sck) {
        h->sck = 1; h->rise = sim_cyc; h->pulses++;
        if (h->ready && h->pulses <= 24) h->dout = (int)((((uint32_t)h->value & 0xFFFFFFu) >> (24 - h->pulses)) & 1u);
        if (h->pulses == 25) { h->dout = 1; h->ready = 0; }
    } else if (!v && h->sck) {
        double high = (sim_cyc - h->rise) / 80.0;
        if (high > hx_max_high_us) hx_max_high_us = high;
        if (high > 60.0) hx_powerdown = 1;
        h->sck = 0;
    }
}

/* ---------------- 1-Wire model, pins 6,7,8 */
enum { OW_IDLE, OW_ROM, OW_CMD, OW_READ, OW_CONV };
typedef struct {
    int present, stuck, master_low, st, bitcnt, rbit; uint8_t byte; uint8_t sp[9];
    uint64_t t_fall, t_rise, t_prev_fall, t_reset_release, dev_from, dev_until; double hold_us;
} ow_t;
static ow_t ow[3];
int ow_errors; char ow_err[256]; double ow_w1_max, ow_w0_min = 1e9, ow_slot_min = 1e9, ow_rd_low_max;
int ow_last_cmd = -1;
static void owerr(const char *fmt, ...) { va_list a; ow_errors++; if (ow_errors == 1) { va_start(a, fmt); vsnprintf(ow_err, sizeof ow_err, fmt, a); va_end(a); } }
void ow_setup(int pin, int present, double hold_us, const uint8_t sp[9]) {
    ow_t *o = &ow[pin - 6]; memset(o, 0, sizeof *o); o->present = present; o->hold_us = hold_us;
    if (sp) memcpy(o->sp, sp, 9);
}
void ow_stuck_low(int pin, int on) { ow[pin - 6].stuck = on; }
static void ow_fall(ow_t *o) {
    if (o->t_prev_fall && o->st != OW_IDLE) {
        double slot = (sim_cyc - o->t_prev_fall) / 80.0;
        if (slot < ow_slot_min) ow_slot_min = slot;
        if (slot < 61.0) owerr("slot too short %.2f us", slot);
    }
    if (o->t_reset_release && (sim_cyc - o->t_reset_release) / 80.0 < 480.0) owerr("fall %.1f us after reset release (<480)", (sim_cyc - o->t_reset_release) / 80.0);
    o->t_reset_release = 0;
    o->t_fall = sim_cyc; o->t_prev_fall = sim_cyc; o->master_low = 1;
    if (o->st == OW_READ && o->rbit < 72) {
        int bit = (o->sp[o->rbit / 8] >> (o->rbit % 8)) & 1; o->rbit++;
        if (!bit) { o->dev_from = sim_cyc; o->dev_until = sim_cyc + (uint64_t)(o->hold_us * 80); }
    }
}
static void ow_rise(ow_t *o) {
    double low = (sim_cyc - o->t_fall) / 80.0;
    o->master_low = 0; o->t_rise = sim_cyc;
    if (low >= 480.0) {
        o->t_prev_fall = 0; o->t_reset_release = sim_cyc;
        if (o->present) { o->dev_from = sim_cyc + 30 * 80; o->dev_until = sim_cyc + 150 * 80; o->st = OW_ROM; o->bitcnt = 0; o->byte = 0; }
        return;
    }
    if (low < 1.0) owerr("low pulse %.2f us < 1", low);
    if (o->st == OW_ROM || o->st == OW_CMD) {
        int bit;
        if (low <= 15.0) { bit = 1; if (low > ow_w1_max) ow_w1_max = low; }
        else if (low >= 60.0) { bit = 0; if (low < ow_w0_min) ow_w0_min = low; }
        else { owerr("ambiguous write low %.2f us", low); bit = 0; }
        o->byte |= (uint8_t)(bit << o->bitcnt);
        if (++o->bitcnt == 8) {
            if (o->st == OW_ROM) { if (o->byte != 0xCC) owerr("ROM cmd %02X", o->byte); o->st = OW_CMD; }
            else { ow_last_cmd = o->byte; if (o->byte == 0xBE) { o->st = OW_READ; o->rbit = 0; } else if (o->byte == 0x44) o->st = OW_CONV; else owerr("cmd %02X", o->byte); }
            o->bitcnt = 0; o->byte = 0;
        }
    } else if (o->st == OW_READ) {
        if (low > ow_rd_low_max) ow_rd_low_max = low;
        if (low > 15.0) owerr("read slot master low %.2f us > 15", low);
    }
}
static int ow_level(ow_t *o) {
    if (o->stuck || o->master_low) return 0;
    if (o->present && sim_cyc >= o->dev_from && sim_cyc < o->dev_until) return 0;
    if (o->t_rise && (sim_cyc - o->t_rise) < 40) return 0; /* 0.5 us RC rise */
    return 1;
}

/* ---------------- GPIO */
static int outmode[16];
void GPIO_init(void) {}
int GPIO_setConfig(uint_least8_t pin, GPIO_PinConfig cfg) {
    adv_us(ov_setcfg_us * edge_frac);
    if (pin >= 6 && pin <= 8) {
        ow_t *o = &ow[pin - 6];
        int drive = (cfg & GPIO_CFG_OUTPUT) != 0;
        if (drive && !o->master_low) ow_fall(o); else if (!drive && o->master_low) ow_rise(o);
    }
    outmode[pin] = (cfg & GPIO_CFG_OUTPUT) != 0;
    adv_us(ov_setcfg_us * (1 - edge_frac));
    return 0;
}
void GPIO_write(uint_least8_t pin, unsigned int v) {
    adv_us(ov_write_us * edge_frac);
    if (pin == 3) hx_clk(0, v != 0); else if (pin == 5) hx_clk(1, v != 0);
    adv_us(ov_write_us * (1 - edge_frac));
}
uint_fast8_t GPIO_read(uint_least8_t pin) {
    int lv = 1;
    adv_us(ov_read_us / 2);
    if (pin == 2) lv = hx[0].ready ? hx[0].dout : 1;
    else if (pin == 4) lv = hx[1].ready ? hx[1].dout : 1;
    else if (pin >= 6 && pin <= 8) lv = ow_level(&ow[pin - 6]);
    adv_us(ov_read_us / 2);
    return (uint_fast8_t)lv;
}
void sim_reset(void) {
    memset(hx, 0, sizeof hx); hx_max_high_us = 0; hx_powerdown = 0; crit_max_us = 0;
    ow_errors = 0; ow_err[0] = 0; ow_w1_max = 0; ow_w0_min = 1e9; ow_slot_min = 1e9; ow_rd_low_max = 0; ow_last_cmd = -1;
}
