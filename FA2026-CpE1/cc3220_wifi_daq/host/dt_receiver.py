#!/usr/bin/env python3
"""
Receiver for the bridge digital twin Wi-Fi node (stage 2, secured link).

Logs in to the broker as dt_receiver (over TLS by default), subscribes to
bridge/<device>/batch and bridge/<device>/status, and checks every packet
before any of its data is used:

  1. format       the payload must be dt-batch/1.1 and end in ,"mac":"<64 hex>"}
  2. signature    HMAC-SHA256 with the key named by "kid", over the exact bytes
                  received before ,"mac":"  (bad_mac / unknown_kid / wrong_key)
  3. topic        the signed device_id must match the topic       (wrong_topic)
  4. replay       per device, boot_id plus increasing seq:
                  the latest packet again -> duplicate (MQTT may resend it,
                  never written twice), any older seq -> replay,
                  a boot_id that was replaced earlier -> stale_boot
                  (boot_ids are remembered across runs in the state file)
  5. freshness    host arrival time minus board time must stay within
                  --max-age-ms of the best seen for that boot     (stale)

Only accepted packets reach <name>_samples.csv. Every packet that can be
parsed gets a row in <name>_packets.csv with its verdict. Rejections are
also written to <name>_rejected.log with the reason.

  <name>_samples.csv   one row per 10 ms sample. The first 12 columns are the
                       same as the serial stream firmware's CSV. Boot_ID and Seq
                       are appended.
  <name>_packets.csv   one row per packet: arrival, sequence, gaps, verdict,
                       board diagnostics.
  <name>_rejected.log  rejected packets with the reason.

Usage (Windows PowerShell, from the host folder, after dt_setup_security.py):
  py dt_receiver.py --name cal_wifi_r1              stage 2b, TLS on port 8883
  py dt_receiver.py --plain --name test_2a          stage 2a, port 1883, no TLS

Stop with Ctrl+C. A summary is printed.
"""

import argparse
import csv
import hashlib
import hmac
import json
import os
import re
import signal
import ssl
import sys
import time
from collections import Counter
from datetime import datetime, timezone

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover
    mqtt = None

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SECRETS = os.path.join(HERE, "secrets", "keys.json")
RECEIVER_USER = "dt_receiver"

SCHEMA = "dt-batch/1.1"
MAC_HEAD = b',"mac":"'
MAC_RE = re.compile(rb"[0-9a-f]{64}")
SAMPLE_HEADER = ["Time_ms", "X_g", "Y_g", "Z_g", "Temp1_C", "Temp2_C", "Temp3_C",
                 "LoadCell1_Raw", "LoadCell2_Raw", "Motor", "LoadCell1_New", "LoadCell2_New",
                 "Boot_ID", "Seq"]
PACKET_HEADER = ["host_rx_iso", "host_rx_ms", "device_id", "boot_id", "seq", "t0_ms", "n",
                 "bytes", "missing_before", "duplicate", "new_boot", "host_minus_board_ms",
                 "accel_fail", "late_slots", "dropped", "pub_fail", "not_connected", "uptime_ms",
                 "kid", "verdict"]
ARRAY_KEYS = ["dt_ms", "ax", "ay", "az", "l1", "l2"]
ACCEPTED = "accepted"
DUPLICATE = "duplicate"


class BatchError(ValueError):
    """A packet that does not match the dt-batch/1.1 format."""


def validate(d):
    """Return the decoded batch or raise BatchError with a readable reason."""
    if not isinstance(d, dict):
        raise BatchError("not a JSON object")
    if d.get("schema") != SCHEMA:
        raise BatchError(f"schema is {d.get('schema')!r}, expected {SCHEMA!r}")
    for key in ("kid", "device_id", "boot_id", "seq", "t0_ms", "n", "accel_lsb_g",
                "l1_new", "l2_new", "temp_c", "diag", "mac"):
        if key not in d:
            raise BatchError(f"missing field {key!r}")
    n = d["n"]
    if not isinstance(n, int) or not 1 <= n <= 1000:
        raise BatchError(f"bad n {n!r}")
    for key in ARRAY_KEYS:
        if not isinstance(d.get(key), list) or len(d[key]) != n:
            raise BatchError(f"{key} has {len(d.get(key) or [])} values, n is {n}")
    for key in ("l1_new", "l2_new"):
        if not isinstance(d[key], str) or len(d[key]) != n or set(d[key]) - {"0", "1"}:
            raise BatchError(f"{key} must be {n} characters of 0/1")
    if not isinstance(d["temp_c"], list) or len(d["temp_c"]) != 3:
        raise BatchError("temp_c must have 3 values")
    if not isinstance(d["seq"], int) or d["seq"] < 0:
        raise BatchError(f"bad seq {d['seq']!r}")
    if not isinstance(d["t0_ms"], int) or not isinstance(d["boot_id"], str):
        raise BatchError("bad t0_ms or boot_id")
    dts = d["dt_ms"]
    if any(not isinstance(v, int) for v in dts) or dts != sorted(dts):
        raise BatchError("dt_ms must be increasing integers")
    return d


def split_signed(raw):
    """(signed_bytes, mac_hex_bytes) for a payload ending in ,"mac":"<64 hex>"}, else None."""
    i = raw.rfind(MAC_HEAD)
    if i <= 0 or len(raw) != i + len(MAC_HEAD) + 64 + 2 or raw[-2:] != b'"}':
        return None
    mac = raw[i + len(MAC_HEAD):i + len(MAC_HEAD) + 64]
    if not MAC_RE.fullmatch(mac):
        return None
    return raw[:i], mac


def sign(signed_bytes, key):
    """Signed payload as the board builds it (used by the tests and the attack checks)."""
    mac = hmac.new(key, signed_bytes, hashlib.sha256).hexdigest().encode()
    return signed_bytes + MAC_HEAD + mac + b'"}'


def sample_rows(d):
    """Rows for <name>_samples.csv, same first 12 columns as the serial CSV."""
    lsb = float(d["accel_lsb_g"])
    t = ["" if v is None else f"{v:.2f}" for v in d["temp_c"]]

    def g(v):
        return "" if v is None else f"{v * lsb:.4f}"

    def raw(v):
        return "" if v is None else str(v)

    for i in range(d["n"]):
        yield [d["t0_ms"] + d["dt_ms"][i], g(d["ax"][i]), g(d["ay"][i]), g(d["az"][i]),
               t[0], t[1], t[2], raw(d["l1"][i]), raw(d["l2"][i]), 0,
               d["l1_new"][i], d["l2_new"][i], d["boot_id"], d["seq"]]


def load_keys(path):
    """{kid: (device_id, key_bytes)} and the full keys.json content."""
    with open(path) as f:
        info = json.load(f)
    keys = {kid: (v["device_id"], bytes.fromhex(v["key_hex"])) for kid, v in info["hmac_keys"].items()}
    return keys, info


class Receiver:
    def __init__(self, out_dir, name, keys, quiet=False, state_path=None, max_age_ms=10000):
        os.makedirs(out_dir, exist_ok=True)
        base = os.path.join(out_dir, name)
        self.samples_f = open(base + "_samples.csv", "w", newline="")
        self.packets_f = open(base + "_packets.csv", "w", newline="")
        self.rejected_f = open(base + "_rejected.log", "w")
        self.samples = csv.writer(self.samples_f)
        self.packets = csv.writer(self.packets_f)
        self.samples.writerow(SAMPLE_HEADER)
        self.packets.writerow(PACKET_HEADER)
        self.paths = [base + s for s in ("_samples.csv", "_packets.csv", "_rejected.log")]
        self.samples_f.flush()     # headers on disk even if no packet ever arrives
        self.packets_f.flush()
        self.keys = keys
        self.quiet = quiet
        self.max_age_ms = max_age_ms
        self.state_path = state_path or os.path.join(out_dir, "receiver_state.json")
        self.state = self._load_state()   # device -> {"boot", "last_seq", "old_boots"}
        self.best_offset = {}             # (device, boot_id) -> smallest host_minus_board_ms
        self.verdicts = Counter()
        self.n_packets = self.n_samples = self.n_missing = self.n_boots = 0
        self.arrivals = []

    # -------------------------------------------------------------- state

    def _load_state(self):
        try:
            with open(self.state_path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self.state_path)

    def close(self):
        for f in (self.samples_f, self.packets_f, self.rejected_f):
            f.close()

    @property
    def n_rejected(self):
        return sum(v for k, v in self.verdicts.items() if k not in (ACCEPTED, DUPLICATE))

    # -------------------------------------------------------------- packets

    def on_status(self, topic, text):
        print(f"[status] {topic} = {text}  (status is not signed, the broker ACL guards it)")

    def _reject(self, verdict, reason, raw, d=None, rx_ms=None):
        self.verdicts[verdict] += 1
        self.rejected_f.write(f"{datetime.now(timezone.utc).isoformat()} {verdict}: {reason}: "
                              f"{raw[:160]!r}\n")
        self.rejected_f.flush()
        if d is not None:
            self._packet_row(d, raw, rx_ms, 0, False, False, verdict)
        print(f"[REJECTED {verdict}] {reason}")
        return verdict, None

    def _packet_row(self, d, raw, rx_ms, missing, duplicate, new_boot, verdict):
        diag = d.get("diag") if isinstance(d.get("diag"), dict) else {}
        self.packets.writerow([
            datetime.fromtimestamp(rx_ms / 1000, timezone.utc).isoformat(timespec="milliseconds"),
            rx_ms, d.get("device_id"), d.get("boot_id"), d.get("seq"), d.get("t0_ms"), d.get("n"),
            len(raw), missing, int(duplicate), int(new_boot),
            rx_ms - d["t0_ms"] if isinstance(d.get("t0_ms"), int) else "",
            diag.get("accel_fail"), diag.get("late_slots"), diag.get("dropped"),
            diag.get("pub_fail"), diag.get("not_connected"), diag.get("uptime_ms"),
            d.get("kid"), verdict])
        self.packets_f.flush()

    def on_batch(self, raw, topic=None, rx_ms=None):
        """Check one packet. Returns (verdict, batch or None). The batch is only given when accepted."""
        rx_ms = int(time.time() * 1000) if rx_ms is None else rx_ms
        if isinstance(raw, str):
            raw = raw.encode()
        self.n_packets += 1
        self.arrivals.append(rx_ms)

        parts = split_signed(raw)
        try:
            d = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            return self._reject("malformed", f"not JSON ({exc})", raw)
        if parts is None:
            return self._reject("unsigned", "no valid mac field at the end of the payload", raw,
                                d if isinstance(d, dict) else None, rx_ms)
        try:
            validate(d)
        except BatchError as exc:
            return self._reject("malformed", str(exc), raw, d if isinstance(d, dict) else None, rx_ms)

        # 2. signature: nothing in the packet is trusted before this passes.
        kid, dev = d["kid"], d["device_id"]
        if kid not in self.keys:
            return self._reject("unknown_kid", f"no key with id {kid!r}", raw, d, rx_ms)
        key_dev, key = self.keys[kid]
        if key_dev != dev:
            return self._reject("wrong_key", f"key {kid!r} belongs to {key_dev}, packet says {dev}",
                                raw, d, rx_ms)
        signed, mac = parts
        if not hmac.compare_digest(hmac.new(key, signed, hashlib.sha256).hexdigest().encode(), mac):
            return self._reject("bad_mac", "signature does not match the contents", raw, d, rx_ms)

        # 3. topic
        if topic is not None and topic != f"bridge/{dev}/batch":
            return self._reject("wrong_topic", f"signed for {dev}, arrived on {topic}", raw, d, rx_ms)

        # 4. replay
        boot, seq = d["boot_id"], d["seq"]
        st = self.state.setdefault(dev, {"boot": None, "last_seq": -1, "old_boots": []})
        new_boot = False
        missing = 0
        if boot == st["boot"]:
            if seq == st["last_seq"]:
                self.verdicts[DUPLICATE] += 1
                self._packet_row(d, raw, rx_ms, 0, True, False, DUPLICATE)
                if not self.quiet:
                    print(f"seq {seq:>6}  DUPLICATE (same packet again, not written twice)")
                return DUPLICATE, None
            if seq < st["last_seq"]:
                return self._reject("replay", f"seq {seq} is older than {st['last_seq']} for boot {boot}",
                                    raw, d, rx_ms)
            missing = seq - st["last_seq"] - 1 if st["last_seq"] >= 0 else 0
        elif boot in st["old_boots"]:
            return self._reject("stale_boot", f"boot {boot} was already replaced by a newer boot",
                                raw, d, rx_ms)
        else:
            new_boot = st["boot"] is not None

        # 5. freshness, against the best (smallest) offset seen for this boot
        offset = rx_ms - d["t0_ms"]
        best = self.best_offset.get((dev, boot))
        if best is not None and offset - best > self.max_age_ms:
            return self._reject("stale", f"arrived {offset - best} ms later than the link allows "
                                f"(limit {self.max_age_ms} ms)", raw, d, rx_ms)
        self.best_offset[(dev, boot)] = offset if best is None else min(best, offset)

        # accepted
        if boot != st["boot"]:
            if st["boot"] is not None:
                st["old_boots"] = (st["old_boots"] + [st["boot"]])[-1000:]
                self.n_boots += 1
            st["boot"] = boot
        st["last_seq"] = seq
        self._save_state()
        self.verdicts[ACCEPTED] += 1
        self.n_missing += missing
        for row in sample_rows(d):
            self.samples.writerow(row)
        self.n_samples += d["n"]
        self.samples_f.flush()
        self._packet_row(d, raw, rx_ms, missing, False, new_boot, ACCEPTED)

        if not self.quiet:
            az = [v for v in d["az"] if v is not None]
            l1 = [v for v in d["l1"] if v is not None]
            l2 = [v for v in d["l2"] if v is not None]
            note = f" MISSING {missing}" if missing else ""
            note += " NEW BOOT" if new_boot else ""
            print(f"seq {seq:>6}  {len(raw):>5} B  ok  "
                  f"z={sum(az) / max(1, len(az)) * d['accel_lsb_g']:+.3f} g  "
                  f"L1={l1[-1] if l1 else '-':>9}  L2={l2[-1] if l2 else '-':>9}  "
                  f"T={d['temp_c']}  late={d['diag'].get('late_slots')}{note}")
        return ACCEPTED, d

    def summary(self):
        lines = ["", "---- summary ----",
                 f"packets received : {self.n_packets}",
                 f"accepted         : {self.verdicts[ACCEPTED]}",
                 f"samples written  : {self.n_samples}",
                 f"missing packets  : {self.n_missing}",
                 f"duplicates       : {self.verdicts[DUPLICATE]}",
                 f"reboots seen     : {self.n_boots}",
                 f"rejected         : {self.n_rejected}"]
        for k in sorted(self.verdicts):
            if k not in (ACCEPTED, DUPLICATE):
                lines.append(f"  {k:<15}: {self.verdicts[k]}")
        if len(self.arrivals) > 2:
            gaps = [b - a for a, b in zip(self.arrivals, self.arrivals[1:])]
            mean = sum(gaps) / len(gaps)
            sd = (sum((g - mean) ** 2 for g in gaps) / len(gaps)) ** 0.5
            lines.append(f"inter-arrival    : mean {mean:.0f} ms, sd {sd:.0f} ms, "
                         f"min {min(gaps)} ms, max {max(gaps)} ms")
        lines.append("files: " + ", ".join(self.paths))
        return "\n".join(lines)


def make_client(client_id):
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    except AttributeError:  # paho-mqtt 1.x
        return mqtt.Client(client_id=client_id)


def tls_context(ca_file):
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_file)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def main(argv=None):
    if mqtt is None:
        sys.exit("paho-mqtt is missing. Install it with:  py -m pip install paho-mqtt")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default="127.0.0.1", help="broker address (default 127.0.0.1)")
    ap.add_argument("--port", type=int, help="default 8883, or 1883 with --plain")
    ap.add_argument("--plain", action="store_true", help="stage 2a: no TLS (login and signatures still checked)")
    ap.add_argument("--secrets", default=DEFAULT_SECRETS, help="keys.json from dt_setup_security.py")
    ap.add_argument("--device", default="CC3220SF_NODE_01", help="device id, or + for all")
    ap.add_argument("--out-dir", default="runs")
    ap.add_argument("--name", default=datetime.now().strftime("wifi_%Y%m%d_%H%M%S"))
    ap.add_argument("--state", help="replay state file (default <out-dir>/receiver_state.json)")
    ap.add_argument("--max-age-ms", type=int, default=10000,
                    help="reject a packet this much later than the link's best delay (default 10000)")
    ap.add_argument("--quiet", action="store_true", help="no line per packet")
    ap.add_argument("--max-packets", type=int, default=0, help="stop after N packets (testing)")
    args = ap.parse_args(argv)
    port = args.port or (1883 if args.plain else 8883)

    try:
        keys, info = load_keys(args.secrets)
    except (OSError, ValueError, KeyError) as exc:
        sys.exit(f"cannot read {args.secrets} ({exc}). Run dt_setup_security.py first.")
    password = info["mqtt_users"][RECEIVER_USER]["password"]

    rx = Receiver(args.out_dir, args.name, keys, args.quiet, args.state, args.max_age_ms)
    batch_topic = f"bridge/{args.device}/batch"
    status_topic = f"bridge/{args.device}/status"
    done = {"stop": False, "code": 0}

    def on_connect(client, userdata, flags, reason_code, properties=None):
        failed = getattr(reason_code, "is_failure", reason_code != 0)
        if failed:
            print(f"broker refused the login as {RECEIVER_USER}: {reason_code}. "
                  "Is Mosquitto using the passwd file from this keys.json?")
            done.update(stop=True, code=2)
            return
        sock = client.socket()
        link = f"{sock.version()} {sock.cipher()[0]}" if hasattr(sock, "cipher") else "NO TLS (stage 2a)"
        print(f"connected to {args.broker}:{port} as {RECEIVER_USER}, {link}, listening on {batch_topic}")
        client.subscribe([(batch_topic, 1), (status_topic, 1)])

    def on_subscribe(client, userdata, mid, granted, *rest):
        codes = [getattr(g, "value", g) for g in granted]
        if any(c >= 0x80 for c in codes):
            print(f"WARNING: the broker refused a subscription {codes}, check the acl file")

    def on_message(client, userdata, msg):
        if msg.topic.endswith("/status"):
            rx.on_status(msg.topic, msg.payload.decode(errors="replace"))
            return
        rx.on_batch(msg.payload, msg.topic)
        if args.max_packets and rx.n_packets >= args.max_packets:
            done["stop"] = True

    client = make_client(f"dt_receiver_{os.getpid()}")
    client.username_pw_set(RECEIVER_USER, password)
    if not args.plain:
        client.tls_set_context(tls_context(os.path.join(os.path.dirname(os.path.abspath(args.secrets)),
                                                        info.get("ca_cert", "ca.crt"))))
    client.on_connect = on_connect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    signal.signal(signal.SIGINT, lambda *a: done.update(stop=True))
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *a: done.update(stop=True))
    try:
        client.connect(args.broker, port, keepalive=30)
    except ssl.SSLError as exc:
        rx.close()
        sys.exit(f"TLS to {args.broker}:{port} failed ({exc}). Is the broker using secrets/server.crt?")
    except OSError as exc:
        rx.close()
        sys.exit(f"cannot reach the broker at {args.broker}:{port} ({exc}). Is Mosquitto running "
                 f"with secrets\\mosquitto_{'2a' if args.plain else '2b'}.conf?")
    client.loop_start()
    try:
        while not done["stop"]:
            time.sleep(0.2)
    finally:
        client.loop_stop()
        client.disconnect()
        print(rx.summary())
        rx.close()
    sys.exit(done["code"])


if __name__ == "__main__":
    main()
