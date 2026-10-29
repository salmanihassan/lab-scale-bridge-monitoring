#!/bin/sh
# Host-side simulation of the HX711 and DS18B20 pin protocols (needs gcc, any OS).
# The sensor drivers are compiled unchanged against mock GPIO/Hwi/timing layers
# with simulated 80 MHz time and device models. Not a substitute for hardware.
set -e
cd "$(dirname "$0")"
gcc -std=gnu99 -Wall -Wno-unused-function -Imock -I../src -o test_hx711 test_hx711.c sim.c
gcc -std=gnu99 -Wall -Wno-unused-function -Imock -I../src -o test_ds18b20 test_ds18b20.c sim.c -lpthread -lm
./test_hx711
./test_ds18b20
