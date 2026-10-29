#include <stdint.h>
#include <stdbool.h>
extern uint64_t sim_cyc;
extern double ov_setcfg_us, ov_write_us, ov_read_us, edge_frac;
extern double crit_max_us;
double now_us(void);
void sim_reset(void);
/* HX711 model */
void hx_load(int i, int32_t v);
extern double hx_max_high_us; extern int hx_powerdown;
/* 1-Wire model */
void ow_setup(int pin, int present, double hold_us, const uint8_t scratch[9]);
void ow_stuck_low(int pin, int on);
extern int ow_errors; extern char ow_err[256]; extern double ow_w1_max, ow_w0_min, ow_slot_min, ow_rd_low_max;
extern int ow_last_cmd;
