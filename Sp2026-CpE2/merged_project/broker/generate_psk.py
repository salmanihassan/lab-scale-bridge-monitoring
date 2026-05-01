#!/usr/bin/env python3
"""
generate_psk.py -- Convert a string into copy-pasteable hex key definitions
for both the C firmware (hmac_auth.h) and the Python host scripts.

Usage:
  python3 generate_psk.py "MySecureDigitalTwinKey2026!@#$%^"
  python3 generate_psk.py            # prompts interactively
"""

import sys


def generate(key_str):
    raw = key_str.encode("utf-8")
    print(f"\nInput string : {key_str}")
    print(f"Length       : {len(raw)} bytes\n")

    # --- C format ---
    lines = []
    for i in range(0, len(raw), 8):
        chunk = raw[i:i+8]
        hex_part = ", ".join(f"0x{b:02x}" for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"    {hex_part + ',':<48s} /* {ascii_part} */")

    # trim trailing comma on last line
    lines[-1] = lines[-1].replace(", */", "  */", 1)
    last_comma = lines[-1].rfind(",")
    lines[-1] = lines[-1][:last_comma] + " " + lines[-1][last_comma+1:]

    print("=== C (hmac_auth.h) ===\n")
    print(f"static const uint8_t HMAC_KEY[{len(raw)}] = {{")
    print("\n".join(lines))
    print("};\n")

    # --- Python format ---
    py_lines = []
    for i in range(0, len(raw), 8):
        chunk = raw[i:i+8]
        hex_part = ", ".join(f"0x{b:02x}" for b in chunk)
        py_lines.append(f"    {hex_part},")

    # trim trailing comma on last line
    py_lines[-1] = py_lines[-1].rstrip(",")

    print("=== Python (host_receiver.py / test_integrity.py) ===\n")
    print(f"HMAC_KEY = bytes([")
    print("\n".join(py_lines))
    print("])\n")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        generate(sys.argv[1])
    else:
        generate(input("Enter key string: "))
