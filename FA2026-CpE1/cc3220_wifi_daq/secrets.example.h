/*
 * FORMAT REFERENCE ONLY. Do not copy this file to secrets.h.
 *
 * secrets.h is generated, together with the broker's certificates, password
 * file and ACL, by:
 *     py host\dt_setup_security.py
 * It is listed in .gitignore. Every value below is a placeholder.
 */
#error "secrets.example.h is a format reference. Run host/dt_setup_security.py to generate secrets.h."

#ifndef SECRETS_H_
#define SECRETS_H_

#include <stdint.h>

/* HMAC-SHA256 key that signs every batch, and its id (sent in each packet). */
#define DT_HMAC_KID         "k20260101-0000"
static const uint8_t DT_HMAC_KEY[32] = { 0x00 /* 32 random bytes */ };

/* This board's MQTT login. The broker's ACL lets it write bridge/<DEVICE_ID>/# only. */
#define DT_MQTT_USER        "dt_node01"
#define DT_MQTT_PASSWORD    "random-password"

/* Project CA certificate (public, not secret), copied to the network
 * processor's file system at boot and used to check the broker. */
#define DT_CA_FILE_NAME     "dt-ca.pem"
static const char DT_CA_PEM[] =
    "-----BEGIN CERTIFICATE-----\n"
    "...\n"
    "-----END CERTIFICATE-----\n";

#endif /* SECRETS_H_ */
