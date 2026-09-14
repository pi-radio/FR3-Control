#include "rf_filter.h"
#include "board_config.h"

#if BOARD_HAS_RF_FILTERS
#include "main.h"

#define RF_FILTER_BIT_VA   0x20U
#define RF_FILTER_BIT_VB   0x10U
#define RF_FILTER_BIT_V3   0x08U
#define RF_FILTER_BIT_V2   0x04U
#define RF_FILTER_BIT_V1   0x02U
#define RF_FILTER_BIT_V0   0x01U

static GPIO_PinState RFFilter_Bit(uint8_t value, uint8_t mask)
{
  return ((value & mask) != 0U) ? GPIO_PIN_SET : GPIO_PIN_RESET;
}

static uint8_t RFFilter_ReadBit(GPIO_TypeDef *port, uint16_t pin, uint8_t mask)
{
  return (HAL_GPIO_ReadPin(port, pin) == GPIO_PIN_SET) ? mask : 0U;
}
#endif /* BOARD_HAS_RF_FILTERS */

void RFFilter_SetTx(uint8_t value)
{
#if BOARD_HAS_RF_FILTERS
  /* CRITICAL: these 6 pins are hard-wired to GND on FR3 1CH rev 1.1 -
     driving them high would thermally destroy the MCU. This #if is the
     only thing preventing that; never let these HAL_GPIO_WritePin() calls
     run when BOARD_HAS_RF_FILTERS is 0, and never reference these pins
     anywhere else - always go through this function. */
  HAL_GPIO_WritePin(TXFILT_VA_GPIO_Port, TXFILT_VA_Pin, RFFilter_Bit(value, RF_FILTER_BIT_VA));
  HAL_GPIO_WritePin(TXFILT_VB_GPIO_Port, TXFILT_VB_Pin, RFFilter_Bit(value, RF_FILTER_BIT_VB));
  HAL_GPIO_WritePin(TXFILT_V3_GPIO_Port, TXFILT_V3_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V3));
  HAL_GPIO_WritePin(TXFILT_V2_GPIO_Port, TXFILT_V2_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V2));
  HAL_GPIO_WritePin(TXFILT_V1_GPIO_Port, TXFILT_V1_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V1));
  HAL_GPIO_WritePin(TXFILT_V0_GPIO_Port, TXFILT_V0_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V0));
#else
  (void)value;
#endif
}

void RFFilter_SetRx(uint8_t value)
{
#if BOARD_HAS_RF_FILTERS
  /* CRITICAL: see the warning in RFFilter_SetTx() above - it applies
     identically here. */
  HAL_GPIO_WritePin(RXFILT_VA_GPIO_Port, RXFILT_VA_Pin, RFFilter_Bit(value, RF_FILTER_BIT_VA));
  HAL_GPIO_WritePin(RXFILT_VB_GPIO_Port, RXFILT_VB_Pin, RFFilter_Bit(value, RF_FILTER_BIT_VB));
  HAL_GPIO_WritePin(RXFILT_V3_GPIO_Port, RXFILT_V3_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V3));
  HAL_GPIO_WritePin(RXFILT_V2_GPIO_Port, RXFILT_V2_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V2));
  HAL_GPIO_WritePin(RXFILT_V1_GPIO_Port, RXFILT_V1_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V1));
  HAL_GPIO_WritePin(RXFILT_V0_GPIO_Port, RXFILT_V0_Pin, RFFilter_Bit(value, RF_FILTER_BIT_V0));
#else
  (void)value;
#endif
}

uint8_t RFFilter_GetTx(void)
{
#if BOARD_HAS_RF_FILTERS
  uint8_t value = 0U;

  value |= RFFilter_ReadBit(TXFILT_VA_GPIO_Port, TXFILT_VA_Pin, RF_FILTER_BIT_VA);
  value |= RFFilter_ReadBit(TXFILT_VB_GPIO_Port, TXFILT_VB_Pin, RF_FILTER_BIT_VB);
  value |= RFFilter_ReadBit(TXFILT_V3_GPIO_Port, TXFILT_V3_Pin, RF_FILTER_BIT_V3);
  value |= RFFilter_ReadBit(TXFILT_V2_GPIO_Port, TXFILT_V2_Pin, RF_FILTER_BIT_V2);
  value |= RFFilter_ReadBit(TXFILT_V1_GPIO_Port, TXFILT_V1_Pin, RF_FILTER_BIT_V1);
  value |= RFFilter_ReadBit(TXFILT_V0_GPIO_Port, TXFILT_V0_Pin, RF_FILTER_BIT_V0);
  return value;
#else
  return 0U;
#endif
}

uint8_t RFFilter_GetRx(void)
{
#if BOARD_HAS_RF_FILTERS
  uint8_t value = 0U;

  value |= RFFilter_ReadBit(RXFILT_VA_GPIO_Port, RXFILT_VA_Pin, RF_FILTER_BIT_VA);
  value |= RFFilter_ReadBit(RXFILT_VB_GPIO_Port, RXFILT_VB_Pin, RF_FILTER_BIT_VB);
  value |= RFFilter_ReadBit(RXFILT_V3_GPIO_Port, RXFILT_V3_Pin, RF_FILTER_BIT_V3);
  value |= RFFilter_ReadBit(RXFILT_V2_GPIO_Port, RXFILT_V2_Pin, RF_FILTER_BIT_V2);
  value |= RFFilter_ReadBit(RXFILT_V1_GPIO_Port, RXFILT_V1_Pin, RF_FILTER_BIT_V1);
  value |= RFFilter_ReadBit(RXFILT_V0_GPIO_Port, RXFILT_V0_Pin, RF_FILTER_BIT_V0);
  return value;
#else
  return 0U;
#endif
}
