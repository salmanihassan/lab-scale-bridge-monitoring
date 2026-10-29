#include "timing.h"

/* ARMv7-M debug registers (architecturally fixed addresses). */
#define DEMCR          (*(volatile uint32_t *)0xE000EDFCu)
#define DWT_CTRL       (*(volatile uint32_t *)0xE0001000u)
#define DWT_CYCCNT     (*(volatile uint32_t *)0xE0001004u)
#define DEMCR_TRCENA   (1u << 24)
#define DWT_CYCCNTENA  (1u << 0)

#define CYCLES_PER_US  (DT_CPU_HZ / 1000000u)

/* CC32xx driverlib (linked through driverlib.a): about 3 CPU cycles per count. */
extern void UtilsDelay(unsigned long ulCount);

static bool s_dwt_ok;

bool Timing_init(void)
{
    uint32_t before;
    volatile uint32_t spin;

    DEMCR |= DEMCR_TRCENA;
    DWT_CYCCNT = 0u;
    DWT_CTRL |= DWT_CYCCNTENA;

    before = DWT_CYCCNT;
    for (spin = 0u; spin < 200u; ++spin) {
    }
    s_dwt_ok = (DWT_CYCCNT != before);
    return s_dwt_ok;
}

bool Timing_cycleCounterOk(void)
{
    return s_dwt_ok;
}

uint32_t Timing_now(void)
{
    return s_dwt_ok ? DWT_CYCCNT : 0u;
}

void Timing_waitUntil(uint32_t start, uint32_t us)
{
    if (s_dwt_ok) {
        const uint32_t cycles = us * CYCLES_PER_US;
        while ((uint32_t)(DWT_CYCCNT - start) < cycles) {
        }
    } else if (us != 0u) {
        UtilsDelay((unsigned long)((us * CYCLES_PER_US) / 3u));
    }
}

void Timing_delayUs(uint32_t us)
{
    Timing_waitUntil(Timing_now(), us);
}

uint32_t Timing_elapsedUs(uint32_t start, uint32_t end)
{
    return s_dwt_ok ? (uint32_t)(end - start) / CYCLES_PER_US : 0u;
}
