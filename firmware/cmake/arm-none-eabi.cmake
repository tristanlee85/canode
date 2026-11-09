# Cross toolchain for the STM32G0 (Cortex-M0+). Picked up automatically by
# firmware/CMakeLists.txt; arm-none-eabi-gcc must be on PATH (brew install
# --cask gcc-arm-embedded, or the Arm GNU Toolchain installer).
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR arm)

set(CMAKE_C_COMPILER   arm-none-eabi-gcc)
set(CMAKE_ASM_COMPILER arm-none-eabi-gcc)
set(CMAKE_OBJCOPY      arm-none-eabi-objcopy CACHE FILEPATH "")
set(CMAKE_SIZE         arm-none-eabi-size CACHE FILEPATH "")

# Don't try to link a host-style test program while probing the compiler.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

set(CPU_FLAGS "-mcpu=cortex-m0plus -mthumb")
set(CMAKE_C_FLAGS_INIT   "${CPU_FLAGS} -ffunction-sections -fdata-sections")
set(CMAKE_ASM_FLAGS_INIT "${CPU_FLAGS} -x assembler-with-cpp")
# -nostartfiles: the ST startup file (startup_stm32g0b1xx.s) is our crt0. Linking
# newlib's crt0 too would drag in exit() -> stdio -> _write/_close stubs.
set(CMAKE_EXE_LINKER_FLAGS_INIT "${CPU_FLAGS} -specs=nano.specs -specs=nosys.specs -nostartfiles -Wl,--gc-sections")

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
