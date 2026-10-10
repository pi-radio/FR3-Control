/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    app_usbx_device.c
  * @author  MCD Application Team
  * @brief   USBX Device applicative file
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
#include "app_usbx_device.h"
/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <string.h>
#include "board_commands.h"
#include "lo_control.h"
#include "usb.h"
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

static ULONG cdc_acm_interface_number;
static ULONG cdc_acm_configuration_number;
static UX_SLAVE_CLASS_CDC_ACM_PARAMETER cdc_acm_parameter;
static TX_THREAD ux_device_app_thread;
extern PCD_HandleTypeDef           hpcd_USB_DRD_FS;

/* USER CODE BEGIN PV */
#define CMD_HISTORY_SIZE      8U
#define CMD_HISTORY_LINE_LEN  64U

typedef enum
{
  ESC_STATE_NONE = 0,
  ESC_STATE_GOT_ESC,
  ESC_STATE_GOT_BRACKET
} EscState;

static char cmd_history[CMD_HISTORY_SIZE][CMD_HISTORY_LINE_LEN];
static UINT cmd_history_count = 0U;
static UINT cmd_history_next = 0U;
/* -1 = browsing off (line is either fresh/empty or being typed normally);
   0 = most recently submitted command, 1 = the one before that, etc. */
static int cmd_history_browse = -1;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
static VOID app_ux_device_thread_entry(ULONG thread_input);
static UINT USBD_ChangeFunction(ULONG Device_State);
/* USER CODE BEGIN PFP */
/* Full definitions live here, not just prototypes - the only marker
   guaranteed to survive CubeMX "Generate Code" regeneration. Placing them
   in the unprotected zone above app_ux_device_thread_entry got them
   silently wiped on regeneration. */
static void CDC_EchoString(UX_SLAVE_CLASS_CDC_ACM *cdc_acm, const char *s)
{
  ULONG actual_length;

  ux_device_class_cdc_acm_write(cdc_acm, (UCHAR *)s, (ULONG)strlen(s), &actual_length);
}

static void CDC_EraseChars(UX_SLAVE_CLASS_CDC_ACM *cdc_acm, UINT count)
{
  UINT k;

  for (k = 0U; k < count; k++)
  {
    /* backspace, overwrite with space, backspace again - standard terminal
       "erase last character" sequence. */
    CDC_EchoString(cdc_acm, "\b \b");
  }
}

static void CmdHistory_Push(const char *line)
{
  if (line[0] == '\0')
  {
    return;
  }

  strncpy(cmd_history[cmd_history_next], line, CMD_HISTORY_LINE_LEN - 1U);
  cmd_history[cmd_history_next][CMD_HISTORY_LINE_LEN - 1U] = '\0';
  cmd_history_next = (cmd_history_next + 1U) % CMD_HISTORY_SIZE;
  if (cmd_history_count < CMD_HISTORY_SIZE)
  {
    cmd_history_count++;
  }
  cmd_history_browse = -1;
}

/* browse_offset: 0 = most recently submitted command, 1 = the one before
   that, etc. Returns NULL if browse_offset is out of range. */
static const char *CmdHistory_Get(int browse_offset)
{
  UINT slot;

  if ((browse_offset < 0) || ((UINT)browse_offset >= cmd_history_count))
  {
    return NULL;
  }

  slot = (cmd_history_next + CMD_HISTORY_SIZE - 1U - (UINT)browse_offset) % CMD_HISTORY_SIZE;
  return cmd_history[slot];
}

static void CmdHistory_OnUpArrow(UX_SLAVE_CLASS_CDC_ACM *cdc_acm, char *line_buffer, UINT *line_length)
{
  int next_browse;
  const char *entry;

  next_browse = (cmd_history_browse < 0) ? 0 : (cmd_history_browse + 1);
  if ((UINT)next_browse >= cmd_history_count)
  {
    /* Already at the oldest entry (or no history at all) - do nothing. */
    return;
  }

  entry = CmdHistory_Get(next_browse);
  CDC_EraseChars(cdc_acm, *line_length);
  *line_length = (UINT)strlen(entry);
  memcpy(line_buffer, entry, *line_length);
  CDC_EchoString(cdc_acm, entry);
  cmd_history_browse = next_browse;
}

static void CmdHistory_OnDownArrow(UX_SLAVE_CLASS_CDC_ACM *cdc_acm, char *line_buffer, UINT *line_length)
{
  int next_browse;
  const char *entry;

  if (cmd_history_browse < 0)
  {
    /* Not browsing history - Down arrow has nothing to do. */
    return;
  }

  next_browse = cmd_history_browse - 1;
  CDC_EraseChars(cdc_acm, *line_length);

  if (next_browse < 0)
  {
    /* Moved past the most recent entry - back to a fresh empty line. */
    *line_length = 0U;
    cmd_history_browse = -1;
    return;
  }

  entry = CmdHistory_Get(next_browse);
  *line_length = (UINT)strlen(entry);
  memcpy(line_buffer, entry, *line_length);
  CDC_EchoString(cdc_acm, entry);
  cmd_history_browse = next_browse;
}
/* USER CODE END PFP */

/**
  * @brief  Application USBX Device Initialization.
  * @param  memory_ptr: memory pointer
  * @retval status
  */

UINT MX_USBX_Device_Init(VOID *memory_ptr)
{
  UINT ret = UX_SUCCESS;
  UCHAR *pointer;
  TX_BYTE_POOL *byte_pool = (TX_BYTE_POOL*)memory_ptr;
  /* USER CODE BEGIN MX_USBX_Device_Init 0 */
  /* USER CODE END MX_USBX_Device_Init 0 */

  /* USER CODE BEGIN MX_USBX_Device_Init 1 */
  /* USER CODE END MX_USBX_Device_Init 1 */

  /* Allocate the stack for device application main thread */
  if (tx_byte_allocate(byte_pool, (VOID **) &pointer, UX_DEVICE_APP_THREAD_STACK_SIZE,
                       TX_NO_WAIT) != TX_SUCCESS)
  {
    /* USER CODE BEGIN MAIN_THREAD_ALLOCATE_STACK_ERROR */
    return TX_POOL_ERROR;
    /* USER CODE END MAIN_THREAD_ALLOCATE_STACK_ERROR */
  }

  /* Create the device application main thread */
  if (tx_thread_create(&ux_device_app_thread, UX_DEVICE_APP_THREAD_NAME, app_ux_device_thread_entry,
                       0, pointer, UX_DEVICE_APP_THREAD_STACK_SIZE, UX_DEVICE_APP_THREAD_PRIO,
                       UX_DEVICE_APP_THREAD_PREEMPTION_THRESHOLD, UX_DEVICE_APP_THREAD_TIME_SLICE,
                       UX_DEVICE_APP_THREAD_START_OPTION) != TX_SUCCESS)
  {
    /* USER CODE BEGIN MAIN_THREAD_CREATE_ERROR */
    return TX_THREAD_ERROR;
    /* USER CODE END MAIN_THREAD_CREATE_ERROR */
  }

  /* USER CODE BEGIN MX_USBX_Device_Init 2 */
  /* USER CODE END MX_USBX_Device_Init 2 */

  return ret;
}

/**
  * @brief  MX_USBX_Device_Stack_Init
  *         Intialization of USB Device.
  *         Initialize the device stack, register of device class stack
  *         Register of the usb device controller
  * @param  None
  * @retval ret
  */
UINT MX_USBX_Device_Stack_Init(void)
{
  UINT ret = UX_SUCCESS;
  UCHAR *device_framework_high_speed;
  UCHAR *device_framework_full_speed;
  ULONG device_framework_hs_length;
  ULONG device_framework_fs_length;
  ULONG string_framework_length;
  ULONG language_id_framework_length;
  UCHAR *string_framework;
  UCHAR *language_id_framework;

  /* USER CODE BEGIN MX_USBX_Device_Stack_Init 0 */

  /* USER CODE END MX_USBX_Device_Stack_Init 0 */
  /* Get Device Framework High Speed and get the length */
  device_framework_high_speed = USBD_Get_Device_Framework_Speed(USBD_HIGH_SPEED,
                                                                &device_framework_hs_length);

  /* Get Device Framework Full Speed and get the length */
  device_framework_full_speed = USBD_Get_Device_Framework_Speed(USBD_FULL_SPEED,
                                                                &device_framework_fs_length);

  /* Get String Framework and get the length */
  string_framework = USBD_Get_String_Framework(&string_framework_length);

  /* Get Language Id Framework and get the length */
  language_id_framework = USBD_Get_Language_Id_Framework(&language_id_framework_length);

  /* Install the device portion of USBX */
  if (ux_device_stack_initialize(device_framework_high_speed,
                                 device_framework_hs_length,
                                 device_framework_full_speed,
                                 device_framework_fs_length,
                                 string_framework,
                                 string_framework_length,
                                 language_id_framework,
                                 language_id_framework_length,
                                 USBD_ChangeFunction) != UX_SUCCESS)
  {
    /* USER CODE BEGIN USBX_DEVICE_INITIALIZE_ERROR */
    return UX_ERROR;
    /* USER CODE END USBX_DEVICE_INITIALIZE_ERROR */
  }

  /* Initialize the cdc acm class parameters for the device */
  cdc_acm_parameter.ux_slave_class_cdc_acm_instance_activate   = USBD_CDC_ACM_Activate;
  cdc_acm_parameter.ux_slave_class_cdc_acm_instance_deactivate = USBD_CDC_ACM_Deactivate;
  cdc_acm_parameter.ux_slave_class_cdc_acm_parameter_change    = USBD_CDC_ACM_ParameterChange;

  /* USER CODE BEGIN CDC_ACM_PARAMETER */

  /* USER CODE END CDC_ACM_PARAMETER */

  /* Get cdc acm configuration number */
  cdc_acm_configuration_number = USBD_Get_Configuration_Number(CLASS_TYPE_CDC_ACM, 0);

  /* Find cdc acm interface number */
  cdc_acm_interface_number = USBD_Get_Interface_Number(CLASS_TYPE_CDC_ACM, 0);

  /* Initialize the device cdc acm class */
  if (ux_device_stack_class_register(_ux_system_slave_class_cdc_acm_name,
                                     ux_device_class_cdc_acm_entry,
                                     cdc_acm_configuration_number,
                                     cdc_acm_interface_number,
                                     &cdc_acm_parameter) != UX_SUCCESS)
  {
    /* USER CODE BEGIN USBX_DEVICE_CDC_ACM_REGISTER_ERROR */
    return UX_ERROR;
    /* USER CODE END USBX_DEVICE_CDC_ACM_REGISTER_ERROR */
  }

  /* USER CODE BEGIN MX_USBX_Device_Stack_Init_PostTreatment */
  /* USER CODE END MX_USBX_Device_Stack_Init_PostTreatment */

  /* USER CODE BEGIN MX_USBX_Device_Stack_Init 1 */

  /* USER CODE END MX_USBX_Device_Stack_Init 1 */

  return ret;
}

/**
  * @brief  Function implementing app_ux_device_thread_entry.
  * @param  thread_input: User thread input parameter.
  * @retval none
  */
static VOID app_ux_device_thread_entry(ULONG thread_input)
{
  /* USER CODE BEGIN app_ux_device_thread_entry */
  UX_SLAVE_CLASS_CDC_ACM *cdc_acm;
  UCHAR rx_buf[64];
  UCHAR rx_byte;
  ULONG rx_count;
  ULONG write_discard;
  ULONG rx_index;
  static char line_buffer[64];
  static UINT line_length = 0;
  char response[64];
  EscState esc_state = ESC_STATE_NONE;

  TX_PARAMETER_NOT_USED(thread_input);

  /* PCD-hardware-touching USB init happens here, inside this already-
     running thread, grouped tightly with no gap. Device framework/class
     stack setup (MX_USBX_Device_Stack_Init(), no hardware access) happens
     earlier, before this thread is even created - only
     ux_dcd_stm32_initialize()/HAL_PCD_Start() and MX_USB_PCD_Init() happen
     here. */
  MX_USB_PCD_Init();

  /* A BCDR register dump showed BCDEN=1/PDEN=1 after HAL_PCD_Init() despite
     battery_charging_enable=DISABLE and no HAL_PCDEx_ActivateBCD() call -
     likely reserved/non-functional bits on this silicon, not live BCD
     state (clearing had no effect on enumeration; the real fixes were the
     PMA/BTABLE overlap and missing IAD descriptor). Harmless defensive
     no-op. */
  hpcd_USB_DRD_FS.Instance->BCDR &= ~(USB_BCDR_BCDEN | USB_BCDR_PDEN | USB_BCDR_SDEN);

  if (ux_dcd_stm32_initialize((ULONG)USB_DRD_FS, (ULONG)&hpcd_USB_DRD_FS) != UX_SUCCESS)
  {
    Error_Handler();
  }
  if (HAL_PCD_Start(&hpcd_USB_DRD_FS) != HAL_OK)
  {
    Error_Handler();
  }

  /* Boot-health diagnostic: reaching here means USB init/connect succeeded.
     Still available afterward for TP1/TP2 ON/OFF commands, same as
     TEST_POINT_1 in main.c. */
  HAL_GPIO_WritePin(TEST_POINT_2_GPIO_Port, TEST_POINT_2_Pin, GPIO_PIN_SET);

  for (;;)
  {
    cdc_acm = CDC_ACM_GetInstance();
    if (cdc_acm == UX_NULL)
    {
      /* Not enumerated / no host connected yet */
      tx_thread_sleep(TX_TIMER_TICKS_PER_SECOND / 10);
      continue;
    }

    /* Request a full buffer, not 1 byte: if multiple bytes arrive in one
       USB transfer (pasted text, an escape sequence), reading only 1 byte
       drops the rest instead of queuing it. Looping over rx_count handles
       any burst up to sizeof(rx_buf). */
    if (ux_device_class_cdc_acm_read(cdc_acm, rx_buf, sizeof(rx_buf), &rx_count) != UX_SUCCESS)
    {
      continue;
    }

    if (rx_count == 0)
    {
      continue;
    }

    for (rx_index = 0; rx_index < rx_count; rx_index++)
    {
      rx_byte = rx_buf[rx_index];

      /* Arrow keys arrive as ESC '[' <letter> or ESC 'O' <letter> (Up='A',
         Down='B'). Without this state machine those raw bytes would get
         echoed/appended into line_buffer as garbage. */
      if (esc_state == ESC_STATE_GOT_BRACKET)
      {
        esc_state = ESC_STATE_NONE;
        if (rx_byte == 'A')
        {
          CmdHistory_OnUpArrow(cdc_acm, line_buffer, &line_length);
        }
        else if (rx_byte == 'B')
        {
          CmdHistory_OnDownArrow(cdc_acm, line_buffer, &line_length);
        }
        /* Left/Right/other final bytes: not supported, byte is swallowed. */
        continue;
      }

      if (esc_state == ESC_STATE_GOT_ESC)
      {
        /* Accept both ESC [ (PuTTY "Normal" mode) and ESC O (PuTTY
           "Application" mode) - a user-configurable terminal setting we
           don't control. */
        if ((rx_byte == '[') || (rx_byte == 'O'))
        {
          esc_state = ESC_STATE_GOT_BRACKET;
        }
        else
        {
          esc_state = ESC_STATE_NONE;
        }
        continue;
      }

      if (rx_byte == 0x1BU)
      {
        esc_state = ESC_STATE_GOT_ESC;
        continue;
      }

      if (rx_byte == '\r' || rx_byte == '\n')
      {
        /* Echo CRLF (not the raw byte) so the cursor advances regardless of
           whether the host sent bare CR, bare LF, or CRLF. PuTTY's local
           echo is off, so without this the user sees nothing they type. */
        ux_device_class_cdc_acm_write(cdc_acm, (UCHAR *)"\r\n", 2, &write_discard);
        line_buffer[line_length] = '\0';
        if (line_length > 0)
        {
          CmdHistory_Push(line_buffer);
          /* 1.4.1: serialize board hardware access with the LO-null auto-bias thread. */
          LoControl_Lock();
          Commands_ProcessLine(line_buffer, response, sizeof(response));
          LoControl_Unlock();
          ux_device_class_cdc_acm_write(cdc_acm, (UCHAR *)response, strlen(response), &write_discard);
        }
        line_length = 0;
        continue;
      }

      ux_device_class_cdc_acm_write(cdc_acm, &rx_byte, 1, &write_discard);

      if (line_length < (sizeof(line_buffer) - 1))
      {
        line_buffer[line_length++] = (char)rx_byte;
      }
    }
  }
  /* USER CODE END app_ux_device_thread_entry */
}

/**
  * @brief  MX_USBX_Device_Stack_DeInit
  *         Unitialization of USB Device.
  *         uninitialize the device stack, unregister of device class stack
  *         unregister of the usb device controller
  * @retval ret
  */
UINT MX_USBX_Device_Stack_DeInit(void)
{
  UINT ret = UX_SUCCESS;

  /* USER CODE BEGIN MX_USBX_Device_Stack_DeInit_PreTreatment_0 */
  /* USER CODE END MX_USBX_Device_Stack_DeInit_PreTreatment_0 */

  /* Unregister USB device controller. */

  /* Unregister CDC ACM class. */
  if (ux_device_stack_class_unregister(_ux_system_slave_class_cdc_acm_name,
                                     ux_device_class_cdc_acm_entry) != UX_SUCCESS)
  {
    return UX_ERROR;
  }

  /* The code below is required for uninstalling the device portion of USBX.  */
  if (ux_device_stack_uninitialize() != UX_SUCCESS)
  {
    return UX_ERROR;
  }

  /* USER CODE BEGIN MX_USBX_Device_Stack_DeInit_PreTreatment_1 */
  /* USER CODE END MX_USBX_Device_Stack_DeInit_PreTreatment_1 */

  /* USER CODE BEGIN MX_USBX_Device_Stack_DeInit_PostTreatment */
  /* USER CODE END MX_USBX_Device_Stack_DeInit_PostTreatment */

  return ret;
}

/**
  * @brief  USBD_ChangeFunction
  *         This function is called when the device state changes.
  * @param  Device_State: USB Device State
  * @retval status
  */
static UINT USBD_ChangeFunction(ULONG Device_State)
{
   UINT status = UX_SUCCESS;

  /* USER CODE BEGIN USBD_ChangeFunction0 */

  /* USER CODE END USBD_ChangeFunction0 */

  switch (Device_State)
  {
    case UX_DEVICE_ATTACHED:

      /* USER CODE BEGIN UX_DEVICE_ATTACHED */

      /* USER CODE END UX_DEVICE_ATTACHED */

      break;

    case UX_DEVICE_REMOVED:

      /* USER CODE BEGIN UX_DEVICE_REMOVED */

      /* USER CODE END UX_DEVICE_REMOVED */

      break;

    case UX_DCD_STM32_DEVICE_CONNECTED:

      /* USER CODE BEGIN UX_DCD_STM32_DEVICE_CONNECTED */

      /* USER CODE END UX_DCD_STM32_DEVICE_CONNECTED */

      break;

    case UX_DCD_STM32_DEVICE_DISCONNECTED:

      /* USER CODE BEGIN UX_DCD_STM32_DEVICE_DISCONNECTED */

      /* USER CODE END UX_DCD_STM32_DEVICE_DISCONNECTED */

      break;

    case UX_DCD_STM32_DEVICE_SUSPENDED:

      /* USER CODE BEGIN UX_DCD_STM32_DEVICE_SUSPENDED */

      /* USER CODE END UX_DCD_STM32_DEVICE_SUSPENDED */

      break;

    case UX_DCD_STM32_DEVICE_RESUMED:

      /* USER CODE BEGIN UX_DCD_STM32_DEVICE_RESUMED */

      /* USER CODE END UX_DCD_STM32_DEVICE_RESUMED */

      break;

    case UX_DCD_STM32_SOF_RECEIVED:

      /* USER CODE BEGIN UX_DCD_STM32_SOF_RECEIVED */

      /* USER CODE END UX_DCD_STM32_SOF_RECEIVED */

      break;

    default:

      /* USER CODE BEGIN DEFAULT */

      /* USER CODE END DEFAULT */

      break;

  }

  /* USER CODE BEGIN USBD_ChangeFunction1 */

  /* USER CODE END USBD_ChangeFunction1 */

  return status;
}
/* USER CODE BEGIN 1 */

/* USER CODE END 1 */
