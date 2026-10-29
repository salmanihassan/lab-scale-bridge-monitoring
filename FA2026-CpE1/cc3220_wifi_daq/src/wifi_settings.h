/*
 * Settings read by the SDK's ifmod/wifi_if.c (mqtt_client example, SDK 7.10).
 * Same macro names as the SDK file. Differences:
 *   - the network name and password come from ../network_config.h;
 *   - provisioning is off, so a wrong password never turns the board into an
 *     access point waiting for a phone app. It just keeps retrying.
 */
#ifndef WIFI_SETTINGS_H
#define WIFI_SETTINGS_H

#include "network_config.h"

#define WIFI_IF_DEBUG_LEVEL         E_INFO

#define PROVISIONING_MODE           WifiProvMode_OFF
#define PROVISIONING_CMD            SL_WLAN_PROVISIONING_CMD_START_MODE_APSC
#define PROVISIONING_TIMEOUT        0
#define PROVISIONING_AP_PASSWORD    NULL
#define PROVISIONING_SC_KEY         NULL
#define FORCE_PROVISIONING          (0)

#define AP_SSID                     DT_WIFI_SSID
#define AP_PASSWORD                 DT_WIFI_PASSWORD

/* Unused while AP_SSID is set (kept because wifi_if.c refers to them). */
#define AP_CFG_FILENAME             "network.cfg"
#define AP_CFG_TOKEN                12345678
#define AP_CFG_MAX_SIZE             100

#endif /* WIFI_SETTINGS_H */
