#!/bin/bash
#
# generate_certs.sh
# Generates a self-signed CA and a server certificate for Mosquitto TLS.
# The CA cert is also copied to userFiles/ for flashing onto the CC3220SF.
#
# Usage: cd broker/certs && ./generate_certs.sh [BROKER_IP]
#

set -euo pipefail

BROKER_IP="${1:-10.198.144.56}"
DAYS_CA=3650
DAYS_SERVER=825
KEY_BITS=2048
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_FILES_DIR="$SCRIPT_DIR/../../userFiles"

echo "=== MQTT TLS Certificate Generator ==="
echo "Broker IP : $BROKER_IP"
echo "Output dir: $SCRIPT_DIR"
echo ""

# --- Step 1: Generate CA private key and self-signed certificate ---
echo "[1/4] Generating CA private key..."
openssl genrsa -out "$SCRIPT_DIR/ca.key" "$KEY_BITS" 2>/dev/null

echo "[2/4] Generating CA self-signed certificate (${DAYS_CA} days)..."
openssl req -x509 -new -nodes \
    -key "$SCRIPT_DIR/ca.key" \
    -sha256 \
    -days "$DAYS_CA" \
    -out "$SCRIPT_DIR/ca-cert.pem" \
    -subj "/C=US/ST=Texas/L=Dallas/O=IoT Lab/OU=Embedded/CN=MQTT-CA"

# --- Step 2: Generate server private key ---
echo "[3/4] Generating server private key and certificate..."
openssl genrsa -out "$SCRIPT_DIR/server.key" "$KEY_BITS" 2>/dev/null

# --- Step 3: Generate server CSR and sign with CA ---
# Create a temporary SAN config for the server cert
SAN_CONF=$(mktemp)
cat > "$SAN_CONF" <<EOF
[req]
default_bits       = $KEY_BITS
prompt             = no
distinguished_name = dn
req_extensions     = v3_req

[dn]
C  = US
ST = Texas
L  = Dallas
O  = IoT Lab
OU = Broker
CN = mosquitto-broker

[v3_req]
subjectAltName = @alt_names

[alt_names]
IP.1  = $BROKER_IP
IP.2  = 127.0.0.1
DNS.1 = localhost
EOF

openssl req -new -nodes \
    -key "$SCRIPT_DIR/server.key" \
    -out "$SCRIPT_DIR/server.csr" \
    -config "$SAN_CONF"

# Sign the server certificate with the CA, preserving SANs
SAN_EXT_CONF=$(mktemp)
cat > "$SAN_EXT_CONF" <<EOF
authorityKeyIdentifier = keyid,issuer
basicConstraints       = CA:FALSE
keyUsage               = digitalSignature, keyEncipherment
extendedKeyUsage       = serverAuth
subjectAltName         = @alt_names

[alt_names]
IP.1  = $BROKER_IP
IP.2  = 127.0.0.1
DNS.1 = localhost
EOF

openssl x509 -req \
    -in "$SCRIPT_DIR/server.csr" \
    -CA "$SCRIPT_DIR/ca-cert.pem" \
    -CAkey "$SCRIPT_DIR/ca.key" \
    -CAcreateserial \
    -out "$SCRIPT_DIR/server.crt" \
    -days "$DAYS_SERVER" \
    -sha256 \
    -extfile "$SAN_EXT_CONF"

rm -f "$SAN_CONF" "$SAN_EXT_CONF" "$SCRIPT_DIR/server.csr" "$SCRIPT_DIR/ca-cert.srl"

# --- Step 4: Copy CA cert to userFiles for MCU flashing ---
echo "[4/4] Copying ca-cert.pem to userFiles/ for MCU flashing..."
cp "$SCRIPT_DIR/ca-cert.pem" "$USER_FILES_DIR/ca-cert.pem"

echo ""
echo "=== Certificate Generation Complete ==="
echo ""
echo "Files generated:"
echo "  CA key         : $SCRIPT_DIR/ca.key"
echo "  CA certificate : $SCRIPT_DIR/ca-cert.pem"
echo "  Server key     : $SCRIPT_DIR/server.key"
echo "  Server cert    : $SCRIPT_DIR/server.crt"
echo "  MCU CA cert    : $USER_FILES_DIR/ca-cert.pem"
echo ""
echo "Next steps:"
echo "  1. Restart Mosquitto:  cd broker && ./broker.sh"
echo "  2. Re-flash the MCU via UniFlash (ca-cert.pem is now in userFiles/)"
echo "  3. Rebuild and flash the firmware with MQTT_SECURE_CLIENT enabled"
