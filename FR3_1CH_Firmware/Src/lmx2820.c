#include "lmx2820.h"
#include "main.h"
#include "spi.h"
#include <string.h>

/* fPD = 10MHz internal TCXO x2 (OSC_2X doubler, baked into the register
 * template below) = 20MHz. PLL_N = floor(VCO_Hz / fPD). */
#define LMX2820_FPD_HZ            20000000ULL
/* VCO fundamental core covers ~5.65-11.3GHz; above that the OUTA_MUX output
 * doubler is used instead, so the VCO itself stays in-band. Crossover is
 * exactly 11.3GHz, direct-mode-inclusive. */
#define LMX2820_CROSSOVER_HZ      11300000000ULL
#define LMX2820_FREQ_MIN_HZ       6000000000ULL
#define LMX2820_FREQ_MAX_HZ       22600000000ULL
/* Power-on/first-boot default frequency - above LMX2820_CROSSOVER_HZ, so a
 * fresh chip-erase boot exercises the output-doubler VCO path rather than
 * direct mode. */
#define LMX2820_DEFAULT_FREQ_HZ   20000000000ULL
/* Fixed denominator used for every frequency that isn't a clean multiple
 * of the PFD, rather than reducing to a smaller one. */
#define LMX2820_PLL_DEN           0x80000002UL

#define LMX2820_REG_COUNT         123U
#define LMX2820_REG_PLL_N         36U
#define LMX2820_REG_PLL_DEN_HI    38U
#define LMX2820_REG_PLL_DEN_LO    39U
#define LMX2820_REG_PLL_NUM_HI    42U
#define LMX2820_REG_PLL_NUM_LO    43U
#define LMX2820_REG_INSTCAL_HI    44U
#define LMX2820_REG_INSTCAL_LO    45U
#define LMX2820_REG_OUTA_MUX_PD   78U
#define LMX2820_REG_OUTA_PWR      79U
#define LMX2820_REG_LOCK_READBACK 74U
#define LMX2820_REG_TEMP_READBACK 76U

#define LMX2820_OUTA_PD_BIT       0x10U
#define LMX2820_OUTA_PWR_BASE     0x0110U

#define LMX2820_MUX_DIRECT        0x01U
#define LMX2820_MUX_DOUBLER       0x02U

/* R0 bit 6: VCO doubler calibration enable. Only meaningful above the
 * 11.3GHz crossover (mux == LMX2820_MUX_DOUBLER); leaving it always-on
 * (the template's POR-inherited default) triggers doubler calibration
 * even in direct mode, causing intermittent "locks on 2nd attempt" failures. */
#define LMX2820_R0_DBLR_CAL_EN_BIT 0x0040U

/* R0 bit 0: full chip powerdown (VCO/PLL/dividers/output), unlike OUTA_PD
 * (mute) which only disables the output buffer and leaks RF. Powering back
 * up needs a full re-init, same as cold boot - see LMX2820_SetMute(). */
#define LMX2820_R0_POWERDOWN_BIT   0x0001U

/* rb_LD readback via R74 is a 2-bit field at bits [15:14]:
 *   00/01 = Unlocked, 10 = Locked, 11 = INVALID.
 * A single-bit (bit 15 only) check would misread INVALID as Locked. */
#define LMX2820_RB_LD_MASK        0x0003U
#define LMX2820_RB_LD_SHIFT       14U
#define LMX2820_RB_LD_LOCKED      0x0002U

/* R19 bits [4:3]: TEMPSENSE_EN (00 = disabled/POR default, 11 = enabled,
 * 01/10 reserved). Template's R19 below (0x2138) has this baked in as
 * permanently enabled - like every other non-frequency-dependent
 * register, it's just always set correctly rather than written separately
 * at read time. */

/* rb_TEMP_SENS via R76 is an 11-bit field at bits [10:0]. Datasheet:
 * Temp_C = 0.85 * code - 415, resolution 0.6C/code, accuracy +-5C. TI has
 * acknowledged on their own E2E forum that this doesn't perfectly match
 * their characterization graph, so treat the result as approximate within
 * that +-5C spec rather than precise. */
#define LMX2820_RB_TEMP_SENS_MASK 0x07FFU

#define LMX2820_LOCK_POLL_ATTEMPTS 20U
#define LMX2820_LOCK_POLL_DELAY_MS 100U

/* Cold-boot calibration is attempt-count-dependent (see LMX2820_Tune()) -
 * retries the full RESET+settle+write+poll sequence this many times before
 * giving up, so an automatic boot-time restore (no user watching to retry
 * it manually) doesn't stay silently unlocked after one unlucky attempt. */
#define LMX2820_COLD_BOOT_RETRY_ATTEMPTS 3U

/* Every register except PLL_N, PLL_DEN, PLL_NUM, INSTCAL_PLL_NUM,
 * OUTA_MUX/PD, and OUTA_PWR is constant across the full 6-22.6GHz range.
 * Those 9 frequency-dependent slots are overwritten by LMX2820_Tune()
 * before every write, so their values here are placeholders. */
static const uint16_t lmx2820_template[LMX2820_REG_COUNT] =
{
  /* R0  */ 0x6070, /* R1  */ 0x57A0, /* R2  */ 0x81F4, /* R3  */ 0x0041,
  /* R4  */ 0x4204, /* R5  */ 0x0032, /* R6  */ 0x0A43, /* R7  */ 0x0000,
  /* R8  */ 0xC802, /* R9  */ 0x0005, /* R10 */ 0x0000, /* R11 */ 0x0612,
  /* R12 */ 0x0408, /* R13 */ 0x0038, /* R14 */ 0x3001, /* R15 */ 0x2001,
  /* R16 */ 0x171E, /* R17 */ 0x15C0, /* R18 */ 0x0000, /* R19 */ 0x2138,
  /* R20 */ 0x272C, /* R21 */ 0x1C64, /* R22 */ 0xE2BF, /* R23 */ 0x1102,
  /* R24 */ 0x0E34, /* R25 */ 0x0624, /* R26 */ 0x0DB0, /* R27 */ 0x8001,
  /* R28 */ 0x0639, /* R29 */ 0x318C, /* R30 */ 0xB18C, /* R31 */ 0x0401,
  /* R32 */ 0x1001, /* R33 */ 0x0000, /* R34 */ 0x0010, /* R35 */ 0x3100,
  /* R36 */ 0x012C, /* R37 */ 0x0500, /* R38 */ 0x8000, /* R39 */ 0x0002,
  /* R40 */ 0x0000, /* R41 */ 0x0000, /* R42 */ 0x0000, /* R43 */ 0x0000,
  /* R44 */ 0x0000, /* R45 */ 0x0000, /* R46 */ 0x0300, /* R47 */ 0x0300,
  /* R48 */ 0x4180, /* R49 */ 0x0000, /* R50 */ 0x0080, /* R51 */ 0x203F,
  /* R52 */ 0x0000, /* R53 */ 0x0000, /* R54 */ 0x0000, /* R55 */ 0x0002,
  /* R56 */ 0x0001, /* R57 */ 0x0001, /* R58 */ 0x0000, /* R59 */ 0x1388,
  /* R60 */ 0x01F4, /* R61 */ 0x03E8, /* R62 */ 0x0000, /* R63 */ 0xC350,
  /* R64 */ 0x0080, /* R65 */ 0x0000, /* R66 */ 0x003F, /* R67 */ 0x1000,
  /* R68 */ 0x0020, /* R69 */ 0x0011, /* R70 */ 0x000E, /* R71 */ 0x0000,
  /* R72 */ 0x0000, /* R73 */ 0x0000, /* R74 */ 0x0000, /* R75 */ 0x0000,
  /* R76 */ 0x0000, /* R77 */ 0x0608, /* R78 */ 0x0001, /* R79 */ 0x011E,
  /* R80 */ 0x01C0, /* R81 */ 0x0000, /* R82 */ 0x0000, /* R83 */ 0x0F00,
  /* R84 */ 0x0040, /* R85 */ 0x0000, /* R86 */ 0x0040, /* R87 */ 0xFF00,
  /* R88 */ 0x03FF, /* R89 */ 0x0000, /* R90 */ 0x0000, /* R91 */ 0x0000,
  /* R92 */ 0x0000, /* R93 */ 0x1000, /* R94 */ 0x0000, /* R95 */ 0x0000,
  /* R96 */ 0x17F8, /* R97 */ 0x0000, /* R98 */ 0x1C80, /* R99 */ 0x19B9,
  /* R100 */ 0x0533, /* R101 */ 0x03E8, /* R102 */ 0x0028, /* R103 */ 0x0014,
  /* R104 */ 0x0014, /* R105 */ 0x000A, /* R106 */ 0x0000, /* R107 */ 0x0000,
  /* R108 */ 0x0000, /* R109 */ 0x0000, /* R110 */ 0x001F, /* R111 */ 0x0000,
  /* R112 */ 0xFFFF, /* R113 */ 0x0000, /* R114 */ 0x0000, /* R115 */ 0x0000,
  /* R116 */ 0x0000, /* R117 */ 0x0000, /* R118 */ 0x0000, /* R119 */ 0x0000,
  /* R120 */ 0x0000, /* R121 */ 0x0000, /* R122 */ 0x0000
};

static uint64_t lmx2820_current_freq_hz = LMX2820_DEFAULT_FREQ_HZ;
static uint8_t lmx2820_current_power = 7U;
static bool lmx2820_current_mute = false;
static uint8_t lmx2820_current_mux = LMX2820_MUX_DIRECT;
static uint32_t lmx2820_last_tune_write_us = 0U;

/* Per-phase timing breakdown of LMX2820_Tune()'s write loop (DWT cycles,
 * reset each call) - measured ~32us/write vs ~1.5us theoretical SPI time. */
static uint32_t lmx2820_dbg_cs_low_cycles = 0U;
static uint32_t lmx2820_dbg_spi_cycles = 0U;
static uint32_t lmx2820_dbg_cs_high_cycles = 0U;

static void LMX2820_WriteRegister(uint8_t addr, uint16_t data)
{
  uint8_t tx[3];
  uint8_t rx[3];
  uint32_t t0;
  uint32_t t1;
  uint32_t t2;
  uint32_t t3;

  tx[0] = (uint8_t)(addr & 0x7FU);
  tx[1] = (uint8_t)(data >> 8);
  tx[2] = (uint8_t)(data & 0xFFU);

  t0 = DWT->CYCCNT;
  HAL_GPIO_WritePin(CSb_LMX_3V3_GPIO_Port, CSb_LMX_3V3_Pin, GPIO_PIN_RESET);
  t1 = DWT->CYCCNT;
  HAL_SPI_TransmitReceive(&hspi4, tx, rx, 3U, HAL_MAX_DELAY);
  t2 = DWT->CYCCNT;
  HAL_GPIO_WritePin(CSb_LMX_3V3_GPIO_Port, CSb_LMX_3V3_Pin, GPIO_PIN_SET);
  t3 = DWT->CYCCNT;

  lmx2820_dbg_cs_low_cycles += (t1 - t0);
  lmx2820_dbg_spi_cycles += (t2 - t1);
  lmx2820_dbg_cs_high_cycles += (t3 - t2);
}

static uint16_t LMX2820_ReadRegister(uint8_t addr)
{
  uint8_t tx[3];
  uint8_t rx[3];

  tx[0] = (uint8_t)(0x80U | (addr & 0x7FU));
  tx[1] = 0x00U;
  tx[2] = 0x00U;

  HAL_GPIO_WritePin(CSb_LMX_3V3_GPIO_Port, CSb_LMX_3V3_Pin, GPIO_PIN_RESET);
  HAL_SPI_TransmitReceive(&hspi4, tx, rx, 3U, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(CSb_LMX_3V3_GPIO_Port, CSb_LMX_3V3_Pin, GPIO_PIN_SET);

  return (uint16_t)(((uint16_t)rx[1] << 8) | rx[2]);
}

/* Computes PLL_N/PLL_NUM/INSTCAL_PLL_NUM/mux for freq_hz using exact 64-bit
 * integer arithmetic throughout (no floating point). */
static void LMX2820_ComputeRegisters(uint64_t freq_hz, uint16_t *pll_n,
                                      uint32_t *pll_num, uint32_t *instcal_num,
                                      uint8_t *mux)
{
  uint64_t effective_pfd;
  uint64_t n;
  uint64_t remainder;
  uint64_t num;
  uint64_t instcal;

  if (freq_hz <= LMX2820_CROSSOVER_HZ)
  {
    *mux = LMX2820_MUX_DIRECT;
    effective_pfd = LMX2820_FPD_HZ;
  }
  else
  {
    *mux = LMX2820_MUX_DOUBLER;
    effective_pfd = LMX2820_FPD_HZ * 2ULL;
  }

  n = freq_hz / effective_pfd;
  remainder = freq_hz - (n * effective_pfd);

  /* round(remainder * PLL_DEN / effective_pfd) */
  num = ((remainder * (uint64_t)LMX2820_PLL_DEN) + (effective_pfd / 2ULL)) / effective_pfd;

  /* round(PLL_NUM * 2^32 / PLL_DEN) */
  instcal = ((num << 32) + ((uint64_t)LMX2820_PLL_DEN / 2ULL)) / (uint64_t)LMX2820_PLL_DEN;

  *pll_n = (uint16_t)n;
  *pll_num = (uint32_t)num;
  *instcal_num = (uint32_t)instcal;
}

static bool LMX2820_PollLock(void)
{
  uint32_t attempt;

  for (attempt = 0U; attempt < LMX2820_LOCK_POLL_ATTEMPTS; attempt++)
  {
    uint16_t readback = LMX2820_ReadRegister(LMX2820_REG_LOCK_READBACK);
    uint16_t rb_ld = (uint16_t)((readback >> LMX2820_RB_LD_SHIFT) & LMX2820_RB_LD_MASK);

    if (rb_ld == LMX2820_RB_LD_LOCKED)
    {
      return true;
    }

    HAL_Delay(LMX2820_LOCK_POLL_DELAY_MS);
  }

  return false;
}

static bool lmx2820_initialized = false;

void LMX2820_Init(void)
{
  lmx2820_current_freq_hz = LMX2820_DEFAULT_FREQ_HZ;
  lmx2820_current_power = 7U;
  lmx2820_current_mute = false;
  lmx2820_current_mux = LMX2820_MUX_DIRECT;
  lmx2820_initialized = false;
}

bool LMX2820_Tune(uint64_t freq_hz)
{
  uint16_t pll_n;
  uint32_t pll_num;
  uint32_t instcal_num;
  uint8_t mux;
  uint16_t outa_mux_pd;
  uint16_t r0_value;
  uint32_t start_cycles;
  uint32_t end_cycles;

  if ((freq_hz < LMX2820_FREQ_MIN_HZ) || (freq_hz > LMX2820_FREQ_MAX_HZ))
  {
    return false;
  }

  LMX2820_ComputeRegisters(freq_hz, &pll_n, &pll_num, &instcal_num, &mux);
  outa_mux_pd = (uint16_t)(mux | (lmx2820_current_mute ? LMX2820_OUTA_PD_BIT : 0U));

  /* Tracks whether this frequency uses the output doubler - see
   * LMX2820_R0_DBLR_CAL_EN_BIT. */
  r0_value = (uint16_t)((lmx2820_template[0] & (uint16_t)~LMX2820_R0_DBLR_CAL_EN_BIT) |
                         ((mux == LMX2820_MUX_DOUBLER) ? LMX2820_R0_DBLR_CAL_EN_BIT : 0U));

  lmx2820_dbg_cs_low_cycles = 0U;
  lmx2820_dbg_spi_cycles = 0U;
  lmx2820_dbg_cs_high_cycles = 0U;
  start_cycles = DWT->CYCCNT;

  bool locked;

  if (!lmx2820_initialized)
  {
    /* First tune since power-on/reset: write all 123 registers so every
     * constant register is correct regardless of POR state. R122 down to
     * R0, R0 last - FCAL_EN calibration (triggered by writing R0) must see
     * every other register already staged. */
    uint16_t regs[LMX2820_REG_COUNT];
    int32_t addr;
    uint32_t attempt;

    memcpy(regs, lmx2820_template, sizeof(regs));
    regs[LMX2820_REG_PLL_N] = pll_n;
    regs[LMX2820_REG_PLL_DEN_HI] = (uint16_t)(LMX2820_PLL_DEN >> 16);
    regs[LMX2820_REG_PLL_DEN_LO] = (uint16_t)(LMX2820_PLL_DEN & 0xFFFFUL);
    regs[LMX2820_REG_PLL_NUM_HI] = (uint16_t)(pll_num >> 16);
    regs[LMX2820_REG_PLL_NUM_LO] = (uint16_t)(pll_num & 0xFFFFU);
    regs[LMX2820_REG_INSTCAL_HI] = (uint16_t)(instcal_num >> 16);
    regs[LMX2820_REG_INSTCAL_LO] = (uint16_t)(instcal_num & 0xFFFFU);
    regs[LMX2820_REG_OUTA_MUX_PD] = outa_mux_pd;
    regs[LMX2820_REG_OUTA_PWR] = (uint16_t)(LMX2820_OUTA_PWR_BASE | ((lmx2820_current_power & 0x07U) << 1));
    regs[0] = r0_value;

    locked = false;
    for (attempt = 0U; (attempt < LMX2820_COLD_BOOT_RETRY_ATTEMPTS) && !locked; attempt++)
    {
      /* Per datasheet Section 8.3 step 3: toggle R0's RESET bit (bit 1)
       * 1->0 before loading the rest, forcing internal state to a known
       * baseline - distinct from the FCAL_EN calibration trigger below.
       * Needed because cold-boot lock is attempt-count-dependent (attempt #1
       * fails, #2 locks, #3+ fail again) regardless of added delay - state,
       * not timing. Retried here, not just left to the caller, because the
       * automatic boot-time restore (Settings_Init()) only ever calls this
       * once with no user watching to retry it manually - seen in practice
       * failing to lock after a brief power glitch (e.g. a USB hub
       * power-cycling its downstream port on a host reconnect) even though
       * a fully clean power-on reliably locks on the first attempt. */
      LMX2820_WriteRegister(0U, 0x0002U); /* RESET = 1 */
      LMX2820_WriteRegister(0U, 0x0000U); /* RESET = 0 */

      /* Cold power-up settling delay - the chip needs time to accept
       * register writes after power-up, not just before calibration.
       * Repeated on every retry too - harmless, and cheap next to the
       * cost of leaving the board silently unlocked. */
      HAL_Delay(500U);

      for (addr = (int32_t)LMX2820_REG_COUNT - 1; addr >= 0; addr--)
      {
        LMX2820_WriteRegister((uint8_t)addr, regs[addr]);
        HAL_Delay(1U);
      }

      LMX2820_WriteRegister(0U, regs[0]);

      locked = LMX2820_PollLock();
    }
  }
  else
  {
    /* Warm retune: only registers that change with frequency/mode, plus R0
     * last (triggers FCAL_EN calibration). OUTA_PWR is excluded - it only
     * depends on power level, already correct from init or LMX_PWR. Not
     * retried - the attempt-count-dependent flakiness above is specifically
     * a cold-boot/reset behavior, not seen on ordinary retunes. */
    LMX2820_WriteRegister(LMX2820_REG_OUTA_MUX_PD, outa_mux_pd);
    LMX2820_WriteRegister(LMX2820_REG_INSTCAL_LO, (uint16_t)(instcal_num & 0xFFFFU));
    LMX2820_WriteRegister(LMX2820_REG_INSTCAL_HI, (uint16_t)(instcal_num >> 16));
    LMX2820_WriteRegister(LMX2820_REG_PLL_NUM_LO, (uint16_t)(pll_num & 0xFFFFU));
    LMX2820_WriteRegister(LMX2820_REG_PLL_NUM_HI, (uint16_t)(pll_num >> 16));
    LMX2820_WriteRegister(LMX2820_REG_PLL_DEN_LO, (uint16_t)(LMX2820_PLL_DEN & 0xFFFFUL));
    LMX2820_WriteRegister(LMX2820_REG_PLL_DEN_HI, (uint16_t)(LMX2820_PLL_DEN >> 16));
    LMX2820_WriteRegister(LMX2820_REG_PLL_N, pll_n);
    LMX2820_WriteRegister(0U, r0_value);

    locked = LMX2820_PollLock();
  }

  end_cycles = DWT->CYCCNT;
  lmx2820_last_tune_write_us = (end_cycles - start_cycles) / (SystemCoreClock / 1000000U);

  lmx2820_current_freq_hz = freq_hz;
  lmx2820_current_mux = mux;

  /* Only latch lmx2820_initialized once a full write has actually locked -
   * otherwise a failed cold-boot calibration would stick on the abbreviated
   * warm-retune path forever, missing the reset/delay/full rewrite a real
   * calibration needs. */
  if (locked)
  {
    lmx2820_initialized = true;
  }

  return locked;
}

void LMX2820_SetPower(uint8_t power)
{
  uint16_t data = (uint16_t)(LMX2820_OUTA_PWR_BASE | ((power & 0x07U) << 1));

  LMX2820_WriteRegister(LMX2820_REG_OUTA_PWR, data);
  lmx2820_current_power = (uint8_t)(power & 0x07U);
}

bool LMX2820_SetMute(bool mute)
{
  if (mute)
  {
    /* Full powerdown (R0 POWERDOWN), not just OUTA_PD - OUTA_PD alone leaks
     * RF since VCO/PLL/dividers keep running. Other R0 bits don't matter
     * here; the next unmute rewrites everything fresh. */
    LMX2820_WriteRegister(0U, LMX2820_R0_POWERDOWN_BIT);
    lmx2820_current_mute = true;
    lmx2820_initialized = false;
    return true;
  }

  /* Unmuting needs the same full re-init as cold boot. Clear mute first
   * (so Tune() recomputes OUTA_MUX_PD correctly); lmx2820_initialized is
   * already false from SetMute(true), forcing the full-write path.
   * Retunes to the last-remembered frequency. */
  lmx2820_current_mute = false;
  return LMX2820_Tune(lmx2820_current_freq_hz);
}

uint64_t LMX2820_GetFrequency(void)
{
  return lmx2820_current_freq_hz;
}

uint8_t LMX2820_GetPower(void)
{
  return lmx2820_current_power;
}

bool LMX2820_GetMuted(void)
{
  return lmx2820_current_mute;
}

LMX2820_LockStatus_t LMX2820_GetLockStatus(void)
{
  uint16_t readback = LMX2820_ReadRegister(LMX2820_REG_LOCK_READBACK);
  uint16_t rb_ld = (uint16_t)((readback >> LMX2820_RB_LD_SHIFT) & LMX2820_RB_LD_MASK);

  if (rb_ld == LMX2820_RB_LD_LOCKED)
  {
    return LMX2820_LOCK_LOCKED;
  }
  if (rb_ld == LMX2820_RB_LD_MASK)
  {
    /* 0b11 = Invalid state, distinct from Unlocked. */
    return LMX2820_LOCK_INVALID;
  }
  return LMX2820_LOCK_UNLOCKED;
}

double LMX2820_GetTemperatureC(void)
{
  uint16_t readback = LMX2820_ReadRegister(LMX2820_REG_TEMP_READBACK);
  uint16_t code = (uint16_t)(readback & LMX2820_RB_TEMP_SENS_MASK);

  return (0.85 * (double)code) - 415.0;
}

uint32_t LMX2820_GetLastTuneWriteDurationUs(void)
{
  return lmx2820_last_tune_write_us;
}

uint32_t LMX2820_GetLastTuneCsLowUs(void)
{
  return lmx2820_dbg_cs_low_cycles / (SystemCoreClock / 1000000U);
}

uint32_t LMX2820_GetLastTuneSpiUs(void)
{
  return lmx2820_dbg_spi_cycles / (SystemCoreClock / 1000000U);
}

uint32_t LMX2820_GetLastTuneCsHighUs(void)
{
  return lmx2820_dbg_cs_high_cycles / (SystemCoreClock / 1000000U);
}

uint16_t LMX2820_ReadRegisterRaw(uint8_t addr)
{
  return LMX2820_ReadRegister(addr);
}

void LMX2820_WriteRegisterRaw(uint8_t addr, uint16_t data)
{
  LMX2820_WriteRegister(addr, data);
  /* The chip no longer matches the template, so the next Tune()/unmute must do
   * the full 123-register write to restore a known configuration. */
  lmx2820_initialized = false;
}
