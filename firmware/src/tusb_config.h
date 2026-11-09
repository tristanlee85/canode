/*
 * tusb_config.h - TinyUSB configuration: one CDC-ACM (virtual serial) interface.
 */
#ifndef TUSB_CONFIG_H
#define TUSB_CONFIG_H

#define CFG_TUSB_MCU           OPT_MCU_STM32G0
#define CFG_TUSB_OS            OPT_OS_NONE      /* bare metal: tud_task() from the main loop */
#define CFG_TUSB_DEBUG         0
#define CFG_TUSB_MEM_SECTION
#define CFG_TUSB_MEM_ALIGN     __attribute__((aligned(4)))

#define BOARD_TUD_RHPORT       0
#define CFG_TUD_ENABLED        1
#define CFG_TUD_MAX_SPEED      OPT_MODE_FULL_SPEED
#define CFG_TUD_ENDPOINT0_SIZE 64

#define CFG_TUD_CDC            1
#define CFG_TUD_MSC            0
#define CFG_TUD_HID            0
#define CFG_TUD_MIDI           0
#define CFG_TUD_VENDOR         0

/* A full 1 Mbit/s bus is ~8000 frames/s x ~45 bytes = ~360 KB/s of candump text.
 * Full-speed bulk can carry that, but the host polls in bursts, so give the TX
 * side a deep buffer. RAM is plentiful (128 KB). */
#define CFG_TUD_CDC_RX_BUFSIZE 256
#define CFG_TUD_CDC_TX_BUFSIZE 4096
#define CFG_TUD_CDC_EP_BUFSIZE 64

#endif
