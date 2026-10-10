#include "board_commands.h"
#include "board_config.h"
#include "board_io.h"
#include "ina229.h"
#include "lmx2820.h"
#include "lo_control.h"
#include "ltc2668.h"
#include "main.h"
#include "power_sequence.h"
#include "rf_filter.h"
#include "settings.h"
#include "usb_pd_sink.h"
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#define BOARD_IDN_STRING  BOARD_NAME " REV" BOARD_REVISION ",STM32H573VIT6,FW" FIRMWARE_VERSION "\r\n"

/* newlib-nano's snprintf() has no "ll" (64-bit) support - "%llu" produced
 * "lu" instead of the number. LMX2820 frequencies don't fit in 32 bits, so
 * format manually. out must be >= 21 bytes (20 digits + NUL). */
static void FormatU64Decimal(uint64_t value, char *out)
{
  char buf[21];
  int i = (int)sizeof(buf) - 1;

  buf[i] = '\0';
  if (value == 0U)
  {
    buf[--i] = '0';
  }
  while (value > 0U)
  {
    buf[--i] = (char)('0' + (value % 10U));
    value /= 10U;
  }
  strcpy(out, &buf[i]);
}

/* newlib-nano has no printf-side float support - "%.6f" produced an empty
 * string (scanf-side "%lf" parsing is unaffected and works fine). Formats
 * with 6 decimal places using plain integer arithmetic instead. Only needs
 * to handle +-0.5V; out must be >= 16 bytes. */
static void FormatFixed6(double value, char *out)
{
  int is_negative = (value < 0.0);
  double abs_value = is_negative ? -value : value;
  uint32_t scaled = (uint32_t)((abs_value * 1000000.0) + 0.5);
  uint32_t whole_part = scaled / 1000000UL;
  uint32_t frac_part = scaled % 1000000UL;

  snprintf(out, 16, "%s%lu.%06lu", is_negative ? "-" : "",
           (unsigned long)whole_part, (unsigned long)frac_part);
}

/* Same newlib-nano float-printf gap as FormatFixed6, just 1 decimal place -
 * matches the LMX2820 temperature sensor's own ~0.6C/code resolution, no
 * point printing more precision than the sensor has. out must be >= 16
 * bytes (whole_part is only ever a few digits, but sized to match
 * FormatFixed6 and avoid a -Wformat-truncation false positive from GCC
 * assuming the full unsigned long range). */
static void FormatFixed1(double value, char *out)
{
  int is_negative = (value < 0.0);
  double abs_value = is_negative ? -value : value;
  uint32_t scaled = (uint32_t)((abs_value * 10.0) + 0.5);
  uint32_t whole_part = scaled / 10U;
  uint32_t frac_part = scaled % 10U;

  snprintf(out, 16, "%s%lu.%01lu", is_negative ? "-" : "",
           (unsigned long)whole_part, (unsigned long)frac_part);
}

void Commands_ProcessLine(const char *line, char *response, size_t response_capacity)
{
  unsigned int tp;
  unsigned int board_serial_value;
#if BOARD_HAS_LMX2820
  unsigned int pwr;
  double freq_double;
#endif
#if BOARD_HAS_LTC2668
  double volt_double;
#endif
#if BOARD_HAS_RF_FILTERS
  unsigned int filter_bits;
#endif
  char word[8];
  int matched_chars;
  char upper_line[64];
  size_t i;

  /* Normalize to uppercase once so every parser below is case-insensitive
     for free. Numeric fields are unaffected by case. */
  for (i = 0; i < sizeof(upper_line) - 1 && line[i] != '\0'; i++)
  {
    upper_line[i] = (char)toupper((unsigned char)line[i]);
  }
  upper_line[i] = '\0';
  line = upper_line;

  if (strcmp(line, "*IDN?") == 0)
  {
    snprintf(response, response_capacity, "%s", BOARD_IDN_STRING);
    return;
  }

  if (strcmp(line, "FUCK YOU") == 0)
  {
    snprintf(response, response_capacity, "Bless your soul!\r\n");
    return;
  }

  matched_chars = -1;
  if (sscanf(line, "SET BOARD SERIAL %u%n", &board_serial_value, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
    Settings_SetBoardSerial((uint32_t)board_serial_value);
    /* Always written, even with PERSIST OFF - a factory serial must never be
       silently dropped. */
    Settings_SaveNow();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "GET BOARD SERIAL") == 0)
  {
    snprintf(response, response_capacity, "%lu\r\n", (unsigned long)Settings_GetBoardSerial());
    return;
  }

  /* Runtime flash-persistence switch for automated sweeps (see
   * Settings_SetPersist()). Always ON after reset. "SET PERSIST ON" writes
   * the current live state to flash immediately. */
  if (strcmp(line, "SET PERSIST OFF") == 0)
  {
    Settings_SetPersist(false);
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "SET PERSIST ON") == 0)
  {
    Settings_SetPersist(true);
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "GET PERSIST") == 0)
  {
    snprintf(response, response_capacity, "%s\r\n", Settings_GetPersist() ? "ON" : "OFF");
    return;
  }

  if (strcmp(line, "GET RESET CAUSE") == 0)
  {
    /* Bring-up diagnostic: space-separated flags captured at the very
     * start of main() (e.g. "BOR", "SFT", "NONE") - tells a genuine
     * brownout reset apart from a software reset, watchdog, or a plain
     * NRST pin reset. */
    snprintf(response, response_capacity, "%s\r\n", Main_GetResetCause());
    return;
  }

  if (strcmp(line, "GET USB PD CURRENT") == 0)
  {
    /* Bring-up diagnostic: what current tier the attached USB-C source is
     * actually advertising via CC (see usb_pd_sink.c) - confirms whether
     * the board is being recognized as a valid sink and getting more than
     * bare default current. */
    const char *tier_str;

    switch (USBPDSink_GetCurrentTier())
    {
      case USB_PD_SINK_CURRENT_3_0A:
        tier_str = "3.0A";
        break;
      case USB_PD_SINK_CURRENT_1_5A:
        tier_str = "1.5A";
        break;
      case USB_PD_SINK_CURRENT_DEFAULT:
        tier_str = "DEFAULT";
        break;
      case USB_PD_SINK_CURRENT_NONE:
      default:
        tier_str = "NONE";
        break;
    }
    snprintf(response, response_capacity, "%s\r\n", tier_str);
    return;
  }

#if BOARD_HAS_CLOCK_SWITCH
  if (strcmp(line, "SET CLOCK INT") == 0)
  {
    /* CLK_SEL (PE13): 1 = internal 10MHz TCXO, 0 = external SMA reference. */
    HAL_GPIO_WritePin(CLK_SEL_GPIO_Port, CLK_SEL_Pin, GPIO_PIN_SET);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "SET CLOCK EXT") == 0)
  {
    HAL_GPIO_WritePin(CLK_SEL_GPIO_Port, CLK_SEL_Pin, GPIO_PIN_RESET);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }
#endif /* BOARD_HAS_CLOCK_SWITCH */

#if BOARD_HAS_LO_SWITCH
  if (strcmp(line, "SET LO INT") == 0)
  {
    /* LO_CTRL_3V3 (PE8): 0 = internal LO, 1 = external via SMA. Switching
       internal also un-mutes the LMX2820; external mutes it, so the two
       paths never both drive the output. */
#if BOARD_HAS_LO_CONTROL
    /* 1.4.1: the internal TCXO is switched off while the LO is external - back on (and settled)
       before the LMX2820 re-tunes against it. */
    PowerSequence_SetTcxo(true);
#endif
    HAL_GPIO_WritePin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin, GPIO_PIN_RESET);
    if (LMX2820_SetMute(false))
    {
#if BOARD_HAS_LO_CONTROL
      (void)LoControl_ApplyBiasNow();
#endif
      Settings_Save();
      snprintf(response, response_capacity, "OK\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  if (strcmp(line, "SET LO EXT") == 0)
  {
    HAL_GPIO_WritePin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin, GPIO_PIN_SET);
    LMX2820_SetMute(true);
#if BOARD_HAS_LO_CONTROL
    /* 1.4.1: with an external LO the internal 10 MHz TCXO is unused - switch it off, so it stops
       clocking the LMK00804B (its 10/20 MHz comb would otherwise still reach the RX IF). An
       external 10 MHz reference (SET CLOCK EXT) still drives the LMK. Auto bias pauses (the
       external LO's frequency is unknown); the last I/Q stay applied. */
    PowerSequence_SetTcxo(false);
#endif
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }
#endif /* BOARD_HAS_LO_SWITCH */

#if BOARD_HAS_IQ_SWAP
  if (strcmp(line, "SET IQ THRU") == 0)
  {
    /* IQ_SWAP_SW_3V3 (PE12): 0 = THRU, 1 = SWAP. */
    HAL_GPIO_WritePin(IQ_SWAP_SW_3V3_GPIO_Port, IQ_SWAP_SW_3V3_Pin, GPIO_PIN_RESET);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "SET IQ SWAP") == 0)
  {
    HAL_GPIO_WritePin(IQ_SWAP_SW_3V3_GPIO_Port, IQ_SWAP_SW_3V3_Pin, GPIO_PIN_SET);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }
#endif /* BOARD_HAS_IQ_SWAP */

#if BOARD_HAS_RF_FILTERS
  matched_chars = -1;
  if (sscanf(line, "SET TXFILTER 0X%x%n", &filter_bits, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
    RFFilter_SetTx((uint8_t)filter_bits);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  matched_chars = -1;
  if (sscanf(line, "SET RXFILTER 0X%x%n", &filter_bits, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
    RFFilter_SetRx((uint8_t)filter_bits);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }
#endif /* BOARD_HAS_RF_FILTERS */

#if BOARD_HAS_CLOCK_SWITCH
  if (strcmp(line, "GET CLOCK") == 0)
  {
    if (HAL_GPIO_ReadPin(CLK_SEL_GPIO_Port, CLK_SEL_Pin) == GPIO_PIN_SET)
    {
      snprintf(response, response_capacity, "INT\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "EXT\r\n");
    }
    return;
  }
#endif /* BOARD_HAS_CLOCK_SWITCH */

#if BOARD_HAS_LO_SWITCH
  if (strcmp(line, "GET LO") == 0)
  {
    if (HAL_GPIO_ReadPin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin) == GPIO_PIN_RESET)
    {
      snprintf(response, response_capacity, "INT\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "EXT\r\n");
    }
    return;
  }
#endif /* BOARD_HAS_LO_SWITCH */

#if BOARD_HAS_IQ_SWAP
  if (strcmp(line, "GET IQ") == 0)
  {
    if (HAL_GPIO_ReadPin(IQ_SWAP_SW_3V3_GPIO_Port, IQ_SWAP_SW_3V3_Pin) == GPIO_PIN_SET)
    {
      snprintf(response, response_capacity, "SWAP\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "THRU\r\n");
    }
    return;
  }
#endif /* BOARD_HAS_IQ_SWAP */

#if BOARD_HAS_RF_FILTERS
  if (strcmp(line, "GET TXFILTER") == 0)
  {
    snprintf(response, response_capacity, "0x%02X\r\n", RFFilter_GetTx());
    return;
  }

  if (strcmp(line, "GET RXFILTER") == 0)
  {
    snprintf(response, response_capacity, "0x%02X\r\n", RFFilter_GetRx());
    return;
  }
#endif /* BOARD_HAS_RF_FILTERS */

#if BOARD_HAS_LMX2820
  matched_chars = -1;
  if (sscanf(line, "LMX TUNE %lf%n", &freq_double, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
#if BOARD_HAS_LO_CONTROL
    if (freq_double >= 0.0)
    {
      LoControl_ApplyDriveFor((uint64_t)(freq_double + 0.5));
    }
#endif
    if (freq_double >= 0.0 && LMX2820_Tune((uint64_t)(freq_double + 0.5)))
    {
#if BOARD_HAS_LO_CONTROL
      (void)LoControl_ApplyBiasNow();
#endif
      Settings_Save();
      snprintf(response, response_capacity, "OK\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  matched_chars = -1;
  if (sscanf(line, "LMX REG%u?%n", &tp, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
    if (tp <= 122U)
    {
      snprintf(response, response_capacity, "0x%04X\r\n", LMX2820_ReadRegisterRaw((uint8_t)tp));
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  /* Debug only: raw register write, e.g. "LMX REG11 0612". Not persisted.
   * Send bare hex digits: newlib's %x rejects a zero value with a 0X prefix. */
  {
    unsigned int reg_value = 0U;
    matched_chars = -1;
    if (sscanf(line, "LMX REG%u %x%n", &tp, &reg_value, &matched_chars) == 2 &&
        matched_chars == (int)strlen(line))
    {
      if (tp <= 122U && reg_value <= 0xFFFFU)
      {
        LMX2820_WriteRegisterRaw((uint8_t)tp, (uint16_t)reg_value);
        snprintf(response, response_capacity, "OK\r\n");
      }
      else
      {
        snprintf(response, response_capacity, "ERR\r\n");
      }
      return;
    }
  }

#if BOARD_HAS_LO_CONTROL
  /* 1.4.1 drive rule: AUTO (default) sets OUTA_PWR from the LO frequency on every tune - 0 for
     LO <= 13 GHz, 2 for 13-20 GHz, 4 for >= 20 GHz. "LMX PWR n" switches to MANUAL. */
  if (strcmp(line, "LMX PWR AUTO") == 0)
  {
    LoControl_SetPowerAuto(true);
    LoControl_ApplyDriveFor(LMX2820_GetFrequency());
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "LMX PWR MODE?") == 0)
  {
    snprintf(response, response_capacity, "%s\r\n", LoControl_GetPowerAuto() ? "AUTO" : "MANUAL");
    return;
  }
#endif

  matched_chars = -1;
  if (sscanf(line, "LMX PWR %u%n", &pwr, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
    if (pwr <= 7U)
    {
#if BOARD_HAS_LO_CONTROL
      LoControl_SetPowerAuto(false);
#endif
      LMX2820_SetPower((uint8_t)pwr);
      Settings_Save();
      snprintf(response, response_capacity, "OK\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  if (strcmp(line, "LMX FREQ?") == 0)
  {
    char freq_str[21];
    FormatU64Decimal(LMX2820_GetFrequency(), freq_str);
    snprintf(response, response_capacity, "%s\r\n", freq_str);
    return;
  }

  if (strcmp(line, "LMX PWR?") == 0)
  {
    snprintf(response, response_capacity, "%u\r\n", LMX2820_GetPower());
    return;
  }

  if (strcmp(line, "LMX MUTE ON") == 0)
  {
    LMX2820_SetMute(true);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "LMX MUTE OFF") == 0)
  {
    if (LMX2820_SetMute(false))
    {
#if BOARD_HAS_LO_CONTROL
      (void)LoControl_ApplyBiasNow();
#endif
      Settings_Save();
      snprintf(response, response_capacity, "OK\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  if (strcmp(line, "LMX MUTE?") == 0)
  {
    snprintf(response, response_capacity, "%s\r\n", LMX2820_GetMuted() ? "ON" : "OFF");
    return;
  }

  if (strcmp(line, "LMX LOCK?") == 0)
  {
    switch (LMX2820_GetLockStatus())
    {
      case LMX2820_LOCK_LOCKED:
        snprintf(response, response_capacity, "LOCKED\r\n");
        break;
      /* INVALID (rb_LD == 0b11) is real - e.g. genuinely returned when an
       * External clock source is selected with nothing actually connected -
       * but reported to the host as UNLOCKED rather than as a distinct
       * third state, since it isn't actionable any differently. */
      case LMX2820_LOCK_INVALID:
      case LMX2820_LOCK_UNLOCKED:
      default:
        snprintf(response, response_capacity, "UNLOCKED\r\n");
        break;
    }
    return;
  }

  if (strcmp(line, "LMX TEMP?") == 0)
  {
    char temp_str[16];
    FormatFixed1(LMX2820_GetTemperatureC(), temp_str);
    snprintf(response, response_capacity, "%s\r\n", temp_str);
    return;
  }
#endif /* BOARD_HAS_LMX2820 */

#if BOARD_HAS_INA229
  /* INA229 is write-only from firmware (its 5V0 SDO is physically
   * disconnected from the shared 3.3V MISO bus - see
   * fr3-1ch-ina229-5v-sdo-cannot-share-3v3-miso). Alerts are latched, so
   * this resets the chip and reconfigures it (see INA229_ClearAlarms()) -
   * the only write-only-compatible way to clear a latched alarm and turn
   * the ALARM LED back off. Can't confirm anything actually happened, and
   * there's no VBUS/current/alarm-status query to pair with SET/GET-style
   * commands elsewhere in this file. */
  if (strcmp(line, "INA ALARM CLEAR") == 0)
  {
    INA229_ClearAlarms();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }
#endif /* BOARD_HAS_INA229 */

#if BOARD_HAS_LTC2668
  matched_chars = -1;
  if (sscanf(line, "SET I_V %lf%n", &volt_double, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
#if BOARD_HAS_LO_CONTROL
    LoControl_SetBiasAuto(false);         /* a manual bias switches the auto bias off (IQBIAS AUTO) */
#endif
    if (LTC2668_SetVoltageI(volt_double))
    {
      Settings_Save();
      snprintf(response, response_capacity, "OK\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  matched_chars = -1;
  if (sscanf(line, "SET Q_V %lf%n", &volt_double, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
#if BOARD_HAS_LO_CONTROL
    LoControl_SetBiasAuto(false);
#endif
    if (LTC2668_SetVoltageQ(volt_double))
    {
      Settings_Save();
      snprintf(response, response_capacity, "OK\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  if (strcmp(line, "GET I_V") == 0)
  {
    char volt_str[16];
    FormatFixed6(LTC2668_GetVoltageI(), volt_str);
    snprintf(response, response_capacity, "%s\r\n", volt_str);
    return;
  }

  if (strcmp(line, "GET Q_V") == 0)
  {
    char volt_str[16];
    FormatFixed6(LTC2668_GetVoltageQ(), volt_str);
    snprintf(response, response_capacity, "%s\r\n", volt_str);
    return;
  }
#endif /* BOARD_HAS_LTC2668 */

#if BOARD_HAS_LO_CONTROL
  /* ---- 1.4.1: per-unit cold/hot LO-null calibration (lo_control.c) ---- */
  if (strcmp(line, "IQBIAS AUTO") == 0)
  {
    if (!LoControl_TableValid())
    {
      snprintf(response, response_capacity, "ERR NOCAL\r\n");
      return;
    }
    LoControl_SetBiasAuto(true);
    (void)LoControl_ApplyBiasNow();
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "IQBIAS MANUAL") == 0)
  {
    LoControl_SetBiasAuto(false);
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  /* "AUTO <state> I=<V> Q=<V> T=<C>" or "MANUAL I=<V> Q=<V>". state: ON (applied), NOCAL (no valid
     table), EXTLO (external LO: paused), MUTED (LMX muted: paused). I/Q are the DAC's present values;
     T is the die temperature the last auto bias was computed for. */
  if (strcmp(line, "IQBIAS?") == 0)
  {
    char i_str[16];
    char q_str[16];
    char t_str[16];
    double li, lq, lt;
    bool lv;
    const char *state = "ON";

    FormatFixed6(LTC2668_GetVoltageI(), i_str);
    FormatFixed6(LTC2668_GetVoltageQ(), q_str);
    if (!LoControl_GetBiasAuto())
    {
      snprintf(response, response_capacity, "MANUAL I=%s Q=%s\r\n", i_str, q_str);
      return;
    }
    LoControl_GetLastApplied(&li, &lq, &lt, &lv);
    if (!LoControl_TableValid())
    {
      state = "NOCAL";
    }
#if BOARD_HAS_LO_SWITCH
    else if (HAL_GPIO_ReadPin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin) == GPIO_PIN_SET)
    {
      state = "EXTLO";
    }
#endif
    else if (LMX2820_GetMuted())
    {
      state = "MUTED";
    }
    FormatFixed1(lv ? lt : 0.0, t_str);
    snprintf(response, response_capacity, "AUTO %s I=%s Q=%s T=%s\r\n", state, i_str, q_str, t_str);
    return;
  }

  /* Upload, one entry per line (63-character line limit): CAL LO <idx 0-155> <C|H> <I_V> <Q_V> <T_C>.
     Goes into a RAM staging copy; nothing is active until CAL COMMIT. */
  {
    unsigned int idx = 0U;
    char which = 0;
    double iv = 0.0, qv = 0.0, tc = 0.0;

    matched_chars = -1;
    if (sscanf(line, "CAL LO %u %c %lf %lf %lf%n", &idx, &which, &iv, &qv, &tc, &matched_chars) == 5 &&
        matched_chars == (int)strlen(line))
    {
      bool ok = ((which == 'C') || (which == 'H')) &&
                LoControl_StageEntry(idx, (which == 'H') ? LOCAL_TEMP_HOT : LOCAL_TEMP_COLD, iv, qv, tc);
      snprintf(response, response_capacity, "%s", ok ? "OK\r\n" : "ERR\r\n");
      return;
    }

    matched_chars = -1;
    if (sscanf(line, "CAL LO? %u %c%n", &idx, &which, &matched_chars) == 2 && matched_chars == (int)strlen(line))
    {
      char i_str[16];
      char q_str[16];
      char t_str[16];

      if (((which == 'C') || (which == 'H')) &&
          LoControl_GetEntry(idx, (which == 'H') ? LOCAL_TEMP_HOT : LOCAL_TEMP_COLD, &iv, &qv, &tc))
      {
        FormatFixed6(iv, i_str);
        FormatFixed6(qv, q_str);
        FormatFixed1(tc, t_str);
        snprintf(response, response_capacity, "%s %s %s\r\n", i_str, q_str, t_str);
      }
      else
      {
        snprintf(response, response_capacity, "ERR\r\n");
      }
      return;
    }
  }

  if (strcmp(line, "CAL CLEAR") == 0)
  {
    LoControl_StageClear();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  {
    unsigned int date = 0U;

    matched_chars = -1;
    if (sscanf(line, "CAL DATE %u%n", &date, &matched_chars) == 1 && matched_chars == (int)strlen(line))
    {
      LoControl_StageDate((uint32_t)date);
      snprintf(response, response_capacity, "OK\r\n");
      return;
    }
  }

  if (strcmp(line, "CAL STAGED?") == 0)
  {
    snprintf(response, response_capacity, "%u\r\n", LoControl_StagedCount());
    return;
  }

  /* Writes the staged table (all 312 entries required) to its flash sector, reads it back and
     compares; becomes the active table. Not affected by SET PERSIST (always written). */
  if (strcmp(line, "CAL COMMIT") == 0)
  {
    const char *err = LoControl_Commit(Settings_GetBoardSerial());

    if (err == NULL)
    {
      (void)LoControl_ApplyBiasNow();
      snprintf(response, response_capacity, "OK\r\n");
    }
    else
    {
      snprintf(response, response_capacity, "ERR %s\r\n", err);
    }
    return;
  }

  if (strcmp(line, "CAL INFO?") == 0)
  {
    unsigned n, fmt;
    uint32_t sn, date;
    bool crc_ok;

    if (LoControl_GetInfo(&n, &fmt, &sn, &date, &crc_ok) || (n > 0U))
    {
      snprintf(response, response_capacity, "N=%u FMT=%u CRC=%s SN=%lu DATE=%lu\r\n", n, fmt, crc_ok ? "OK" : "BAD",
               (unsigned long)sn, (unsigned long)date);
    }
    else
    {
      snprintf(response, response_capacity, "NONE\r\n");
    }
    return;
  }

  if (strcmp(line, "CAL TEMPS?") == 0)
  {
    double c0 = 0.0, c1 = 0.0, h0 = 0.0, h1 = 0.0;
    char a[16], b[16], c[16], d[16];

    if (LoControl_GetTempRange(LOCAL_TEMP_COLD, &c0, &c1) && LoControl_GetTempRange(LOCAL_TEMP_HOT, &h0, &h1))
    {
      FormatFixed1(c0, a);
      FormatFixed1(c1, b);
      FormatFixed1(h0, c);
      FormatFixed1(h1, d);
      snprintf(response, response_capacity, "C=%s..%s H=%s..%s\r\n", a, b, c, d);
    }
    else
    {
      snprintf(response, response_capacity, "ERR NOCAL\r\n");
    }
    return;
  }
#endif /* BOARD_HAS_LO_CONTROL */

  matched_chars = -1;
  if (sscanf(line, "TP%u?%n", &tp, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
    if (BoardIO_IsValidTestPoint(tp))
    {
      snprintf(response, response_capacity, "%u\r\n", BoardIO_GetTestPoint(tp));
    }
    else
    {
      snprintf(response, response_capacity, "ERR\r\n");
    }
    return;
  }

  if (sscanf(line, "TP%u %7s", &tp, word) == 2)
  {
    if (BoardIO_IsValidTestPoint(tp))
    {
      if (strcmp(word, "ON") == 0)
      {
        BoardIO_SetTestPoint(tp, 1U);
        snprintf(response, response_capacity, "OK\r\n");
        return;
      }
      if (strcmp(word, "OFF") == 0)
      {
        BoardIO_SetTestPoint(tp, 0U);
        snprintf(response, response_capacity, "OK\r\n");
        return;
      }
    }
  }

  /* Bring-up diagnostic: an intermittent, unexplained parsing failure hits
     commands sent shortly after a response (seen with LMX REG74?/LMX TUNE).
     Echoes the unmatched line + length to catch it with real data. */
  snprintf(response, response_capacity, "ERR:[%s]len=%d\r\n", line, (int)strlen(line));
}
