/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    stm32h5xx_it.c
  * @brief   Interrupt Service Routines.
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
#include "main.h"
#include "stm32h5xx_it.h"
/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "usb.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN TD */

/* USER CODE END TD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
/* STM32H5 erratum ES0565 section 2.20.1: "Buffer description table update
   completes after CTR interrupt triggers" - the PMA/BTABLE entry for a
   just-completed transfer isn't guaranteed valid until ~800ns after CTR
   is set. Must run at the very top of the ISR before touching PMA/BTABLE
   (which happens inside HAL_PCD_IRQHandler), so it can't live in the
   vendor HAL/LL files - those get fully overwritten on every CubeMX
   "Generate Code" and have no USER CODE markers. Requires the DWT cycle
   counter to already be enabled and unlocked - see main() USER CODE
   BEGIN SysInit. */
static void USB_PMA_Errata_Delay(void)
{
  uint32_t target_cycles = (SystemCoreClock / 1250000UL) + 1U;
  uint32_t start = DWT->CYCCNT;
  /* iteration_guard bounds this independent of DWT->CYCCNT actually
     incrementing, so a stuck/unlocked DWT can never hang the whole
     system inside an ISR. */
  uint32_t iteration_guard = 2000U;
  while (((DWT->CYCCNT - start) < target_cycles) && (iteration_guard > 0U))
  {
    iteration_guard--;
  }
}
/* USER CODE END 0 */

/* External variables --------------------------------------------------------*/
extern PCD_HandleTypeDef hpcd_USB_DRD_FS;
extern TIM_HandleTypeDef htim6;

/* USER CODE BEGIN EV */

/* USER CODE END EV */

/******************************************************************************/
/*           Cortex Processor Interruption and Exception Handlers          */
/******************************************************************************/
/**
  * @brief This function handles Non maskable interrupt.
  */
void NMI_Handler(void)
{
  /* USER CODE BEGIN NonMaskableInt_IRQn 0 */

  /* USER CODE END NonMaskableInt_IRQn 0 */
  /* USER CODE BEGIN NonMaskableInt_IRQn 1 */
   while (1)
  {
  }
  /* USER CODE END NonMaskableInt_IRQn 1 */
}

/**
  * @brief This function handles Hard fault interrupt.
  */
void HardFault_Handler(void)
{
  /* USER CODE BEGIN HardFault_IRQn 0 */

  /* USER CODE END HardFault_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_HardFault_IRQn 0 */
    /* USER CODE END W1_HardFault_IRQn 0 */
  }
}

/**
  * @brief This function handles Memory management fault.
  */
void MemManage_Handler(void)
{
  /* USER CODE BEGIN MemoryManagement_IRQn 0 */

  /* USER CODE END MemoryManagement_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_MemoryManagement_IRQn 0 */
    /* USER CODE END W1_MemoryManagement_IRQn 0 */
  }
}

/**
  * @brief This function handles Pre-fetch fault, memory access fault.
  */
void BusFault_Handler(void)
{
  /* USER CODE BEGIN BusFault_IRQn 0 */

  /* USER CODE END BusFault_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_BusFault_IRQn 0 */
    /* USER CODE END W1_BusFault_IRQn 0 */
  }
}

/**
  * @brief This function handles Undefined instruction or illegal state.
  */
void UsageFault_Handler(void)
{
  /* USER CODE BEGIN UsageFault_IRQn 0 */

  /* USER CODE END UsageFault_IRQn 0 */
  while (1)
  {
    /* USER CODE BEGIN W1_UsageFault_IRQn 0 */
    /* USER CODE END W1_UsageFault_IRQn 0 */
  }
}

/**
  * @brief This function handles Debug monitor.
  */
void DebugMon_Handler(void)
{
  /* USER CODE BEGIN DebugMonitor_IRQn 0 */

  /* USER CODE END DebugMonitor_IRQn 0 */
  /* USER CODE BEGIN DebugMonitor_IRQn 1 */

  /* USER CODE END DebugMonitor_IRQn 1 */
}

/******************************************************************************/
/* STM32H5xx Peripheral Interrupt Handlers                                    */
/* Add here the Interrupt Handlers for the used peripherals.                  */
/* For the available peripheral interrupt handler names,                      */
/* please refer to the startup file (startup_stm32h5xx.s).                    */
/******************************************************************************/

/**
  * @brief This function handles TIM6 global interrupt.
  */
void TIM6_IRQHandler(void)
{
  /* USER CODE BEGIN TIM6_IRQn 0 */

  /* USER CODE END TIM6_IRQn 0 */
  HAL_TIM_IRQHandler(&htim6);
  /* USER CODE BEGIN TIM6_IRQn 1 */

  /* USER CODE END TIM6_IRQn 1 */
}

/**
  * @brief This function handles USB FS global interrupt.
  */
void USB_DRD_FS_IRQHandler(void)
{
  /* USER CODE BEGIN USB_DRD_FS_IRQn 0 */
  /* HAL_PCD_IRQHandler (stm32h5xx_hal_pcd.c) takes one snapshot of ISTR,
     checks flags in a fixed priority order (CTR, RESET, PMAOVR, ERR, WKUP,
     SUSP, L1REQ, SOF, ESOF), services only the FIRST match it finds, and
     returns - even if multiple flags are simultaneously pending. Normally
     this self-corrects almost instantly, since an unhandled flag stays
     pending and the NVIC re-enters this ISR right away, but under load
     (e.g. a RESET arriving right as an endpoint event is also pending)
     that single flag can get starved longer than expected. Draining every
     currently-pending flag within one physical interrupt closes that gap;
     the iteration bound keeps this from looping forever if something
     keeps regenerating a flag. */
  {
    uint32_t pending_mask = USB_ISTR_CTR | USB_ISTR_RESET | USB_ISTR_PMAOVR | USB_ISTR_ERR |
                             USB_ISTR_WKUP | USB_ISTR_SUSP | USB_ISTR_L1REQ | USB_ISTR_SOF |
                             USB_ISTR_ESOF;
    uint32_t dispatch_guard = 16U;

    do
    {
      /* Re-applied on every iteration, not just once - each dispatch may
         service a genuinely new CTR event, which needs its own PMA settle
         delay per erratum 2.20.1 (see USB_PMA_Errata_Delay() above). */
      USB_PMA_Errata_Delay();
      HAL_PCD_IRQHandler(&hpcd_USB_DRD_FS);
      dispatch_guard--;
    } while (((hpcd_USB_DRD_FS.Instance->ISTR & pending_mask) != 0U) && (dispatch_guard > 0U));
  }
  /* USER CODE END USB_DRD_FS_IRQn 0 */
  HAL_PCD_IRQHandler(&hpcd_USB_DRD_FS);
  /* USER CODE BEGIN USB_DRD_FS_IRQn 1 */

  /* USER CODE END USB_DRD_FS_IRQn 1 */
}

/* USER CODE BEGIN 1 */

/* USER CODE END 1 */
