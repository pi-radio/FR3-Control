#include "board_io.h"
#include "main.h"

uint8_t BoardIO_IsValidTestPoint(uint32_t index)
{
  return (index == 1U || index == 2U) ? 1U : 0U;
}

void BoardIO_SetTestPoint(uint32_t index, uint8_t state)
{
  GPIO_TypeDef *port;
  uint16_t pin;

  switch (index)
  {
    case 1U:
      port = TEST_POINT_1_GPIO_Port;
      pin = TEST_POINT_1_Pin;
      break;
    case 2U:
      port = TEST_POINT_2_GPIO_Port;
      pin = TEST_POINT_2_Pin;
      break;
    default:
      return;
  }

  HAL_GPIO_WritePin(port, pin, state ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

uint8_t BoardIO_GetTestPoint(uint32_t index)
{
  GPIO_TypeDef *port;
  uint16_t pin;

  switch (index)
  {
    case 1U:
      port = TEST_POINT_1_GPIO_Port;
      pin = TEST_POINT_1_Pin;
      break;
    case 2U:
      port = TEST_POINT_2_GPIO_Port;
      pin = TEST_POINT_2_Pin;
      break;
    default:
      return 0U;
  }

  return (HAL_GPIO_ReadPin(port, pin) == GPIO_PIN_SET) ? 1U : 0U;
}
