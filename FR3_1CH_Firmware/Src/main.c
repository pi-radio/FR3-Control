/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
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
/* Includes ------------------------------------------------------------------*/
#include "app_threadx.h"
#include "main.h"
#include "gpdma.h"
#include "icache.h"
#include "spi.h"
#include "ucpd.h"
#include "usb.h"
#include "gpio.h"
#include "usbpd.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include "lmx2820.h"
#include "ltc2668.h"
#include "power_sequence.h"
#include "settings.h"
#include "usb_pd_sink.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

/* USER CODE BEGIN PV */
/* Captured once, first thing in main() - see Main_GetResetCause(). */
static char main_reset_cause[64] = "UNKNOWN";
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MPU_Config(void);
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */
  /* Diagnostic: capture why the MCU actually reset, before anything else
   * (including HAL_Init()) has a chance to touch RCC - see
   * Main_GetResetCause() / "GET RESET CAUSE". Distinguishes a genuine
   * brownout (BOR) from a software reset, watchdog, or a plain NRST pin
   * reset. Cleared right after reading so the *next* reset's flags don't
   * OR together with this one's. */
  {
    size_t pos = 0U;

    if (__HAL_RCC_GET_FLAG(RCC_FLAG_BORRST))
    {
      pos += (size_t)snprintf(&main_reset_cause[pos], sizeof(main_reset_cause) - pos, "BOR ");
    }
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_PINRST))
    {
      pos += (size_t)snprintf(&main_reset_cause[pos], sizeof(main_reset_cause) - pos, "PIN ");
    }
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_SFTRST))
    {
      pos += (size_t)snprintf(&main_reset_cause[pos], sizeof(main_reset_cause) - pos, "SFT ");
    }
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_IWDGRST))
    {
      pos += (size_t)snprintf(&main_reset_cause[pos], sizeof(main_reset_cause) - pos, "IWDG ");
    }
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_WWDGRST))
    {
      pos += (size_t)snprintf(&main_reset_cause[pos], sizeof(main_reset_cause) - pos, "WWDG ");
    }
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_LPWRRST))
    {
      pos += (size_t)snprintf(&main_reset_cause[pos], sizeof(main_reset_cause) - pos, "LPWR ");
    }
    if (pos == 0U)
    {
      snprintf(main_reset_cause, sizeof(main_reset_cause), "NONE");
    }

    __HAL_RCC_CLEAR_RESET_FLAGS();
  }
  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* MPU Configuration--------------------------------------------------------*/
  MPU_Config();

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */
  /* Unlock and enable the Cortex-M33 DWT cycle counter - required by the
     STM32H5 erratum 2.20.1 PMA-settle delay in stm32h5xx_it.c. M33 needs
     this CoreSight lock register write before DWT->CTRL takes effect;
     CMSIS core_cm33.h doesn't expose LAR as a named field (only LSR),
     hence the raw pointer write. */
  *(volatile uint32_t *)(DWT_BASE + 0xFB0UL) = 0xC5ACCE55U;
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0U;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_GPDMA1_Init();
  MX_ICACHE_Init();
  MX_UCPD1_Init();
  MX_SPI4_Init();
  /* Call PreOsInit function */
  USBPD_PreInitOs();
  /* USER CODE BEGIN 2 */
  /* MX_USB_PCD_Init() deliberately NOT called here - it runs later, from
     inside app_ux_device_thread_entry() (app_usbx_device.c), alongside
     ux_dcd_stm32_initialize()/HAL_PCD_Start(), after the scheduler has
     started rather than during pre-scheduler main(). CubeMX re-adds
     MX_USB_PCD_Init() to the call list above on every "Generate Code" (no
     USER CODE markers wrap individual calls there) - delete it by hand
     again after every regeneration. */

  /* Boot-health diagnostic: reaching here means clocks, GPIO, and basic
     peripheral init all succeeded. */
  HAL_GPIO_WritePin(TEST_POINT_1_GPIO_Port, TEST_POINT_1_Pin, GPIO_PIN_SET);

  /* USBPDSink_Init() (usb_pd_sink.c) is NOT called here anymore - the full
   * USBPD middleware now owns UCPD1 (MX_USBPD_Init(), called from
   * tx_application_define() in app_azure_rtos.c once the scheduler starts).
   * Calling our old hand-rolled LL_UCPD_Enable()/SetSNKRole()/SetccEnable()
   * sequence here would fight the middleware's own hardware interface
   * layer over the same registers. usb_pd_sink.c is kept around only for
   * its read-only USBPDSink_GetCurrentTier() diagnostic ("GET USB PD
   * CURRENT"), which is safe to keep calling since it never writes to
   * UCPD1 - only USBPDSink_Init() (the writing half) was removed. */

  PowerSequence_Init();
  LMX2820_Init();
  LTC2668_Init();
  Settings_Init();
  /* USER CODE END 2 */

  MX_ThreadX_Init();

  /* We should never get here as control is now taken by the scheduler */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
  RCC_CRSInitTypeDef RCC_CRSInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE3);

  while(!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI48|RCC_OSCILLATORTYPE_HSI;
  RCC_OscInitStruct.HSIState = RCC_HSI_ON;
  RCC_OscInitStruct.HSIDiv = RCC_HSI_DIV2;
  RCC_OscInitStruct.HSICalibrationValue = RCC_HSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.HSI48State = RCC_HSI48_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2
                              |RCC_CLOCKTYPE_PCLK3;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Enable the CRS APB clock
  */
  __HAL_RCC_CRS_CLK_ENABLE();

  /** Configures CRS
  */
  RCC_CRSInitStruct.Prescaler = RCC_CRS_SYNC_DIV1;
  RCC_CRSInitStruct.Source = RCC_CRS_SYNC_SOURCE_USB;
  RCC_CRSInitStruct.Polarity = RCC_CRS_SYNC_POLARITY_RISING;
  RCC_CRSInitStruct.ReloadValue = __HAL_RCC_CRS_RELOADVALUE_CALCULATE(48000000,1000);
  RCC_CRSInitStruct.ErrorLimitValue = 34;
  RCC_CRSInitStruct.HSI48CalibrationValue = 32;

  HAL_RCCEx_CRSConfig(&RCC_CRSInitStruct);

  /** Configure the programming delay
  */
  __HAL_FLASH_SET_PROGRAM_DELAY(FLASH_PROGRAMMING_DELAY_0);
}

/* USER CODE BEGIN 4 */
const char *Main_GetResetCause(void)
{
  return main_reset_cause;
}
/* USER CODE END 4 */

 /* MPU Configuration */

void MPU_Config(void)
{
  MPU_Region_InitTypeDef MPU_InitStruct = {0};
  MPU_Attributes_InitTypeDef MPU_AttributesInit = {0};

  /* Disables the MPU */
  HAL_MPU_Disable();

  /** Initializes and configures the Region 0 and the memory to be protected
  */
  MPU_InitStruct.Enable = MPU_REGION_ENABLE;
  MPU_InitStruct.Number = MPU_REGION_NUMBER0;
  MPU_InitStruct.BaseAddress = 0x08FFF000;
  MPU_InitStruct.LimitAddress = 0x08FFFFFF;
  MPU_InitStruct.AttributesIndex = MPU_ATTRIBUTES_NUMBER0;
  MPU_InitStruct.AccessPermission = MPU_REGION_ALL_RO;
  MPU_InitStruct.DisableExec = MPU_INSTRUCTION_ACCESS_DISABLE;
  MPU_InitStruct.IsShareable = MPU_ACCESS_NOT_SHAREABLE;

  HAL_MPU_ConfigRegion(&MPU_InitStruct);

  /** Initializes and configures the Attribute 0 and the memory to be protected
  */
  MPU_AttributesInit.Number = MPU_ATTRIBUTES_NUMBER0;
  MPU_AttributesInit.Attributes = INNER_OUTER(MPU_NOT_CACHEABLE);

  HAL_MPU_ConfigMemoryAttributes(&MPU_AttributesInit);
  /* Enables the MPU */
  HAL_MPU_Enable(MPU_PRIVILEGED_DEFAULT);

}

/**
  * @brief  Period elapsed callback in non blocking mode
  * @note   This function is called  when TIM6 interrupt took place, inside
  * HAL_TIM_IRQHandler(). It makes a direct call to HAL_IncTick() to increment
  * a global variable "uwTick" used as application time base.
  * @param  htim : TIM handle
  * @retval None
  */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
  /* USER CODE BEGIN Callback 0 */

  /* USER CODE END Callback 0 */
  if (htim->Instance == TIM6)
  {
    HAL_IncTick();
  }
  /* USER CODE BEGIN Callback 1 */

  /* USER CODE END Callback 1 */
}

/**
  * @brief  This function is executed in case of error occurrence.
  * @param None
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
