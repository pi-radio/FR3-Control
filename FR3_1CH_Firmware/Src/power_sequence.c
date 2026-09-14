#include "power_sequence.h"
#include "board_config.h"

#if BOARD_HAS_POWER_SEQUENCING
#include "main.h"
#endif

void PowerSequence_Init(void)
{
#if BOARD_HAS_POWER_SEQUENCING
  /* CRITICAL: INRUSH_EN/BUCK_EN_5V3/BUCK_EN_3V7/TCXO_EN_3V3 are hard-wired
     to GND on FR3 1CH rev 1.1 - driving them high would thermally destroy
     the MCU. This #if is the only thing preventing that; never let these
     HAL_GPIO_WritePin() calls run when BOARD_HAS_POWER_SEQUENCING is 0,
     and never reference these pins anywhere else - always go through this
     function.

     Order matters: TCXO_EN_3V3 needs 3V7 up first, and the LMX2820's
     reference clock (from the TCXO) must be enabled/settled before 5V3
     brings up anything downstream of it - hence Inrush, 3V7, TCXO, 5V3. */
  HAL_GPIO_WritePin(INRUSH_EN_GPIO_Port, INRUSH_EN_Pin, GPIO_PIN_SET);
  HAL_Delay(200U);

  HAL_GPIO_WritePin(BUCK_EN_3V7_GPIO_Port, BUCK_EN_3V7_Pin, GPIO_PIN_SET);
  HAL_Delay(200U);

  HAL_GPIO_WritePin(TCXO_EN_3V3_GPIO_Port, TCXO_EN_3V3_Pin, GPIO_PIN_SET);
  HAL_Delay(10U);

  HAL_GPIO_WritePin(BUCK_EN_5V3_GPIO_Port, BUCK_EN_5V3_Pin, GPIO_PIN_SET);
  HAL_Delay(200U);
#endif
}
