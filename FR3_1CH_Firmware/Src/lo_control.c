#include "lo_control.h"
#include "board_config.h"

#if BOARD_HAS_LO_CONTROL

#include "lmx2820.h"
#include "ltc2668.h"
#include "main.h"
#include "tx_api.h"
#include <stddef.h>
#include <string.h>

/* ---- calibration table in flash -------------------------------------------------------------
 * Bank 2, sector 1 of ordinary (not EDATA) flash. Bank 2 sector 0 holds the settings module's
 * EDATA-initialized marker; the firmware image itself (~160 KB) never reaches bank 2. Ordinary
 * flash reads safely while erased (unlike EDATA, see settings.c), so no marker is needed: an
 * erased sector simply fails the magic/CRC check. Programmed in 128-bit quad-words. */
#define LOCAL_FLASH_BANK     FLASH_BANK_2
#define LOCAL_FLASH_SECTOR   1U
#define LOCAL_FLASH_ADDR     (FLASH_BASE + FLASH_BANK_SIZE + (LOCAL_FLASH_SECTOR * FLASH_SECTOR_SIZE))

#define LOCAL_MAGIC          0x4C4F434CUL   /* 'L','O','C','L' */
#define LOCAL_FORMAT         1U
/* I/Q stored as int16 in units of 1/65536 V (~15.3 uV; the LTC2668 software limit is +-0.5 V,
 * the LO null is ~2 mV wide). Temperature as int16 in 0.1 C. */
#define LOCAL_V_SCALE        65536.0
#define LOCAL_T_SCALE        10.0
/* Temperature extrapolation beyond the cold-hot span is capped at this many degrees. */
#define LOCAL_T_EXTRAP_C     10.0

typedef struct
{
  int16_t i;
  int16_t q;
  int16_t temp_dc;
  uint8_t drive;
  uint8_t valid;
} LoCalEntry_t;                               /* 8 bytes */

typedef struct
{
  uint32_t magic;
  uint16_t format;
  uint16_t n_points;
  uint32_t f_start_mhz;
  uint32_t step_mhz;
  uint32_t board_serial;
  uint32_t date;                              /* YYYYMMDD, as uploaded */
  uint32_t crc;                               /* CRC-32 of the whole record with this field = 0 */
  uint32_t reserved;
  LoCalEntry_t e[LOCAL_N_POINTS][2];          /* [LO index][LOCAL_TEMP_COLD / LOCAL_TEMP_HOT] */
} LoCalRecord_t;                              /* 32 + 2496 = 2528 bytes = 158 quad-words */

/* Aligned for 32-bit access by the quad-word programmer. */
static LoCalRecord_t local_active __attribute__((aligned(16)));
static LoCalRecord_t local_stage __attribute__((aligned(16)));
static bool local_active_valid = false;
static bool local_active_crc_ok = false;

/* ---- modes and last applied bias (RAM; the modes are persisted by settings.c) ---- */
static bool lo_power_auto = true;
static bool lo_bias_auto = true;
static bool lo_last_valid = false;
static double lo_last_i = 0.0;
static double lo_last_q = 0.0;
static double lo_last_t = 0.0;

/* ---- threading ---- */
#define LO_THREAD_STACK_BYTES   2048U
#define LO_THREAD_PRIO          12U          /* below the USB command thread (10) */
#define LO_THREAD_PERIOD_MS     2000U
static TX_THREAD lo_thread;
static TX_MUTEX lo_mutex;
static bool lo_mutex_ready = false;
static ULONG lo_thread_stack[LO_THREAD_STACK_BYTES / sizeof(ULONG)];

static uint32_t Crc32Update(uint32_t crc, uint8_t byte)
{
  uint32_t b;

  crc ^= byte;
  for (b = 0U; b < 8U; b++)
  {
    crc = (crc & 1U) ? ((crc >> 1) ^ 0xEDB88320UL) : (crc >> 1);
  }
  return crc;
}

/* CRC-32 (IEEE) of the whole record with the crc field taken as zero - computed in place, not on
 * a stack copy (the record is 2.5 KB; the USB command thread's stack is 4 KB). */
static uint32_t RecordCrc(const LoCalRecord_t *r)
{
  const uint8_t *p = (const uint8_t *)r;
  uint32_t crc_at = (uint32_t)offsetof(LoCalRecord_t, crc);
  uint32_t crc = 0xFFFFFFFFUL;
  uint32_t i;

  for (i = 0U; i < (uint32_t)sizeof(LoCalRecord_t); i++)
  {
    crc = Crc32Update(crc, ((i >= crc_at) && (i < (crc_at + 4U))) ? 0U : p[i]);
  }
  return ~crc;
}

static int16_t ToI16(double x)
{
  double r = (x >= 0.0) ? (x + 0.5) : (x - 0.5);

  if (r > 32767.0)
  {
    r = 32767.0;
  }
  if (r < -32768.0)
  {
    r = -32768.0;
  }
  return (int16_t)r;
}

static uint64_t GridHz(unsigned k)
{
  return LOCAL_F_START_HZ + ((uint64_t)k * LOCAL_F_STEP_HZ);
}

static void LoadActiveFromFlash(void)
{
  memcpy(&local_active, (const void *)LOCAL_FLASH_ADDR, sizeof(local_active));
  local_active_crc_ok = (RecordCrc(&local_active) == local_active.crc);
  local_active_valid = (local_active.magic == LOCAL_MAGIC) && (local_active.format == LOCAL_FORMAT) &&
                       (local_active.n_points == LOCAL_N_POINTS) && local_active_crc_ok;
}

void LoControl_Init(void)
{
  LoadActiveFromFlash();
  LoControl_StageClear();
}

/* ---- lock ---- */
void LoControl_Lock(void)
{
  if (lo_mutex_ready)
  {
    (void)tx_mutex_get(&lo_mutex, TX_WAIT_FOREVER);
  }
}

void LoControl_Unlock(void)
{
  if (lo_mutex_ready)
  {
    (void)tx_mutex_put(&lo_mutex);
  }
}

static VOID LoThreadEntry(ULONG input)
{
  (void)input;
  for (;;)
  {
    tx_thread_sleep((LO_THREAD_PERIOD_MS * TX_TIMER_TICKS_PER_SECOND) / 1000U);
    LoControl_Lock();
    (void)LoControl_ApplyBiasNow();
    LoControl_Unlock();
  }
}

unsigned int LoControl_ThreadCreate(void)
{
  UINT ret = tx_mutex_create(&lo_mutex, "lo_hw_lock", TX_INHERIT);

  if (ret != TX_SUCCESS)
  {
    return ret;
  }
  lo_mutex_ready = true;
  return tx_thread_create(&lo_thread, "lo_bias", LoThreadEntry, 0, lo_thread_stack, sizeof(lo_thread_stack),
                          LO_THREAD_PRIO, LO_THREAD_PRIO, TX_NO_TIME_SLICE, TX_AUTO_START);
}

/* ---- drive rule ---- */
uint8_t LoControl_DriveFor(uint64_t lo_hz)
{
  if (lo_hz <= 13000000000ULL)
  {
    return 0U;
  }
  if (lo_hz < 20000000000ULL)
  {
    return 2U;
  }
  return 4U;
}

bool LoControl_GetPowerAuto(void)
{
  return lo_power_auto;
}

void LoControl_SetPowerAuto(bool on)
{
  lo_power_auto = on;
}

void LoControl_ApplyDriveFor(uint64_t lo_hz)
{
  uint8_t d;

  if (!lo_power_auto)
  {
    return;
  }
  /* Set before the tune: the cold (full-write) tune path writes OUTA_PWR from the stored power,
   * and the warm path skips it - so this one write covers both. */
  d = LoControl_DriveFor(lo_hz);
  if (d != LMX2820_GetPower())
  {
    LMX2820_SetPower(d);
  }
}

/* ---- bias ---- */
bool LoControl_GetBiasAuto(void)
{
  return lo_bias_auto;
}

void LoControl_SetBiasAuto(bool on)
{
  lo_bias_auto = on;
}

bool LoControl_TableValid(void)
{
  return local_active_valid;
}

/* Bias of one grid entry at temp_c: linear in temperature between its cold and hot pairs, using
 * each pair's own recorded temperature; extrapolation capped at LOCAL_T_EXTRAP_C. */
static bool EntryBias(unsigned k, double temp_c, double *i_v, double *q_v)
{
  const LoCalEntry_t *c = &local_active.e[k][LOCAL_TEMP_COLD];
  const LoCalEntry_t *h = &local_active.e[k][LOCAL_TEMP_HOT];
  double ic = c->i / LOCAL_V_SCALE, qc = c->q / LOCAL_V_SCALE, tc = c->temp_dc / LOCAL_T_SCALE;
  double ih = h->i / LOCAL_V_SCALE, qh = h->q / LOCAL_V_SCALE, th = h->temp_dc / LOCAL_T_SCALE;
  double frac;
  double t_lo;
  double t_hi;

  if (!c->valid && !h->valid)
  {
    return false;
  }
  if (!h->valid)
  {
    *i_v = ic;
    *q_v = qc;
    return true;
  }
  if (!c->valid)
  {
    *i_v = ih;
    *q_v = qh;
    return true;
  }
  if (((th - tc) < 0.5) && ((tc - th) < 0.5))
  {
    frac = 0.5;
  }
  else
  {
    t_lo = ((tc < th) ? tc : th) - LOCAL_T_EXTRAP_C;
    t_hi = ((tc > th) ? tc : th) + LOCAL_T_EXTRAP_C;
    if (temp_c < t_lo)
    {
      temp_c = t_lo;
    }
    if (temp_c > t_hi)
    {
      temp_c = t_hi;
    }
    frac = (temp_c - tc) / (th - tc);
  }
  *i_v = ic + (frac * (ih - ic));
  *q_v = qc + (frac * (qh - qc));
  return true;
}

bool LoControl_ComputeBias(uint64_t lo_hz, double temp_c, double *i_v, double *q_v)
{
  unsigned k;
  double pos;
  double r;
  double i0, q0, i1, q1;
  bool ok0, ok1;
  uint8_t d;

  if (!local_active_valid)
  {
    return false;
  }
  /* LO 6-7 GHz uses the 7.0 GHz entry, 22.5-22.6 GHz the 22.5 GHz entry (user, 2026-10-10). */
  if (lo_hz <= LOCAL_F_START_HZ)
  {
    return EntryBias(0U, temp_c, i_v, q_v);
  }
  if (lo_hz >= GridHz(LOCAL_N_POINTS - 1U))
  {
    return EntryBias(LOCAL_N_POINTS - 1U, temp_c, i_v, q_v);
  }
  pos = (double)(lo_hz - LOCAL_F_START_HZ) / (double)LOCAL_F_STEP_HZ;
  k = (unsigned)pos;
  r = pos - (double)k;
  if (r < 1e-6)
  {
    return EntryBias(k, temp_c, i_v, q_v);
  }
  if (r > (1.0 - 1e-6))
  {
    return EntryBias(k + 1U, temp_c, i_v, q_v);
  }
  /* Between two grid points: linear in frequency, but never across a drive boundary (13 / 20
   * GHz) - there the nearest point with the same drive as this LO is used instead. */
  d = LoControl_DriveFor(lo_hz);
  ok0 = (LoControl_DriveFor(GridHz(k)) == d) && EntryBias(k, temp_c, &i0, &q0);
  ok1 = (LoControl_DriveFor(GridHz(k + 1U)) == d) && EntryBias(k + 1U, temp_c, &i1, &q1);
  if (ok0 && ok1)
  {
    *i_v = i0 + (r * (i1 - i0));
    *q_v = q0 + (r * (q1 - q0));
    return true;
  }
  if (ok0)
  {
    *i_v = i0;
    *q_v = q0;
    return true;
  }
  if (ok1)
  {
    *i_v = i1;
    *q_v = q1;
    return true;
  }
  return false;
}

bool LoControl_ApplyBiasNow(void)
{
  double t;
  double i_v;
  double q_v;

  if (!lo_bias_auto || !local_active_valid)
  {
    return false;
  }
#if BOARD_HAS_LO_SWITCH
  if (HAL_GPIO_ReadPin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin) == GPIO_PIN_SET)
  {
    return false;                         /* external LO: frequency unknown - auto bias paused */
  }
#endif
  if (LMX2820_GetMuted())
  {
    return false;
  }
  t = LMX2820_GetTemperatureC();
  if (!LoControl_ComputeBias(LMX2820_GetFrequency(), t, &i_v, &q_v))
  {
    return false;
  }
  if (!LTC2668_SetVoltageI(i_v) || !LTC2668_SetVoltageQ(q_v))
  {
    return false;
  }
  lo_last_i = i_v;
  lo_last_q = q_v;
  lo_last_t = t;
  lo_last_valid = true;
  return true;
}

void LoControl_GetLastApplied(double *i_v, double *q_v, double *temp_c, bool *valid)
{
  *i_v = lo_last_i;
  *q_v = lo_last_q;
  *temp_c = lo_last_t;
  *valid = lo_last_valid;
}

/* ---- upload / readback ---- */
void LoControl_StageClear(void)
{
  memset(&local_stage, 0, sizeof(local_stage));
}

bool LoControl_StageEntry(unsigned idx, unsigned which, double i_v, double q_v, double temp_c)
{
  LoCalEntry_t *e;

  if ((idx >= LOCAL_N_POINTS) || (which > LOCAL_TEMP_HOT))
  {
    return false;
  }
  if ((i_v <= -0.5) || (i_v >= 0.5) || (q_v <= -0.5) || (q_v >= 0.5) || (temp_c < -40.0) || (temp_c > 150.0))
  {
    return false;
  }
  e = &local_stage.e[idx][which];
  e->i = ToI16(i_v * LOCAL_V_SCALE);
  e->q = ToI16(q_v * LOCAL_V_SCALE);
  e->temp_dc = ToI16(temp_c * LOCAL_T_SCALE);
  e->drive = LoControl_DriveFor(GridHz(idx));
  e->valid = 1U;
  return true;
}

void LoControl_StageDate(uint32_t yyyymmdd)
{
  local_stage.date = yyyymmdd;
}

unsigned LoControl_StagedCount(void)
{
  unsigned n = 0U;
  unsigned k;

  for (k = 0U; k < LOCAL_N_POINTS; k++)
  {
    n += local_stage.e[k][LOCAL_TEMP_COLD].valid + local_stage.e[k][LOCAL_TEMP_HOT].valid;
  }
  return n;
}

const char *LoControl_Commit(uint32_t board_serial)
{
  FLASH_EraseInitTypeDef erase = {0};
  uint32_t sector_error = 0U;
  const uint32_t *words = (const uint32_t *)&local_stage;
  uint32_t n_quad = (uint32_t)(sizeof(local_stage) / 16U);
  uint32_t i;
  bool ok = true;

  if (LoControl_StagedCount() != (2U * LOCAL_N_POINTS))
  {
    return "INCOMPLETE";
  }
  local_stage.magic = LOCAL_MAGIC;
  local_stage.format = LOCAL_FORMAT;
  local_stage.n_points = LOCAL_N_POINTS;
  local_stage.f_start_mhz = (uint32_t)(LOCAL_F_START_HZ / 1000000ULL);
  local_stage.step_mhz = (uint32_t)(LOCAL_F_STEP_HZ / 1000000ULL);
  local_stage.board_serial = board_serial;
  local_stage.reserved = 0U;
  local_stage.crc = RecordCrc(&local_stage);

  erase.TypeErase = FLASH_TYPEERASE_SECTORS;
  erase.Banks = LOCAL_FLASH_BANK;
  erase.Sector = LOCAL_FLASH_SECTOR;
  erase.NbSectors = 1U;

  HAL_FLASH_Unlock();
  if (HAL_FLASHEx_Erase(&erase, &sector_error) != HAL_OK)
  {
    ok = false;
  }
  for (i = 0U; ok && (i < n_quad); i++)
  {
    if (HAL_FLASH_Program(FLASH_TYPEPROGRAM_QUADWORD, LOCAL_FLASH_ADDR + (i * 16U), (uint32_t)&words[i * 4U]) != HAL_OK)
    {
      ok = false;
    }
  }
  HAL_FLASH_Lock();
#ifdef HAL_ICACHE_MODULE_ENABLED
  (void)HAL_ICACHE_Invalidate();          /* the next read must come from flash, not the cache */
#endif
  if (!ok)
  {
    LoadActiveFromFlash();
    return "FLASH";
  }
  LoadActiveFromFlash();
  if (!local_active_valid || (memcmp(&local_active, &local_stage, sizeof(local_stage)) != 0))
  {
    return "VERIFY";
  }
  return NULL;
}

bool LoControl_GetEntry(unsigned idx, unsigned which, double *i_v, double *q_v, double *temp_c)
{
  const LoCalEntry_t *e;

  if (!local_active_valid || (idx >= LOCAL_N_POINTS) || (which > LOCAL_TEMP_HOT))
  {
    return false;
  }
  e = &local_active.e[idx][which];
  if (!e->valid)
  {
    return false;
  }
  *i_v = e->i / LOCAL_V_SCALE;
  *q_v = e->q / LOCAL_V_SCALE;
  *temp_c = e->temp_dc / LOCAL_T_SCALE;
  return true;
}

bool LoControl_GetInfo(unsigned *n_valid, unsigned *fmt, uint32_t *serial, uint32_t *date, bool *crc_ok)
{
  unsigned k;
  unsigned n = 0U;

  *crc_ok = local_active_crc_ok;
  if (local_active.magic != LOCAL_MAGIC)
  {
    *n_valid = 0U;
    *fmt = 0U;
    *serial = 0U;
    *date = 0U;
    return false;
  }
  for (k = 0U; k < LOCAL_N_POINTS; k++)
  {
    n += local_active.e[k][LOCAL_TEMP_COLD].valid + local_active.e[k][LOCAL_TEMP_HOT].valid;
  }
  *n_valid = n;
  *fmt = local_active.format;
  *serial = local_active.board_serial;
  *date = local_active.date;
  return local_active_valid;
}

bool LoControl_GetTempRange(unsigned which, double *t_min, double *t_max)
{
  unsigned k;
  bool any = false;
  double t;

  if (!local_active_valid || (which > LOCAL_TEMP_HOT))
  {
    return false;
  }
  for (k = 0U; k < LOCAL_N_POINTS; k++)
  {
    if (!local_active.e[k][which].valid)
    {
      continue;
    }
    t = local_active.e[k][which].temp_dc / LOCAL_T_SCALE;
    if (!any || (t < *t_min))
    {
      *t_min = t;
    }
    if (!any || (t > *t_max))
    {
      *t_max = t;
    }
    any = true;
  }
  return any;
}

#else /* !BOARD_HAS_LO_CONTROL: no table, no thread; the lock is a no-op. */

void LoControl_Init(void)
{
}

unsigned int LoControl_ThreadCreate(void)
{
  return 0U;
}

void LoControl_Lock(void)
{
}

void LoControl_Unlock(void)
{
}

#endif /* BOARD_HAS_LO_CONTROL */
