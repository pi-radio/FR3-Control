#include "settings.h"
#include "board_config.h"
#include "main.h"
#include "lmx2820.h"
#include "ltc2668.h"
#include "rf_filter.h"
#include <string.h>

#define SETTINGS_MAGIC    0x53455454UL  /* 'S','E','T','T' */
#define SETTINGS_VERSION  1U

/* Reserve 1 EDATA sector (6KB) - far more than this <100-byte settings
 * blob needs. EDATA sectors are numbered starting at 120 from the bottom
 * of the always-reserved 8-sector/48KB zone (sector = 120 +
 * offset/sector_size from FLASH_EDATA_BASE), so with EDATASize=1 the
 * active sector is physical 120, not 127; sectors 121-127 stay reserved
 * but unused. */
#define SETTINGS_EDATA_SIZE_SECTORS  1U
#define SETTINGS_EDATA_BANK          FLASH_BANK_1
#define SETTINGS_EDATA_SECTOR        120U

/* STM32H5 EDATA quirk: a plain erase does not leave the area safe to read
 * - its ECC only becomes valid once something has actually been
 * programmed. Reading a freshly-enabled-but-never-programmed region
 * triggers an uncorrectable ECC error, delivered as an NMI on this part.
 * This marker - one quad-word in ordinary flash, separate from EDATA -
 * records whether EDATA has ever been programmed, so Settings_Init()
 * knows it's safe to read without reading EDATA itself first.
 *
 * Lives in bank 2, not bank 1: enabling EDATA at all reserves the entire
 * top 8-sector/48KB block of bank 1 out of normal addressing (not just
 * the sectors EDATASize requests - confirmed by a bus fault reading
 * sector 126 once enabled). Bank 2 is untouched and this firmware is
 * nowhere near large enough to reach it. */
#define SETTINGS_INIT_MARKER_BANK    FLASH_BANK_2
#define SETTINGS_INIT_MARKER_SECTOR  0U
#define SETTINGS_INIT_MARKER_ADDR    (FLASH_BASE + FLASH_BANK_SIZE + (SETTINGS_INIT_MARKER_SECTOR * FLASH_SECTOR_SIZE))
#define SETTINGS_INIT_MARKER_MAGIC   0x494E4954UL  /* 'I','N','I','T' */

/* Marks the EDATA range non-cacheable, so a read right after a save can't
 * return a stale ICACHE'd value. Covers the full max-size window
 * regardless of sectors reserved. Slot 1 - slot 0 is MPU_Config() in
 * main.c's OTP area. */
#define SETTINGS_EDATA_MPU_BASE   FLASH_EDATA_BASE
#define SETTINGS_EDATA_MPU_LIMIT  (FLASH_EDATA_BASE + FLASH_EDATA_BANK_SIZE - 1U)

typedef struct
{
  uint32_t magic;
  uint32_t version;

  uint32_t board_serial;

#if BOARD_HAS_LMX2820
  uint64_t lmx_freq_hz;
  uint8_t  lmx_power;
  uint8_t  lmx_mute;
#endif

#if BOARD_HAS_LTC2668
  double   i_v;
  double   q_v;
#endif

#if BOARD_HAS_CLOCK_SWITCH
  uint8_t  clock_internal;
#endif

#if BOARD_HAS_LO_SWITCH
  uint8_t  lo_internal;
#endif

#if BOARD_HAS_IQ_SWAP
  uint8_t  iq_swap;
#endif

#if BOARD_HAS_RF_FILTERS
  uint8_t  tx_filter;
  uint8_t  rx_filter;
#endif
} Settings_t;

static uint32_t settings_board_serial = 0U;

uint32_t Settings_GetBoardSerial(void)
{
  return settings_board_serial;
}

void Settings_SetBoardSerial(uint32_t serial)
{
  settings_board_serial = serial;
}

static void Settings_ConfigureEdataMpu(void)
{
  MPU_Region_InitTypeDef region = {0};
  MPU_Attributes_InitTypeDef attr = {0};

  HAL_MPU_Disable();

  attr.Number = MPU_ATTRIBUTES_NUMBER1;
  attr.Attributes = INNER_OUTER(MPU_NOT_CACHEABLE);
  HAL_MPU_ConfigMemoryAttributes(&attr);

  region.Enable = MPU_REGION_ENABLE;
  region.Number = MPU_REGION_NUMBER1;
  region.BaseAddress = SETTINGS_EDATA_MPU_BASE;
  region.LimitAddress = SETTINGS_EDATA_MPU_LIMIT;
  region.AttributesIndex = MPU_ATTRIBUTES_NUMBER1;
  region.AccessPermission = MPU_REGION_ALL_RW;
  region.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;
  region.IsShareable = MPU_ACCESS_NOT_SHAREABLE;
  HAL_MPU_ConfigRegion(&region);

  HAL_MPU_Enable(MPU_PRIVILEGED_DEFAULT);
}

static void Settings_EnableEdataIfNeeded(void)
{
  FLASH_OBProgramInitTypeDef ob = {0};

  ob.Banks = SETTINGS_EDATA_BANK;
  HAL_FLASHEx_OBGetConfig(&ob);

  if (ob.EDATASize != 0U)
  {
    return;
  }

  /* EDATA not enabled yet - enable it now. One-time option-byte write:
     HAL_FLASH_OB_Launch() reloads option bytes, followed by an automatic
     system reset. Every future boot sees EDATASize != 0 and returns early. */
  HAL_FLASH_Unlock();
  HAL_FLASH_OB_Unlock();

  ob.OptionType = OPTIONBYTE_EDATA;
  ob.Banks = SETTINGS_EDATA_BANK;
  ob.EDATASize = SETTINGS_EDATA_SIZE_SECTORS;

  if (HAL_FLASHEx_OBProgram(&ob) == HAL_OK)
  {
    HAL_FLASH_OB_Launch();
  }

  HAL_FLASH_OB_Lock();
  HAL_FLASH_Lock();

  /* HAL_FLASH_OB_Launch() triggers a reset shortly after returning; wait
     here rather than fall through into the rest of Settings_Init() with
     EDATA in an indeterminate not-yet-reset state. */
  while (1)
  {
  }
}

static void Settings_Erase(void)
{
  FLASH_EraseInitTypeDef erase = {0};
  uint32_t sector_error;

  erase.TypeErase = FLASH_TYPEERASE_SECTORS;
  erase.Banks = SETTINGS_EDATA_BANK;
  erase.Sector = SETTINGS_EDATA_SECTOR;
  erase.NbSectors = 1U;

  HAL_FLASHEx_Erase(&erase, &sector_error);
}

static void Settings_ProgramWords(const uint32_t *data, uint32_t word_count)
{
  uint32_t i;

  for (i = 0U; i < word_count; i++)
  {
    HAL_FLASH_Program(FLASH_TYPEPROGRAM_WORD_EDATA,
                       FLASH_EDATA_BASE + (i * 4U),
                       (uint32_t)&data[i]);
  }
}

static bool Settings_IsEdataInitialized(void)
{
  return (*(volatile uint32_t *)SETTINGS_INIT_MARKER_ADDR) == SETTINGS_INIT_MARKER_MAGIC;
}

static void Settings_MarkEdataInitialized(void)
{
  FLASH_EraseInitTypeDef erase = {0};
  uint32_t sector_error;
  uint32_t marker[4] = {SETTINGS_INIT_MARKER_MAGIC, 0U, 0U, 0U};

  erase.TypeErase = FLASH_TYPEERASE_SECTORS;
  erase.Banks = SETTINGS_INIT_MARKER_BANK;
  erase.Sector = SETTINGS_INIT_MARKER_SECTOR;
  erase.NbSectors = 1U;

  HAL_FLASH_Unlock();
  HAL_FLASHEx_Erase(&erase, &sector_error);
  HAL_FLASH_Program(FLASH_TYPEPROGRAM_QUADWORD, SETTINGS_INIT_MARKER_ADDR, (uint32_t)marker);
  HAL_FLASH_Lock();
}

void Settings_Init(void)
{
  Settings_t settings;

  Settings_ConfigureEdataMpu();
  Settings_EnableEdataIfNeeded();

  if (!Settings_IsEdataInitialized())
  {
    /* First-ever access: EDATA is erased but never programmed, not yet
       safe to read - see SETTINGS_INIT_MARKER_SECTOR above. Settings_Save()
       does the required erase-then-program cycle (saving current driver
       defaults), making it safe to read from now on. */
    Settings_Save();
    Settings_MarkEdataInitialized();
  }

  memcpy(&settings, (const void *)FLASH_EDATA_BASE, sizeof(settings));

  if ((settings.magic != SETTINGS_MAGIC) || (settings.version != SETTINGS_VERSION))
  {
    /* Shouldn't normally happen, but covers a future layout change finding
       an old-format blob - leave each driver's own Init() defaults rather
       than misinterpret stale data. */
    return;
  }

  settings_board_serial = settings.board_serial;

#if BOARD_HAS_CLOCK_SWITCH
  /* Restore the clock source before tuning the LMX2820 below - it needs a
     stable reference clock to calibrate against. Otherwise every boot
     would tune while CLK_SEL is still at its GPIO-init default, not the
     persisted selection. */
  HAL_GPIO_WritePin(CLK_SEL_GPIO_Port, CLK_SEL_Pin,
                     (settings.clock_internal != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
  HAL_Delay(200U);
#endif

#if BOARD_HAS_LMX2820
  /* Tune first, unconditionally - this is the only call that runs the
     mandatory cold-boot RESET + 500ms settle + full 123-register write,
     and must be the very first thing to touch the chip after power-up.
     SetPower() is a single-register write, safe only once that's done;
     calling it before Tune() (as this used to) hit the chip with a raw
     SPI write during its power-up transient, before RESET/settling ever
     happened. Tune()'s own full write uses whatever lmx2820_current_power
     already is (still the LMX2820_Init() default here, not yet the
     persisted value), so SetPower() still runs right after to correct it
     - one extra harmless single-register write, on an already-initialized
     chip this time.
     Mute last: muting before tuning would power down and mark
     uninitialized, only for the tune to immediately power it back up -
     undoing the restored mute. No explicit unmute call needed since the
     tune already leaves it unmuted. */
  LMX2820_Tune(settings.lmx_freq_hz);
  LMX2820_SetPower(settings.lmx_power);
  if (settings.lmx_mute != 0U)
  {
    LMX2820_SetMute(true);
  }
#endif

#if BOARD_HAS_LTC2668
  LTC2668_SetVoltageI(settings.i_v);
  LTC2668_SetVoltageQ(settings.q_v);
#endif

#if BOARD_HAS_LO_SWITCH
  HAL_GPIO_WritePin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin,
                     (settings.lo_internal != 0U) ? GPIO_PIN_RESET : GPIO_PIN_SET);
#endif

#if BOARD_HAS_IQ_SWAP
  HAL_GPIO_WritePin(IQ_SWAP_SW_3V3_GPIO_Port, IQ_SWAP_SW_3V3_Pin,
                     (settings.iq_swap != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET);
#endif

#if BOARD_HAS_RF_FILTERS
  RFFilter_SetTx(settings.tx_filter);
  RFFilter_SetRx(settings.rx_filter);
#endif
}

void Settings_Save(void)
{
  Settings_t settings = {0};

  settings.magic = SETTINGS_MAGIC;
  settings.version = SETTINGS_VERSION;

  settings.board_serial = settings_board_serial;

#if BOARD_HAS_LMX2820
  settings.lmx_freq_hz = LMX2820_GetFrequency();
  settings.lmx_power = LMX2820_GetPower();
  settings.lmx_mute = LMX2820_GetMuted() ? 1U : 0U;
#endif

#if BOARD_HAS_LTC2668
  settings.i_v = LTC2668_GetVoltageI();
  settings.q_v = LTC2668_GetVoltageQ();
#endif

#if BOARD_HAS_CLOCK_SWITCH
  settings.clock_internal = (HAL_GPIO_ReadPin(CLK_SEL_GPIO_Port, CLK_SEL_Pin) == GPIO_PIN_SET) ? 1U : 0U;
#endif

#if BOARD_HAS_LO_SWITCH
  settings.lo_internal = (HAL_GPIO_ReadPin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin) == GPIO_PIN_RESET) ? 1U : 0U;
#endif

#if BOARD_HAS_IQ_SWAP
  settings.iq_swap = (HAL_GPIO_ReadPin(IQ_SWAP_SW_3V3_GPIO_Port, IQ_SWAP_SW_3V3_Pin) == GPIO_PIN_SET) ? 1U : 0U;
#endif

#if BOARD_HAS_RF_FILTERS
  settings.tx_filter = RFFilter_GetTx();
  settings.rx_filter = RFFilter_GetRx();
#endif

  HAL_FLASH_Unlock();
  Settings_Erase();
  Settings_ProgramWords((const uint32_t *)&settings, (uint32_t)((sizeof(settings) + 3U) / 4U));
  HAL_FLASH_Lock();
}
