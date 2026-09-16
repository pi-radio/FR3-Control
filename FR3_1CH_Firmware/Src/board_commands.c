#include "board_commands.h"
#include "board_config.h"
#include "board_io.h"
#include "lmx2820.h"
#include "ltc2668.h"
#include "main.h"
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
    Settings_Save();
    snprintf(response, response_capacity, "OK\r\n");
    return;
  }

  if (strcmp(line, "GET BOARD SERIAL") == 0)
  {
    snprintf(response, response_capacity, "%lu\r\n", (unsigned long)Settings_GetBoardSerial());
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
    HAL_GPIO_WritePin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin, GPIO_PIN_RESET);
    if (LMX2820_SetMute(false))
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

  if (strcmp(line, "SET LO EXT") == 0)
  {
    HAL_GPIO_WritePin(LO_CTRL_3V3_GPIO_Port, LO_CTRL_3V3_Pin, GPIO_PIN_SET);
    LMX2820_SetMute(true);
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
    if (freq_double >= 0.0 && LMX2820_Tune((uint64_t)(freq_double + 0.5)))
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

  matched_chars = -1;
  if (sscanf(line, "LMX PWR %u%n", &pwr, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
    if (pwr <= 7U)
    {
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

#if BOARD_HAS_LTC2668
  matched_chars = -1;
  if (sscanf(line, "SET I_V %lf%n", &volt_double, &matched_chars) == 1 && matched_chars == (int)strlen(line))
  {
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
