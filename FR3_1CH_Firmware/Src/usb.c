/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    usb.c
  * @brief   This file provides code for the configuration
  *          of the USB instances.
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
#include "usb.h"

/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

PCD_HandleTypeDef hpcd_USB_DRD_FS;

/* USB init function */

void MX_USB_PCD_Init(void)
{

  /* USER CODE BEGIN USB_Init 0 */

  /* USER CODE END USB_Init 0 */

  /* USER CODE BEGIN USB_Init 1 */

  /* USER CODE END USB_Init 1 */
  hpcd_USB_DRD_FS.Instance = USB_DRD_FS;
  hpcd_USB_DRD_FS.Init.dev_endpoints = 8;
  hpcd_USB_DRD_FS.Init.speed = USBD_FS_SPEED;
  hpcd_USB_DRD_FS.Init.phy_itface = PCD_PHY_EMBEDDED;
  hpcd_USB_DRD_FS.Init.Sof_enable = DISABLE;
  hpcd_USB_DRD_FS.Init.low_power_enable = DISABLE;
  hpcd_USB_DRD_FS.Init.lpm_enable = DISABLE;
  hpcd_USB_DRD_FS.Init.battery_charging_enable = DISABLE;
  hpcd_USB_DRD_FS.Init.vbus_sensing_enable = DISABLE;
  hpcd_USB_DRD_FS.Init.bulk_doublebuffer_enable = DISABLE;
  hpcd_USB_DRD_FS.Init.iso_singlebuffer_enable = DISABLE;
  if (HAL_PCD_Init(&hpcd_USB_DRD_FS) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USB_Init 2 */
  /* USB_DRD_FS has 2KB of dedicated packet memory, and every endpoint's
     buffer location within it must be explicitly assigned here - neither
     CubeMX nor USBX's STM32 DCD layer does this for us. With
     dev_endpoints = 8, the buffer descriptor table (BTABLE) occupies the
     first 8 * 8 = 64 (0x40) bytes of PMA - real endpoint buffers must
     start at 0x40 or later, never at 0x00 (placing one at 0x00 corrupts
     the BTABLE itself). Keep endpoint address literals in sync with
     ux_device_descriptors.h if those ever change. */
  HAL_PCDEx_PMAConfig(&hpcd_USB_DRD_FS, 0x00, PCD_SNG_BUF, 0x40);  /* EP0 OUT */
  HAL_PCDEx_PMAConfig(&hpcd_USB_DRD_FS, 0x80, PCD_SNG_BUF, 0x80);  /* EP0 IN */
  HAL_PCDEx_PMAConfig(&hpcd_USB_DRD_FS, 0x81, PCD_SNG_BUF, 0xC0);  /* CDC command/notification IN */
  HAL_PCDEx_PMAConfig(&hpcd_USB_DRD_FS, 0x82, PCD_SNG_BUF, 0x100); /* CDC bulk data IN */
  HAL_PCDEx_PMAConfig(&hpcd_USB_DRD_FS, 0x03, PCD_SNG_BUF, 0x140); /* CDC bulk data OUT */
  /* USER CODE END USB_Init 2 */

}

void HAL_PCD_MspInit(PCD_HandleTypeDef* pcdHandle)
{

  RCC_PeriphCLKInitTypeDef PeriphClkInitStruct = {0};
  if(pcdHandle->Instance==USB_DRD_FS)
  {
  /* USER CODE BEGIN USB_DRD_FS_MspInit 0 */
  /* Must complete before the HAL_PWREx_EnableVddUSB() call below (generated
     boilerplate, not a USER CODE section - do not move it here even though
     it's logically part of this same sequencing fix, it would be wiped on
     the next "Generate Code"). */
  HAL_PWREx_EnableUSBVoltageDetector();
  while (__HAL_PWR_GET_FLAG(PWR_FLAG_USB33RDY) == RESET) { }
  /* USER CODE END USB_DRD_FS_MspInit 0 */

  /** Initializes the peripherals clock
  */
    PeriphClkInitStruct.PeriphClockSelection = RCC_PERIPHCLK_USB;
    PeriphClkInitStruct.UsbClockSelection = RCC_USBCLKSOURCE_HSI48;
    if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInitStruct) != HAL_OK)
    {
      Error_Handler();
    }

    /* Enable VDDUSB */
    HAL_PWREx_EnableVddUSB();
    /* USB_DRD_FS clock enable */
    __HAL_RCC_USB_CLK_ENABLE();

    /* USB_DRD_FS interrupt Init */
    HAL_NVIC_SetPriority(USB_DRD_FS_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(USB_DRD_FS_IRQn);
  /* USER CODE BEGIN USB_DRD_FS_MspInit 1 */

  /* USER CODE END USB_DRD_FS_MspInit 1 */
  }
}

void HAL_PCD_MspDeInit(PCD_HandleTypeDef* pcdHandle)
{

  if(pcdHandle->Instance==USB_DRD_FS)
  {
  /* USER CODE BEGIN USB_DRD_FS_MspDeInit 0 */

  /* USER CODE END USB_DRD_FS_MspDeInit 0 */
    /* Peripheral clock disable */
    __HAL_RCC_USB_CLK_DISABLE();

    /* USB_DRD_FS interrupt Deinit */
    HAL_NVIC_DisableIRQ(USB_DRD_FS_IRQn);
  /* USER CODE BEGIN USB_DRD_FS_MspDeInit 1 */

  /* USER CODE END USB_DRD_FS_MspDeInit 1 */
  }
}

/* USER CODE BEGIN 1 */

/* USER CODE END 1 */

