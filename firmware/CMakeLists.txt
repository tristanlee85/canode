# canode firmware. One configure builds every board:
#   cmake -S firmware -B firmware/build && cmake --build firmware/build
# Outputs: build/canode.{elf,bin,hex} and build/nucleo_g0b1re.{elf,bin,hex}
cmake_minimum_required(VERSION 3.24)

if(NOT CMAKE_TOOLCHAIN_FILE)
    set(CMAKE_TOOLCHAIN_FILE ${CMAKE_CURRENT_LIST_DIR}/cmake/arm-none-eabi.cmake)
endif()
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE MinSizeRel CACHE STRING "Debug, MinSizeRel, Release" FORCE)
endif()

project(canode_fw VERSION 0.1.0 LANGUAGES C ASM)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_EXTENSIONS ON)   # gnu11: CMSIS uses GCC asm/attribute extensions

include(cmake/deps.cmake)

# Version string: 0.1.0, plus the git commit when built from a checkout.
execute_process(COMMAND git describe --always --dirty --exclude "*"
                WORKING_DIRECTORY ${CMAKE_CURRENT_LIST_DIR}
                OUTPUT_VARIABLE GIT_REV OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
set(FW_VERSION ${PROJECT_VERSION})
if(GIT_REV)
    set(FW_VERSION "${FW_VERSION}+${GIT_REV}")
endif()

# Warnings for our own code. Third-party sources get the same flags; their
# headers are SYSTEM includes so their internals don't drown out ours.
set(OUR_WARNINGS -Wall -Wextra -Wshadow -Wdouble-promotion -Wformat=2 -Wundef)

set(LIB_SOURCES
    lib/bittiming.c
    lib/candump.c
    lib/frame_ring.c
    lib/gateway.c
    lib/parse.c
    lib/power.c
    lib/shell.c)

set(APP_SOURCES
    src/main.c
    src/system.c
    src/uart.c
    src/usb.c
    src/console.c
    src/can_drv.c
    src/selftest.c
    src/sleep.c
    src/commands.c)

set(VENDOR_SOURCES
    ${CMSIS_DEVICE_DIR}/Source/Templates/gcc/startup_stm32g0b1xx.s
    ${CMSIS_DEVICE_DIR}/Source/Templates/system_stm32g0xx.c
    ${HAL_DIR}/Src/stm32g0xx_hal.c
    ${HAL_DIR}/Src/stm32g0xx_hal_cortex.c
    ${HAL_DIR}/Src/stm32g0xx_hal_fdcan.c
    ${HAL_DIR}/Src/stm32g0xx_hal_gpio.c
    ${HAL_DIR}/Src/stm32g0xx_hal_pwr.c
    ${HAL_DIR}/Src/stm32g0xx_hal_pwr_ex.c
    ${HAL_DIR}/Src/stm32g0xx_hal_rcc.c
    ${HAL_DIR}/Src/stm32g0xx_hal_rcc_ex.c
    ${TINYUSB_DIR}/src/tusb.c
    ${TINYUSB_DIR}/src/common/tusb_fifo.c
    ${TINYUSB_DIR}/src/device/usbd.c
    ${TINYUSB_DIR}/src/class/cdc/cdc_device.c
    ${TINYUSB_DIR}/src/portable/st/stm32_fsdev/dcd_stm32_fsdev.c
    ${TINYUSB_DIR}/src/portable/st/stm32_fsdev/fsdev_common.c)

# canode_firmware(<target> <BOARD_xxx define>)
function(canode_firmware TARGET BOARD_DEF)
    add_executable(${TARGET} ${LIB_SOURCES} ${APP_SOURCES} ${VENDOR_SOURCES})
    set_target_properties(${TARGET} PROPERTIES SUFFIX ".elf")
    target_compile_definitions(${TARGET} PRIVATE
        ${BOARD_DEF} STM32G0B1xx USE_HAL_DRIVER
        CANODE_FW_VERSION="${FW_VERSION}")
    target_include_directories(${TARGET} PRIVATE src lib)
    target_include_directories(${TARGET} SYSTEM PRIVATE
        ${CMSIS_CORE_DIR}/Include
        ${CMSIS_DEVICE_DIR}/Include
        ${HAL_DIR}/Inc
        ${TINYUSB_DIR}/src)
    target_compile_options(${TARGET} PRIVATE
        $<$<COMPILE_LANGUAGE:C>:${OUR_WARNINGS}> -g3)
    target_link_options(${TARGET} PRIVATE
        -T${CMAKE_CURRENT_SOURCE_DIR}/ld/stm32g0b1xb.ld
        -Wl,-Map=$<TARGET_FILE_DIR:${TARGET}>/${TARGET}.map
        -Wl,--print-memory-usage
        -Wl,--no-warn-rwx-segments)
    set_property(TARGET ${TARGET} APPEND PROPERTY LINK_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/ld/stm32g0b1xb.ld)
    add_custom_command(TARGET ${TARGET} POST_BUILD
        COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${TARGET}> $<TARGET_FILE_DIR:${TARGET}>/${TARGET}.bin
        COMMAND ${CMAKE_OBJCOPY} -O ihex   $<TARGET_FILE:${TARGET}> $<TARGET_FILE_DIR:${TARGET}>/${TARGET}.hex
        COMMAND ${CMAKE_SIZE} $<TARGET_FILE:${TARGET}>
        VERBATIM)
endfunction()

canode_firmware(canode       BOARD_CANODE)
canode_firmware(nucleo_g0b1re BOARD_NUCLEO_G0B1RE)

# Host unit tests for lib/ (uses the system compiler, not the cross compiler):
#   cmake --build firmware/build --target host-tests
add_custom_target(host-tests
    COMMAND ${CMAKE_CURRENT_SOURCE_DIR}/test/run_tests.sh
    USES_TERMINAL VERBATIM)
