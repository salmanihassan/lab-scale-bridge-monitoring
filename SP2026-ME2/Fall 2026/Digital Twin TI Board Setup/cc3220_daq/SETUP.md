# CC3220SF LaunchPad development-board setup

## Installed toolchain

| Item | Location / version |
| --- | --- |
| CCS | `C:\ti\ccs2101` / 21.0.1 |
| TI Arm Clang | `C:\ti\ccs2101\ccs\tools\compiler\ti-cgt-armllvm_5.1.1.LTS` / 5.1.1 LTS |
| CC32xx SDK | `C:\ti\simplelink_cc32xx_sdk_7_10_00_13` |
| UniFlash | `C:\ti\uniflash_9.6.0` / 9.6.0.5764 |
| Project SysConfig | `tools\sysconfig_1.20` / 1.20.0.3587 |
| Project FreeRTOS | `tools\FreeRTOSv202104.00` / 202104.00 |

CCS's bundled SysConfig 1.28 does not support CC3220SF; use the project-local
1.20 executable for SysConfig generation.

## Build

From `cc3220_daq`:

```powershell
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' -f makefile all
```

This writes `build\digital_twin_daq.out` and `build\digital_twin_daq.bin`.
The default build starts `ACQ_MODE_I2C_SCAN`; it is diagnostic-only and keeps
the vibration motor compile-time disabled.

## Provision a repurposed development board

> Warning: this is for a development LaunchPad whose serial-flash state may be
> replaced. It formats the CC3220SF serial flash, installs the SDK service
> pack/default catalog, and replaces the former application, network settings,
> and user certificates. Do not use it on a board whose existing state must be
> retained.

The source manifest is `development_provision.syscfg`. It selects ImageCreator
development mode plus the SDK-default service pack, without an MCU image,
user files, user credentials, production security, OTP, secure bootloader, or
debug lock.

```powershell
$proj = 'C:\Users\blayn\Downloads\Digital Twin TI Board Setup\cc3220_daq'
$sdk = 'C:\ti\simplelink_cc32xx_sdk_7_10_00_13'
$syscfg = "$proj\tools\sysconfig_1.20\sysconfig_cli.bat"
$img = "$sdk\source\ti\drivers\net\imagecreator\bin\SLImageCreator.exe"
$prov = "$proj\build\development_provision_minimal"

& $syscfg --product "$sdk\metadata\product.json" --script "$proj\development_provision.syscfg" --output $prov --compiler ticlang
& $img syscfg create_image --sdk_path $sdk --json "$prov\ti_drivers_net_wifi_config.json" --file "$proj\build\cc3220sf_development_provision.sli"
& $img syscfg program --file "$proj\build\cc3220sf_development_provision.sli" --json "$prov\ti_drivers_net_wifi_config.json"
```

The final command is the state-changing provisioning step. On this board it
completed at `Image Programming: 100% (84224/84224)`.

## Program and run the DAQ `.out` over XDS110

CCS 21.0.1's installed target database has no CC3220SF definition, while
UniFlash 9.6 supplies the official CC3220SF target/flash-loader definitions.
Use the UniFlash Debug Server with the project-local wrapper
`build\cc3220sf_xds110_uniflash.ccxml`; that wrapper references the installed
TI XDS110 and CC3220SF database XML files unchanged.

```powershell
$env:TI_APPDATA_DIR = 'C:\Users\blayn\Downloads\Digital Twin TI Board Setup\cc3220_daq\build\uniflash_appdata'
$dslite = 'C:\ti\uniflash_9.6.0\deskdb\content\TICloudAgent\win\ccs_base\DebugServer\bin\DSLite.exe'
$cfg = 'C:\Users\blayn\Downloads\Digital Twin TI Board Setup\cc3220_daq\build\cc3220sf_xds110_uniflash.ccxml'
$out = 'C:\Users\blayn\Downloads\Digital Twin TI Board Setup\cc3220_daq\build\digital_twin_daq.out'

& $dslite flash --config $cfg --core 0 --verbose --run $out
```

This is an on-chip executable-flash `.out` load/run operation through the
XDS110. It does not program an `.sli` application image or change the service
pack, filesystem, certificates, or network configuration.

For the verified board, COM3 is the XDS110 application UART: **230400 baud,
8-N-1, no flow control**. See [STATUS.md](STATUS.md) for the captured output
and known XDS110 firmware-version warning.
