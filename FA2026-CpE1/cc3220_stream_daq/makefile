# CC3220SF LaunchPad TIClang build of the stream firmware.
# Based on the ME-2 cc3220_daq makefile. SysConfig 1.20 and the FreeRTOS kernel
# are reused from that project folder, so it must stay where it is in the repo.
#
# Build (PowerShell, from this folder):
#   & 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile all
# Single-sensor diagnostic instead of the stream, for example:
#   & 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile clean all EXTRA_DEFS=-DDT_DIAG_LOADCELLS
# Any path can be overridden on the command line, for example SDK=C:/ti/simplelink_cc32xx_sdk_7_10_00_13

ME2 ?= ..\..\SP2026-ME2\Fall 2026\Digital Twin TI Board Setup\cc3220_daq
SDK ?= C:/ti/simplelink_cc32xx_sdk_7_10_00_13
TICLANG ?= C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS
SYSCONFIG ?= $(ME2)\tools\sysconfig_1.20\sysconfig_cli.bat
FREERTOS ?= $(ME2)\tools\FreeRTOSv202104.00
EXTRA_DEFS ?=

CC = "$(TICLANG)/bin/tiarmclang"
LNK = "$(TICLANG)/bin/tiarmclang"
HEX = "$(TICLANG)/bin/tiarmobjcopy"

CFG = build/syscfg
NAME = dt_stream_daq
APP_SRCS = src/main_freertos.c src/acquisition.c src/accelerometer.c src/loadcells.c src/temperature.c src/timing.c src/vibration_motor.c
CFG_SRCS = $(CFG)/ti_drivers_config.c $(CFG)/ti_freertos_config.c $(CFG)/ti_freertos_portable_config.c
OBJS = $(APP_SRCS:src/%.c=build/%.obj) $(CFG_SRCS:$(CFG)/%.c=build/%.obj)

CFLAGS = -Isrc -I$(CFG) -DDeviceFamily_CC3220 $(EXTRA_DEFS) -Oz -gdwarf-3 -mcpu=cortex-m4 -march=armv7e-m -mthumb -mfloat-abi=soft -mfpu=none \
    "-I$(SDK)/source" \
    "-I$(SDK)/kernel/freertos" \
    "-I$(SDK)/source/ti/posix/ticlang" \
    "-I$(FREERTOS)/FreeRTOS/Source/include" \
    "-I$(FREERTOS)/FreeRTOS/Source/portable/GCC/ARM_CM3"

LFLAGS = "-L$(SDK)/source" \
    $(CFG)/ti_utils_build_linker.cmd.genlibs \
    -lti/devices/cc32xx/driverlib/ticlang/Release/driverlib.a \
    $(SDK)/examples/rtos/CC3220SF_LAUNCHXL/drivers/empty/freertos/ticlang/cc32xxsf_freertos.cmd \
    "-Wl,-m,build/$(NAME).map" -Wl,--rom_model -Wl,--warn_sections \
    "-L$(TICLANG)/lib" -llibc.a

.PHONY: all syscfg clean
all: build/$(NAME).bin

syscfg:
	@ if not exist build\syscfg mkdir build\syscfg
	@ echo Generating validated SysConfig files...
	@ "$(SYSCONFIG)" --product $(SDK)/.metadata/product.json --script digital_twin_daq.syscfg --output $(CFG) --compiler ticlang

build/%.obj: src/%.c syscfg
	@ echo Building $@
	@ $(CC) $(CFLAGS) -c $< -o $@

build/%.obj: $(CFG)/%.c syscfg
	@ echo Building $@
	@ $(CC) $(CFLAGS) -c $< -o $@

build/$(NAME).out: $(OBJS)
	@ echo Linking $@
	@ $(LNK) -Wl,-u,_c_int00 $(OBJS) $(LFLAGS) -o $@

build/$(NAME).bin: build/$(NAME).out
	@ echo Creating $@
	@ $(HEX) -O binary --only-section .text --only-section .const --only-section .cinit --only-section .rodata --only-section .resetVecs $< $@

clean:
	@ if exist build del /Q build\*.obj build\$(NAME).out build\$(NAME).map build\$(NAME).bin 2>NUL
