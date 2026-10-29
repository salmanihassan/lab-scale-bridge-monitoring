#!/usr/bin/env python3
"""
One-time security setup for the bridge digital twin Wi-Fi link (stage 2).

Generates everything the board, the broker and the receiver need, outside git:

  ../secrets.h                  board: HMAC key and key id, MQTT login, CA certificate
  secrets/keys.json             receiver: HMAC keys by key id, MQTT logins
  secrets/ca.crt, ca.key        project certificate authority (ca.key never leaves the laptop)
  secrets/server.crt, .key      broker certificate, signed by the project CA
  secrets/passwd                Mosquitto password file (PBKDF2-SHA512, Mosquitto 2 format)
  secrets/acl                   Mosquitto topic rules
  secrets/mosquitto_2a.conf     stage 2a broker: login + ACL on port 1883, no TLS
  secrets/mosquitto_2b.conf     stage 2b broker: TLS 1.2+ on port 8883, login + ACL

Usage (Windows PowerShell, from the host folder):
  py -m pip install cryptography
  py dt_setup_security.py
  py dt_setup_security.py --force      # new keys for everything (rebuild and reflash after)

The broker IP and device id are read from ../network_config.h. The board does
not check the IP inside the broker certificate (it connects by address and
checks the CA chain), so a changed laptop IP only needs network_config.h.
"""

import argparse
import base64
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import secrets
import socket
import stat
import sys
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
except ImportError:  # pragma: no cover
    sys.exit("The cryptography package is missing. Install it with:  py -m pip install cryptography")

HERE = Path(__file__).resolve().parent
FIRMWARE_DIR = HERE.parent

BOARD_USER = "dt_node01"
RECEIVER_USER = "dt_receiver"
CA_FILE_NAME = "dt-ca.pem"          # name of the CA file on the board's network processor
TLS12_CIPHERS = "ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-CHACHA20-POLY1305"


# ------------------------------------------------------------------ helpers

def read_network_config(path):
    """DT_BROKER_IP and DT_DEVICE_ID from network_config.h, or None."""
    if not path.exists():
        return None, None
    text = path.read_text(errors="replace")

    def get(name):
        m = re.search(r'^\s*#define\s+' + name + r'\s+"([^"]*)"', text, re.M)
        return m.group(1) if m else None

    return get("DT_BROKER_IP"), get("DT_DEVICE_ID")


def mosquitto_hash(password, iterations=101):
    """Password file entry in Mosquitto 2's $7$ format (PBKDF2-HMAC-SHA512, 12-byte salt)."""
    salt = secrets.token_bytes(12)
    digest = hashlib.pbkdf2_hmac("sha512", password.encode(), salt, iterations, 64)
    return f"$7${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def write_private(path, data):
    """Write a file readable by the current user only (where the OS supports it)."""
    path.write_bytes(data if isinstance(data, bytes) else data.encode())
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def key_pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                             serialization.NoEncryption())


def make_ca(now):
    key = new_key()
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Bridge Digital Twin project"),
                      x509.NameAttribute(NameOID.COMMON_NAME, "DT project CA")])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=30))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=True, crl_sign=True,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
            .sign(key, hashes.SHA256()))
    return key, cert


def make_server(ca_key, ca_cert, ips, now):
    key = new_key()
    sans = [x509.DNSName("localhost")]
    host = socket.gethostname()
    if host and re.fullmatch(r"[A-Za-z0-9.-]+", host):
        sans.append(x509.DNSName(host))
    sans += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Bridge Digital Twin project"),
                                     x509.NameAttribute(NameOID.COMMON_NAME, "dt-broker")]))
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=30))
            .not_valid_after(now + dt.timedelta(days=825))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                                         key_encipherment=True, data_encipherment=False,
                                         key_agreement=False, key_cert_sign=False, crl_sign=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                           critical=False)
            .sign(ca_key, hashes.SHA256()))
    return key, cert


def c_string_lines(text):
    return "\n".join('    "' + line.replace("\\", "\\\\").replace('"', '\\"') + '\\n"'
                     for line in text.strip().splitlines())


def secrets_h(kid, key, board_pw, ca_pem, device_id, when):
    key_bytes = ", ".join(f"0x{b:02x}" for b in key)
    return f"""/*
 * GENERATED by host/dt_setup_security.py on {when} for {device_id}.
 * Contains this board's HMAC key and MQTT password. Never commit or share it
 * (it is in .gitignore). To replace every key: py host\\dt_setup_security.py --force
 */
#ifndef SECRETS_H_
#define SECRETS_H_

#include <stdint.h>

#define DT_HMAC_KID         "{kid}"
static const uint8_t DT_HMAC_KEY[32] = {{ {key_bytes} }};

#define DT_MQTT_USER        "{BOARD_USER}"
#define DT_MQTT_PASSWORD    "{board_pw}"

#define DT_CA_FILE_NAME     "{CA_FILE_NAME}"
static const char DT_CA_PEM[] =
{c_string_lines(ca_pem)};

#endif /* SECRETS_H_ */
"""


def mosquitto_conf(stage, sec_dir, extra=""):
    p = sec_dir.resolve().as_posix()
    common = f"""persistence false
# 1 MB is far above the ~5 KB packets. Anything larger is not ours.
message_size_limit 1048576
allow_anonymous false
password_file {p}/passwd
acl_file {p}/acl
connection_messages true
log_type error
log_type warning
log_type notice
log_type information
log_timestamp_format %Y-%m-%dT%H:%M:%S
"""
    if stage == "2a":
        head = """# Stage 2a, generated by dt_setup_security.py: logins and topic rules, NO encryption.
# Run (PowerShell, from the host folder):  mosquitto -c secrets\\mosquitto_2a.conf -v
per_listener_settings false
listener 1883 0.0.0.0
"""
    else:
        head = f"""# Stage 2b, generated by dt_setup_security.py: TLS, logins and topic rules.
# Run (PowerShell, from the host folder):  mosquitto -c secrets\\mosquitto_2b.conf -v
per_listener_settings false
listener 8883 0.0.0.0
cafile {p}/ca.crt
certfile {p}/server.crt
keyfile {p}/server.key
tls_version tlsv1.2
ciphers {TLS12_CIPHERS}
require_certificate false
"""
    return head + common + extra


# ------------------------------------------------------------------ main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker-ip", action="append", default=[],
                    help="laptop IP to put in the broker certificate (repeatable, "
                         "default: DT_BROKER_IP from network_config.h)")
    ap.add_argument("--device-id", help="default: DT_DEVICE_ID from network_config.h")
    ap.add_argument("--out", default=str(HERE / "secrets"), help="folder for broker and receiver files")
    ap.add_argument("--secrets-h", default=str(FIRMWARE_DIR / "secrets.h"), help="where to write secrets.h")
    ap.add_argument("--force", action="store_true", help="replace existing keys (the board must be rebuilt)")
    args = ap.parse_args(argv)

    cfg_ip, cfg_dev = read_network_config(FIRMWARE_DIR / "network_config.h")
    device_id = args.device_id or cfg_dev or "CC3220SF_NODE_01"
    ips = list(dict.fromkeys(args.broker_ip + ([cfg_ip] if cfg_ip else []) + ["127.0.0.1"]))
    for ip in ips:
        ipaddress.ip_address(ip)  # raises on a typo

    sec = Path(args.out)
    keys_json = sec / "keys.json"
    if keys_json.exists() and not args.force:
        sys.exit(f"{keys_json} already exists. Keys are already set up.\n"
                 "Use --force to replace every key (then rebuild and reflash the board, "
                 "and restart Mosquitto).")
    sec.mkdir(parents=True, exist_ok=True)
    (sec / ".gitignore").write_text("# Generated secrets, never commit.\n*\n")

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    when = now.isoformat()
    kid = f"k{now:%Y%m%d}-{secrets.token_hex(2)}"
    hmac_key = secrets.token_bytes(32)
    passwords = {BOARD_USER: secrets.token_urlsafe(18), RECEIVER_USER: secrets.token_urlsafe(18)}

    ca_key, ca_cert = make_ca(now)
    srv_key, srv_cert = make_server(ca_key, ca_cert, ips, now)
    ca_pem = ca_cert.public_bytes(serialization.Encoding.PEM).decode()

    write_private(sec / "ca.key", key_pem(ca_key))
    (sec / "ca.crt").write_text(ca_pem)
    write_private(sec / "server.key", key_pem(srv_key))
    (sec / "server.crt").write_bytes(srv_cert.public_bytes(serialization.Encoding.PEM))
    write_private(sec / "passwd", "".join(f"{u}:{mosquitto_hash(p)}\n" for u, p in passwords.items()))
    (sec / "acl").write_text(f"""# Generated by dt_setup_security.py. Anything not listed is denied.

# The board may only publish its own topics (batches, status, will).
user {BOARD_USER}
topic write bridge/{device_id}/#

# The receiver may read every bridge topic and publish nothing.
user {RECEIVER_USER}
topic read bridge/#
""")
    (sec / "mosquitto_2a.conf").write_text(mosquitto_conf("2a", sec))
    (sec / "mosquitto_2b.conf").write_text(mosquitto_conf("2b", sec))
    write_private(keys_json, json.dumps({
        "generated_utc": when,
        "device_id": device_id,
        "broker_cert_ips": ips,
        "active_kid": kid,
        "hmac_keys": {kid: {"device_id": device_id, "key_hex": hmac_key.hex()}},
        "mqtt_users": {BOARD_USER: {"role": "board", "password": passwords[BOARD_USER]},
                       RECEIVER_USER: {"role": "receiver", "password": passwords[RECEIVER_USER]}},
        "ca_cert": "ca.crt",
    }, indent=2) + "\n")
    write_private(Path(args.secrets_h), secrets_h(kid, hmac_key, passwords[BOARD_USER], ca_pem, device_id, when))

    fp = srv_cert.fingerprint(hashes.SHA256()).hex(":")
    print(f"""Security files written for {device_id}
  board     {Path(args.secrets_h).resolve()}
  broker    {sec.resolve()}  (mosquitto_2a.conf, mosquitto_2b.conf)
  receiver  {keys_json.resolve()}
  key id    {kid}
  broker certificate valid for: {', '.join(ips)}, localhost
  broker certificate SHA-256: {fp}

Next: rebuild and reflash the board (secrets.h changed), then start Mosquitto with
  mosquitto -c secrets\\mosquitto_2b.conf -v      (or mosquitto_2a.conf for stage 2a)
Keep the secrets folder and secrets.h off GitHub, OneDrive sharing and chat.""")


if __name__ == "__main__":
    main()
