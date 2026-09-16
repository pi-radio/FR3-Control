/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    app_usbx.h
  * @author  MCD Application Team
  * @brief   USBX applicative header file
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
#ifndef __APP_USBX_H__
#define __APP_USBX_H__

#ifdef __cplusplus
extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include "ux_api.h"

#include "app_usbx_device.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

/* Exported types ------------------------------------------------------------*/
/* USER CODE BEGIN ET */

/* USER CODE END ET */

/* Exported constants --------------------------------------------------------*/
/* Bumped from CubeMX's regenerated default of 1024 - see the
 * UX_APP_MEM_POOL_SIZE comment in app_azure_rtos_config.h for why the old
 * 1024/1024 pairing hung the device before USB was ever touched. This is
 * USBX's own internal working memory (descriptors, class instances,
 * endpoint buffers all draw from it at runtime, not just at init), so it
 * needs real headroom, not just enough for the one allocation. An earlier
 * attempt at 4096 still hit UX_MEMORY_INSUFFICIENT inside
 * _ux_device_stack_initialize() (class array + control endpoint buffer +
 * interface/endpoint pools + 3 endpoints' worth of transfer buffers add up
 * fast), confirmed via debugger single-stepping - 16K is comfortably clear
 * of that. Also outside any USER CODE block - re-check after any future
 * CubeMX regeneration. */
#define USBX_MEMORY_STACK_SIZE       16384
/* USER CODE BEGIN EC */

/* USER CODE END EC */

/* Exported functions prototypes ---------------------------------------------*/
UINT MX_USBX_Init(VOID *memory_ptr);

/* USER CODE BEGIN 1 */

/* USER CODE END 1 */

#ifdef __cplusplus
}
#endif
#endif /* __APP_USBX_H__ */
