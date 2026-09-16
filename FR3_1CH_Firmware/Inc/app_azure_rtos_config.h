
/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    app_azure_rtos_config.h
  * @author  MCD Application Team
  * @brief   app_azure_rtos config header file
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
#ifndef APP_AZURE_RTOS_CONFIG_H
#define APP_AZURE_RTOS_CONFIG_H
#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* Using static memory allocation via threadX Byte memory pools */

#define USE_STATIC_ALLOCATION                    1

#define TX_APP_MEM_POOL_SIZE                     1024

/* Bumped from CubeMX's regenerated default of 1024: MX_USBX_Init()
 * (app_usbx.c) allocates a USBX_MEMORY_STACK_SIZE (app_usbx.h) block from
 * this pool, then MX_USBX_Device_Init() (app_usbx_device.c) allocates a
 * second UX_DEVICE_APP_THREAD_STACK_SIZE block from the SAME pool - two
 * back-to-back 1024-byte allocations out of a 1024-byte pool, which the
 * first allocation alone already exhausts (a byte pool needs headroom
 * beyond the raw block size for its own free-block bookkeeping). At 1024
 * the first tx_byte_allocate() in MX_USBX_Init() fails immediately, so
 * tx_application_define() spins forever in the MX_USBX_Init_Error while(1)
 * loop - before USB hardware is ever touched, which is why nothing at all
 * enumerated (not even a driverless/unknown device) despite the LMX and
 * power sequencing running fine (those happen earlier, in main(), before
 * tx_kernel_enter()). This #define lives outside any USER CODE block, so
 * CubeMX will silently reset it back to 1024 on the next "Generate Code"
 * unless the pool size is also changed in CubeMX's own USBX memory
 * settings - re-check this value after any future regeneration. */
#define UX_APP_MEM_POOL_SIZE                     24576

/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported macro ------------------------------------------------------------*/
/* USER CODE BEGIN EM */

/* USER CODE END EM */

/* Exported functions prototypes ---------------------------------------------*/
/* USER CODE BEGIN EFP */

/* USER CODE END EFP */

/* Private defines -----------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

#ifdef __cplusplus
}
#endif
#endif /* APP_AZURE_RTOS_CONFIG_H */
