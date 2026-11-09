/*
 * usb.c - TinyUSB glue: clocks/IRQ, descriptors, and a small CDC wrapper.
 *
 * Why TinyUSB instead of ST's USB device middleware: it supports the G0's
 * "FSDEV" USB peripheral directly (including the G0B1's 32-bit packet memory),
 * is actively maintained on GitHub with tagged releases, needs no CubeMX code
 * generation, and its CDC class is a few calls (read/write/flush). ST's
 * middleware would need generated glue and the HAL PCD module.
 */
#include "usb.h"

#include <string.h>

#include "stm32g0xx_hal.h"
#include "system.h"
#include "tusb.h"

/* pid.codes test VID/PID (https://pid.codes/1209/0001/): fine for development
 * and private use, not for distribution. Get a real PID before shipping boards. */
#define USB_VID 0x1209
#define USB_PID 0x0001

static volatile bool s_open_event;

void usb_init(void)
{
    /* USB clock (HSI48) and CRS were set up in system_clock_init(). The G0B1
     * also needs VDDUSB declared valid before the transceiver will power up. */
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWREx_EnableVddUSB();
    __HAL_RCC_USB_CLK_ENABLE();

    /* PA11/PA12 need no GPIO setup: enabling the USB peripheral takes them over.
     * USB shares its interrupt with the USB-C PD (UCPD) blocks, which we don't use. */
    NVIC_SetPriority(USB_UCPD1_2_IRQn, 1);

    tusb_rhport_init_t dev_init = {.role = TUSB_ROLE_DEVICE, .speed = TUSB_SPEED_AUTO};
    tusb_init(BOARD_TUD_RHPORT, &dev_init);
}

void USB_UCPD1_2_IRQHandler(void)
{
    tusb_int_handler(BOARD_TUD_RHPORT, true);
}

/* TinyUSB uses this for timeouts in a no-RTOS build. */
uint32_t tusb_time_millis_api(void)
{
    return system_millis();
}

void usb_poll(void)
{
    tud_task();
}

bool usb_connected(void)
{
    return tud_cdc_connected();
}

bool usb_take_open_event(void)
{
    if (!s_open_event)
        return false;
    s_open_event = false;
    return true;
}

int usb_getc(void)
{
    if (!tud_cdc_available())
        return -1;
    return (int)tud_cdc_read_char();
}

size_t usb_write(const char *s, size_t n)
{
    if (!tud_cdc_connected())
        return 0;   /* nobody listening: drop rather than fill the FIFO */
    size_t done = 0;
    uint32_t start = system_millis();
    while (done < n) {
        done += tud_cdc_write(s + done, (uint32_t)(n - done));
        if (done < n) {
            /* FIFO full: let TinyUSB push packets out, but give up after 20 ms
             * so a stalled host can't freeze CAN processing. */
            tud_cdc_write_flush();
            tud_task();
            if (!tud_cdc_connected() || system_millis() - start > 20u)
                break;
        }
    }
    tud_cdc_write_flush();
    return done;
}

void tud_cdc_line_state_cb(uint8_t itf, bool dtr, bool rts)
{
    (void)itf;
    (void)rts;
    if (dtr)
        s_open_event = true;
}

/* ---- descriptors -------------------------------------------------------- */

static const tusb_desc_device_t desc_device = {
    .bLength = sizeof(tusb_desc_device_t),
    .bDescriptorType = TUSB_DESC_DEVICE,
    .bcdUSB = 0x0200,
    /* IAD class codes, as required for a CDC function made of two interfaces. */
    .bDeviceClass = TUSB_CLASS_MISC,
    .bDeviceSubClass = MISC_SUBCLASS_COMMON,
    .bDeviceProtocol = MISC_PROTOCOL_IAD,
    .bMaxPacketSize0 = CFG_TUD_ENDPOINT0_SIZE,
    .idVendor = USB_VID,
    .idProduct = USB_PID,
    .bcdDevice = 0x0100,
    .iManufacturer = 1,
    .iProduct = 2,
    .iSerialNumber = 3,
    .bNumConfigurations = 1,
};

const uint8_t *tud_descriptor_device_cb(void)
{
    return (const uint8_t *)&desc_device;
}

enum { ITF_NUM_CDC = 0, ITF_NUM_CDC_DATA, ITF_NUM_TOTAL };

#define EPNUM_CDC_NOTIF 0x81
#define EPNUM_CDC_OUT   0x02
#define EPNUM_CDC_IN    0x82
#define CONFIG_TOTAL_LEN (TUD_CONFIG_DESC_LEN + TUD_CDC_DESC_LEN)

static const uint8_t desc_configuration[] = {
    /* config number, interface count, string index, total length, attributes, power mA */
    TUD_CONFIG_DESCRIPTOR(1, ITF_NUM_TOTAL, 0, CONFIG_TOTAL_LEN, 0x00, 100),
    /* interface number, string index, notify EP + size, data EP out/in + size */
    TUD_CDC_DESCRIPTOR(ITF_NUM_CDC, 4, EPNUM_CDC_NOTIF, 8, EPNUM_CDC_OUT, EPNUM_CDC_IN, 64),
};

const uint8_t *tud_descriptor_configuration_cb(uint8_t index)
{
    (void)index;
    return desc_configuration;
}

static const char *const string_desc[] = {
    NULL,               /* 0: language (handled below) */
    "canode",           /* 1: manufacturer */
    "canode dual CAN",  /* 2: product */
    NULL,               /* 3: serial = chip unique ID */
    "canode shell",     /* 4: CDC interface */
};

const uint16_t *tud_descriptor_string_cb(uint8_t index, uint16_t langid)
{
    (void)langid;
    static uint16_t desc[32];
    char serial[25];
    const char *str;
    size_t len;

    if (index == 0) {
        desc[1] = 0x0409;   /* English (US) */
        len = 1;
    } else {
        if (index >= sizeof(string_desc) / sizeof(string_desc[0]))
            return NULL;
        if (index == 3) {
            system_uid_string(serial);
            str = serial;
        } else {
            str = string_desc[index];
        }
        len = strlen(str);
        if (len > 31)
            len = 31;
        for (size_t i = 0; i < len; i++)
            desc[1 + i] = (uint16_t)str[i];   /* ASCII -> UTF-16 */
    }
    desc[0] = (uint16_t)((TUSB_DESC_STRING << 8) | (2u * len + 2u));
    return desc;
}
