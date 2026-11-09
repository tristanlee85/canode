# Third-party sources, downloaded at configure time and pinned by SHA-256.
#
# They land in firmware/.deps/ (git-ignored) rather than the build directory,
# so `rm -rf build` doesn't trigger a re-download. To upgrade: change the
# version, set the hash to the output of `shasum -a 256` on the new archive.
# Must be set before include(FetchContent), which otherwise defaults it to build/_deps.
get_filename_component(_deps_dir "${CMAKE_CURRENT_LIST_DIR}/../.deps" ABSOLUTE)
set(FETCHCONTENT_BASE_DIR "${_deps_dir}" CACHE PATH "Download cache for firmware deps")
include(FetchContent)
set(FETCHCONTENT_QUIET ON)

# ST device headers (register definitions, startup code, SystemInit).
FetchContent_Declare(cmsis_device_g0
    URL      https://github.com/STMicroelectronics/cmsis-device-g0/archive/refs/tags/v1.4.5.tar.gz
    URL_HASH SHA256=494164a7f00a3571669df90a48707fe3ec38716647fdecbbad64f18dcea65037
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SOURCE_SUBDIR _none_)   # sources only: don't add_subdirectory() anything

# ST HAL driver (RCC, GPIO, FDCAN, PWR, Cortex).
FetchContent_Declare(stm32g0xx_hal_driver
    URL      https://github.com/STMicroelectronics/stm32g0xx-hal-driver/archive/refs/tags/v1.4.7.tar.gz
    URL_HASH SHA256=1a9e2da373e47fd816f5487d3254b4161a9c21420344dc0dc8626546ee2480a0
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SOURCE_SUBDIR _none_)

# Arm CMSIS 6 core headers (core_cm0plus.h, cmsis_gcc.h).
FetchContent_Declare(cmsis_6
    URL      https://github.com/ARM-software/CMSIS_6/archive/refs/tags/v6.4.0.tar.gz
    URL_HASH SHA256=3f8ccae0c7f8ec2e1db2b671ddd1f5d97f5b42558ca7b15fff337c43d813fa02
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SOURCE_SUBDIR _none_)

# TinyUSB (USB device stack, CDC class, STM32 FSDEV driver).
FetchContent_Declare(tinyusb
    URL      https://github.com/hathach/tinyusb/archive/refs/tags/0.21.0.tar.gz
    URL_HASH SHA256=b7cdf35c5ccefb0f61640aff94a732ab4ebcb21498201e4a161545891b23ba01
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
    SOURCE_SUBDIR _none_)

FetchContent_MakeAvailable(cmsis_device_g0 stm32g0xx_hal_driver cmsis_6 tinyusb)

set(CMSIS_DEVICE_DIR ${cmsis_device_g0_SOURCE_DIR})
set(HAL_DIR          ${stm32g0xx_hal_driver_SOURCE_DIR})
set(CMSIS_CORE_DIR   ${cmsis_6_SOURCE_DIR}/CMSIS/Core)
set(TINYUSB_DIR      ${tinyusb_SOURCE_DIR})
