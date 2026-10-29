#!/bin/sh
# Host tests for the Wi-Fi node (gcc, python3 with paho-mqtt and cryptography;
# mosquitto for --e2e).
#   sh run_tests.sh          HMAC vectors, payload encoder + signer, receiver unit tests
#   sh run_tests.sh --e2e    also full round trips through a local mosquitto:
#                            stage 2a (login + ACL) and stage 2b (TLS + login + ACL)
set -e
cd "$(dirname "$0")"
T=$(mktemp -d)
gcc -std=c99 -Wall -Wextra -I../src -o "$T/test_hmac" test_hmac.c ../src/dt_hmac.c
"$T/test_hmac"
gcc -std=c99 -Wall -Wextra -I../src -o "$T/test_payload" test_payload.c ../src/payload.c ../src/dt_hmac.c
"$T/test_payload" "$T/worst.json" "$T/typical.json"
python3 test_receiver.py "$T/typical.json" "$T/worst.json" "$@"
rm -rf "$T"
