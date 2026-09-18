/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  *                   This file contains the common defines of the application.
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Define to prevent recursive inclusion -------------------------------------*/
#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "stm32h5xx_hal.h"

#include "stm32h5xx_ll_ucpd.h"
#include "stm32h5xx_ll_bus.h"
#include "stm32h5xx_ll_cortex.h"
#include "stm32h5xx_ll_rcc.h"
#include "stm32h5xx_ll_system.h"
#include "stm32h5xx_ll_utils.h"
#include "stm32h5xx_ll_pwr.h"
#include "stm32h5xx_ll_gpio.h"
#include "stm32h5xx_ll_dma.h"

#include "stm32h5xx_ll_exti.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
void Error_Handler(void);

/* USER CODE BEGIN EFP */
/* Space-separated reset-cause flags captured at the very start of main()
 * (e.g. "BOR ", "SFT ", "NONE") - see the "GET RESET CAUSE" command. */
const char *Main_GetResetCause(void);
/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
#define BUCK_EN_5V3_Pin GPIO_PIN_0
#define BUCK_EN_5V3_GPIO_Port GPIOA
#define BUCK_EN_3V7_Pin GPIO_PIN_1
#define BUCK_EN_3V7_GPIO_Port GPIOA
#define TEST_POINT_1_Pin GPIO_PIN_2
#define TEST_POINT_1_GPIO_Port GPIOA
#define TEST_POINT_2_Pin GPIO_PIN_3
#define TEST_POINT_2_GPIO_Port GPIOA
#define LO_CTRL_3V3_Pin GPIO_PIN_8
#define LO_CTRL_3V3_GPIO_Port GPIOE
#define CSb_LMX_3V3_Pin GPIO_PIN_9
#define CSb_LMX_3V3_GPIO_Port GPIOE
#define CSb_LTC2668_3V3_Pin GPIO_PIN_10
#define CSb_LTC2668_3V3_GPIO_Port GPIOE
#define IQ_SWAP_SW_3V3_Pin GPIO_PIN_12
#define IQ_SWAP_SW_3V3_GPIO_Port GPIOE
#define CLK_SEL_Pin GPIO_PIN_13
#define CLK_SEL_GPIO_Port GPIOE
#define INRUSH_EN_Pin GPIO_PIN_8
#define INRUSH_EN_GPIO_Port GPIOD
#define TXFILT_V3_Pin GPIO_PIN_9
#define TXFILT_V3_GPIO_Port GPIOD
#define TXFILT_V2_Pin GPIO_PIN_10
#define TXFILT_V2_GPIO_Port GPIOD
#define TXFILT_V1_Pin GPIO_PIN_11
#define TXFILT_V1_GPIO_Port GPIOD
#define TXFILT_V0_Pin GPIO_PIN_12
#define TXFILT_V0_GPIO_Port GPIOD
#define TXFILT_VB_Pin GPIO_PIN_13
#define TXFILT_VB_GPIO_Port GPIOD
#define TXFILT_VA_Pin GPIO_PIN_14
#define TXFILT_VA_GPIO_Port GPIOD
#define TCXO_EN_3V3_Pin GPIO_PIN_7
#define TCXO_EN_3V3_GPIO_Port GPIOC
#define SPI_INA_CSb_Pin GPIO_PIN_8
#define SPI_INA_CSb_GPIO_Port GPIOC
#define RXFILT_VA_Pin GPIO_PIN_4
#define RXFILT_VA_GPIO_Port GPIOB
#define RXFILT_VB_Pin GPIO_PIN_5
#define RXFILT_VB_GPIO_Port GPIOB
#define RXFILT_V0_Pin GPIO_PIN_6
#define RXFILT_V0_GPIO_Port GPIOB
#define RXFILT_V1_Pin GPIO_PIN_7
#define RXFILT_V1_GPIO_Port GPIOB
#define RXFILT_V2_Pin GPIO_PIN_8
#define RXFILT_V2_GPIO_Port GPIOB
#define RXFILT_V3_Pin GPIO_PIN_9
#define RXFILT_V3_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */
