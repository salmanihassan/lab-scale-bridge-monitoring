# CC3220SF LaunchPad build of the Wi-Fi node (TI Arm Clang, gmake from CCS).
#
# Build (PowerShell, from this folder):
#   & 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile all
# Stage 2a (login + HMAC over plain port 1883, no TLS):
#   & 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile all EXTRA_DEFS=-DDT_USE_TLS=0
# Result: build\dt_wifi_node.out (flash it with DSLite, see README.md)
#
# SysConfig 1.20 and FreeRTOS are reused from the ME-2 cc3220_daq folder, as in
# the serial stream build. The Wi-Fi and MQTT helpers (ifmod) come straight
# from the SDK's mqtt_client example. The MQTT client library is compiled
# from SDK source so its packet buffer can hold a one-second batch.

ME2 ?= ..\..\SP2026-ME2\Fall 2026\Digital Twin TI Board Setup\cc3220_daq
SDK ?= C:/ti/simplelink_cc32xx_sdk_7_10_00_13
TICLANG ?= C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS
SYSCONFIG ?= $(ME2)\tools\sysconfig_1.20\sysconfig_cli.bat
FREERTOS ?= $(ME2)\tools\FreeRTOSv202104.00
EXTRA_DEFS ?=

EX = $(SDK)/examples/rtos/CC3220SF_LAUNCHXL/demos/mqtt_client
MQ = $(SDK)/source/ti/net/mqtt

CC = "$(TICLANG)/bin/tiarmclang"
LNK = "$(TICLANG)/bin/tiarmclang"
HEX = "$(TICLANG)/bin/tiarmobjcopy"

NAME = dt_wifi_node
CFG = build/syscfg
OBJDIR = build/obj

APP_SRCS = dt_wifi_app.c sampler.c payload.c dt_hmac.c tls_files.c accelerometer.c loadcells.c temperature.c timing.c
SDK_SRCS = main_freertos.c uart_if.c wifi_if.c mqtt_if.c utils_if.c
MQTT_SRCS = mqttclient.c client_core.c mqtt_common.c mqtt_net_func.c
CFG_SRCS = $(notdir $(wildcard $(CFG)/*.c))

vpath %.c src $(CFG) $(EX)/freertos $(EX)/ifmod $(MQ)/interface $(MQ)/client $(MQ)/common $(MQ)/platform

OBJS = $(addprefix $(OBJDIR)/,$(APP_SRCS:.c=.obj) $(SDK_SRCS:.c=.obj) $(MQTT_SRCS:.c=.obj) $(CFG_SRCS:.c=.obj))

# Rebuild when a project header changes (Wi-Fi settings, keys) or when
# EXTRA_DEFS changes (for example switching between stage 2a and 2b). Each
# EXTRA_DEFS value has its own stamp file, and starting a build in a new mode
# deletes the other stamps, so every object is newer than it again.
APP_HDRS = $(wildcard src/*.h) network_config.h secrets.h
empty :=
space := $(empty) $(empty)
STAMP = $(OBJDIR)/mode$(subst =,_,$(subst $(space),_,$(strip $(EXTRA_DEFS)))).stamp

# MQTT packet buffer: 6.5 KB holds a 100-sample batch (about 5.1 KB worst case)
# plus topic and header. The SDK library default is 1 KB.
# -Isrc comes before the SDK example folder so src/wifi_settings.h and
# src/ota_settings.h are used instead of the SDK copies.
CFLAGS = -Isrc -I. -I$(CFG) "-I$(EX)" "-I$(EX)/ifmod" \
    -DDeviceFamily_CC3220 -DCFG_SL_CL_BUF_LEN=6656 $(EXTRA_DEFS) \
    -Oz -gdwarf-3 -mcpu=cortex-m4 -march=armv7e-m -mthumb -mfloat-abi=soft -mfpu=none \
    "-I$(SDK)/source" \
    "-I$(SDK)/kernel/freertos" \
    "-I$(SDK)/source/ti/posix/ticlang" \
    "-I$(FREERTOS)/FreeRTOS/Source/include" \
    "-I$(FREERTOS)/FreeRTOS/Source/portable/GCC/ARM_CM3"

LFLAGS = "-L$(SDK)/source/ti/net/mqtt/lib" \
    "-L$(SDK)/source/ti/net/lib" \
    "-L$(SDK)/source/ti/net/ota" \
    "-L$(SDK)/source/ti/net/http/http_lib_for_OTA" \
    -lticlang/m4/httpclient_release.a \
    "-L$(SDK)/source/ti/utils/json/lib" \
    "-L$(SDK)/source/ti/drivers/net/wifi/slnetif" \
    "-L$(SDK)/source" \
    "-L$(SDK)/source/ti/drivers/net/wifi" \
    $(CFG)/ti_utils_build_linker.cmd.genlibs \
    -lti/devices/cc32xx/driverlib/ticlang/Release/driverlib.a \
    $(EX)/freertos/ticlang/cc32xxsf_freertos.cmd \
    "-Wl,-m,build/$(NAME).map" -Wl,--rom_model -Wl,--warn_sections \
    "-L$(TICLANG)/lib" -llibc.a

.PHONY: all syscfg firmware clean check_config

# Two passes: SysConfig first, then a second make that can see which .c
# files SysConfig generated.
all: check_config syscfg
	@ "$(MAKE)" -f makefile firmware

check_config:
	@ if not exist network_config.h (echo. & echo ERROR: network_config.h is missing. Copy network_config.example.h to network_config.h and fill in the Wi-Fi name, password and broker IP. & echo. & exit 1)
	@ if not exist secrets.h (echo. & echo ERROR: secrets.h is missing. Run  py host\dt_setup_security.py  once, it writes secrets.h and the broker files. & echo. & exit 1)

syscfg:
	@ if not exist build\syscfg mkdir build\syscfg
	@ if not exist build\obj mkdir build\obj
	@ echo Generating SysConfig files...
	@ "$(SYSCONFIG)" --product $(SDK)/.metadata/product.json --script dt_wifi.syscfg --output $(CFG) --compiler ticlang

firmware: build/$(NAME).out

$(STAMP):
	@ if exist $(subst /,\,$(OBJDIR))\*.stamp del /Q $(subst /,\,$(OBJDIR))\*.stamp
	@ echo build options: $(EXTRA_DEFS) > $(subst /,\,$@)

$(OBJDIR)/%.obj: %.c $(APP_HDRS) $(STAMP)
	@ echo Building $@
	@ $(CC) $(CFLAGS) -c $< -o $@

build/$(NAME).out: $(OBJS)
	@ echo Linking $@
	@ $(LNK) -Wl,-u,_c_int00 $(OBJS) $(LFLAGS) -o $@
	@ echo Done: $@

clean:
	@ if exist build rmdir /S /Q build
