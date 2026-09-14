#include "ltc2668.h"
#include "main.h"
#include "spi.h"

/* 24-bit SPI frame: 4-bit command | 4-bit channel address, then 16-bit
 * data, MSB first. Command 0x3 writes a channel's input register AND
 * updates its output immediately, no LDAC pulse needed - required here
 * since LDAC/CLR are both tied to 3V3 (permanently inactive). */
#define LTC2668_CMD_WRITE_UPDATE_N   0x3U
#define LTC2668_CMD_SPAN_ALL         0xEU
#define LTC2668_SPAN_BIPOLAR_2V5     0x4U

#define LTC2668_CHANNEL_Q            0U  /* VOUT0 = CH1_Q_DC */
#define LTC2668_CHANNEL_I            2U  /* VOUT2 = CH1_I_DC */

/* Hardware span is +-2.5V; the board's usable/requested range is
 * deliberately limited in software to +-0.5V. */
#define LTC2668_SPAN_MIN             (-2.5)
#define LTC2668_SPAN_MAX             (2.5)
#define LTC2668_VOLT_LIMIT           0.5

static double ltc2668_current_i_v = 0.0;
static double ltc2668_current_q_v = 0.0;

static void LTC2668_Write(uint8_t cmd, uint8_t channel, uint16_t data)
{
  uint8_t tx[3];
  uint8_t rx[3];

  tx[0] = (uint8_t)((cmd << 4) | (channel & 0x0FU));
  tx[1] = (uint8_t)(data >> 8);
  tx[2] = (uint8_t)(data & 0xFFU);

  HAL_GPIO_WritePin(CSb_LTC2668_3V3_GPIO_Port, CSb_LTC2668_3V3_Pin, GPIO_PIN_RESET);
  HAL_SPI_TransmitReceive(&hspi4, tx, rx, 3U, HAL_MAX_DELAY);
  HAL_GPIO_WritePin(CSb_LTC2668_3V3_GPIO_Port, CSb_LTC2668_3V3_Pin, GPIO_PIN_SET);
}

/* Offset binary: code 0 = LTC2668_SPAN_MIN, code 65535 = LTC2668_SPAN_MAX,
 * code 32768 (0x8000) = 0V. */
static uint16_t LTC2668_VoltsToCode(double volts)
{
  double frac = (volts - LTC2668_SPAN_MIN) / (LTC2668_SPAN_MAX - LTC2668_SPAN_MIN);
  double code = (frac * 65535.0) + 0.5;

  if (code < 0.0)
  {
    code = 0.0;
  }
  if (code > 65535.0)
  {
    code = 65535.0;
  }

  return (uint16_t)code;
}

void LTC2668_Init(void)
{
  /* On a true cold power-up, the first SPI write can land before the
   * LTC2668's own POR sequence completes, silently failing to set the
   * span and leaving every later voltage-code write mapped through the
   * wrong default span. A settling delay before this first write fixes
   * it. */
  HAL_Delay(200U);

  /* Explicitly (re)establish the +-2.5V bipolar span - never assume the
   * chip's POR default, always set it. */
  LTC2668_Write(LTC2668_CMD_SPAN_ALL, 0U, LTC2668_SPAN_BIPOLAR_2V5);

  ltc2668_current_i_v = 0.0;
  ltc2668_current_q_v = 0.0;
}

bool LTC2668_SetVoltageI(double volts)
{
  if ((volts < -LTC2668_VOLT_LIMIT) || (volts > LTC2668_VOLT_LIMIT))
  {
    return false;
  }

  LTC2668_Write(LTC2668_CMD_WRITE_UPDATE_N, LTC2668_CHANNEL_I, LTC2668_VoltsToCode(volts));
  ltc2668_current_i_v = volts;
  return true;
}

bool LTC2668_SetVoltageQ(double volts)
{
  if ((volts < -LTC2668_VOLT_LIMIT) || (volts > LTC2668_VOLT_LIMIT))
  {
    return false;
  }

  LTC2668_Write(LTC2668_CMD_WRITE_UPDATE_N, LTC2668_CHANNEL_Q, LTC2668_VoltsToCode(volts));
  ltc2668_current_q_v = volts;
  return true;
}

double LTC2668_GetVoltageI(void)
{
  return ltc2668_current_i_v;
}

double LTC2668_GetVoltageQ(void)
{
  return ltc2668_current_q_v;
}
