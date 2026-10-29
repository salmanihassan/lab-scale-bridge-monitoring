#ifndef NETWORK_CONFIG_H_
#define NETWORK_CONFIG_H_

/*
 * Copy this file to network_config.h (same folder) and fill in the three
 * settings below. network_config.h is listed in .gitignore so the Wi-Fi
 * password never ends up in the repo.
 *
 * The board supports 2.4 GHz networks only, WPA2-Personal (password) or open.
 */

/* Network name and password, exactly as the router or hotspot shows them. */
#define DT_WIFI_SSID        "your-network-name"
#define DT_WIFI_PASSWORD    "your-network-password"

/* IPv4 address of the laptop running Mosquitto, on that same network.
 * On Windows: run ipconfig and use the "IPv4 Address" of the Wi-Fi adapter.
 * Give the laptop a DHCP reservation on the router so this never changes. */
#define DT_BROKER_IP        "192.168.1.2"
#define DT_BROKER_PORT      1883

/* Identifies this node in every packet and in the MQTT topics. */
#define DT_DEVICE_ID        "CC3220SF_NODE_01"

#endif /* NETWORK_CONFIG_H_ */
