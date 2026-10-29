#!/usr/bin/env python3
"""
Security self-test for the stage 2 broker. Each check plays one attacker
move against the running Mosquitto and reports whether it was stopped.

  py dt_security_check.py                 stage 2b broker (TLS, port 8883)
  py dt_security_check.py --plain         stage 2a broker (port 1883)
  py dt_security_check.py --inject        also publish a forged, a tampered and a
                                          replayed batch on the real batch topic, so a
                                          running dt_receiver.py shows the rejections

Checks:
  - anonymous login refused, wrong password refused
  - (2b) a TLS client that does not trust the project CA cannot connect
  - (2b) plain MQTT to the TLS port fails, and nothing listens on plain 1883
  - ACL: the receiver login cannot publish, the board login cannot read
It needs keys.json from dt_setup_security.py, and does not need the board.
"""

import argparse
import json
import os
import socket
import ssl
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import dt_receiver as R  # noqa: E402

BOARD_USER = "dt_node01"


class Probe:
    """A short-lived MQTT client that records what the broker did."""

    def __init__(self, broker, port, user=None, password=None, ctx=None, cid="dt_check"):
        self.connected = threading.Event()
        self.answered = threading.Event()
        self.failure = None
        self.messages = []
        self.c = R.make_client(f"{cid}_{os.getpid()}")
        if user is not None:
            self.c.username_pw_set(user, password)
        if ctx is not None:
            self.c.tls_set_context(ctx)
        self.c.on_connect = self._on_connect
        self.c.on_message = lambda c, u, m: self.messages.append((m.topic, m.payload))
        self.broker, self.port = broker, port

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if getattr(reason_code, "is_failure", reason_code != 0):
            self.failure = str(reason_code)
        else:
            self.connected.set()
        self.answered.set()

    def start(self, timeout=4.0):
        """True if the broker accepted the login. Exceptions mean the transport failed."""
        self.c.connect(self.broker, self.port, keepalive=10)
        self.c.loop_start()
        self.answered.wait(timeout)
        return self.connected.is_set()

    def stop(self):
        try:
            self.c.loop_stop()
            self.c.disconnect()
        except Exception:  # noqa: BLE001
            pass


def run_checks(broker, port, plain, secrets_path, inject=False, out=print):
    _, info = R.load_keys(secrets_path)
    users = info["mqtt_users"]
    dev = info["device_id"]
    ca = os.path.join(os.path.dirname(os.path.abspath(secrets_path)), info.get("ca_cert", "ca.crt"))
    ctx = None if plain else R.tls_context(ca)
    results = []

    def report(name, stopped, detail):
        results.append((name, stopped))
        out(f"{'STOPPED' if stopped else 'NOT STOPPED'}  {name}: {detail}")

    def login(user, password, context=ctx, cid="dt_check"):
        p = Probe(broker, port, user, password, context, cid)
        try:
            ok = p.start()
            return ok, p.failure or ("accepted" if ok else "no answer")
        except (ssl.SSLError, OSError) as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            p.stop()

    # The genuine receiver login must work, or nothing else means anything.
    ok, why = login(R.RECEIVER_USER, users[R.RECEIVER_USER]["password"])
    out(f"{'OK     ' if ok else 'PROBLEM'}  genuine receiver login: {why}")
    if not ok:
        out("The broker does not accept the real login, so the checks below would prove nothing.")
        return False

    ok, why = login(None, None)
    report("anonymous login", not ok, why)
    ok, why = login(R.RECEIVER_USER, "wrong-password")
    report("receiver login with a wrong password", not ok, why)
    ok, why = login(BOARD_USER, users[R.RECEIVER_USER]["password"])
    report("board user with another user's password", not ok, why)

    if not plain:
        ok, why = login(R.RECEIVER_USER, users[R.RECEIVER_USER]["password"],
                        context=ssl.create_default_context())
        report("TLS client that only trusts public CAs (man-in-the-middle view)", not ok, why)
        ok, why = login(R.RECEIVER_USER, users[R.RECEIVER_USER]["password"], context=None)
        report("plain MQTT sent to the TLS port", not ok, why)
        try:
            with socket.create_connection((broker, 1883), timeout=2):
                report("plain port 1883 closed", False, "something accepts connections on 1883")
        except OSError as exc:
            report("plain port 1883 closed", True, f"{type(exc).__name__}: {exc}")

    # ACL checks use a listener logged in as the receiver.
    listener = Probe(broker, port, R.RECEIVER_USER, users[R.RECEIVER_USER]["password"], ctx, "dt_check_listen")
    listener.start()
    listener.c.subscribe(f"bridge/{dev}/#", qos=1)
    time.sleep(0.5)

    pub = Probe(broker, port, R.RECEIVER_USER, users[R.RECEIVER_USER]["password"], ctx, "dt_check_pub")
    pub.start()
    pub.c.publish(f"bridge/{dev}/selftest", b"receiver tries to publish", qos=1).wait_for_publish(3)
    time.sleep(1.0)
    got = [m for m in listener.messages if m[0].endswith("/selftest")]
    report("receiver login publishing into the device's topics", not got,
           "broker dropped it" if not got else "message was delivered")
    pub.stop()

    board = Probe(broker, port, BOARD_USER, users[BOARD_USER]["password"], ctx, "dt_check_board")
    if board.start():
        board.c.subscribe("bridge/#", qos=1)
        time.sleep(0.5)
        board.c.publish(f"bridge/{dev}/selftest", b"board selftest", qos=1).wait_for_publish(3)
        time.sleep(1.0)
        delivered_to_listener = any(m[0].endswith("/selftest") for m in listener.messages)
        report("board login reading bridge topics", not board.messages,
               "nothing delivered" if not board.messages else f"{len(board.messages)} messages read")
        out(f"{'OK     ' if delivered_to_listener else 'PROBLEM'}  board login can publish to its "
            f"own topics: {'delivered' if delivered_to_listener else 'NOT delivered, check the acl'}")

        if inject:
            # Attacker holding the board's MQTT password but not the HMAC key.
            # Attacker holding the board's MQTT password but not the HMAC key.
            time.sleep(2.5)                       # collect a few real batches first
            real = [m[1] for m in listener.messages if m[0].endswith("/batch")]
            if len(real) >= 2:
                last = R.split_signed(real[-1])
                body = last[0].replace(b'"l1":[', b'"l1":[1', 1)       # load cell 1 value changed
                attacks = [("tampered (value changed, old signature kept)",
                            body + R.MAC_HEAD + last[1] + b'"}'),
                           ("forged (value changed, signed with a guessed key)", R.sign(body, os.urandom(32))),
                           ("replayed (an older genuine batch sent again)", real[0])]
                for what, payload in attacks:
                    board.c.publish(f"bridge/{dev}/batch", payload, qos=1).wait_for_publish(3)
                    out(f"INJECTED {what}")
                out("A running dt_receiver.py should show bad_mac, bad_mac and replay for these.")
            else:
                out("fewer than 2 real batches seen (is the board publishing?), injection skipped")
        board.stop()
    else:
        out("PROBLEM  the board login was refused, check passwd")
        results.append(("board login works", False))
    listener.stop()

    stopped = sum(1 for _, s in results if s)
    out(f"\n{stopped} of {len(results)} attacker moves stopped")
    return stopped == len(results)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--broker", default="127.0.0.1")
    ap.add_argument("--port", type=int, help="default 8883, or 1883 with --plain")
    ap.add_argument("--plain", action="store_true", help="stage 2a broker (no TLS)")
    ap.add_argument("--secrets", default=R.DEFAULT_SECRETS)
    ap.add_argument("--inject", action="store_true",
                    help="also publish forged, tampered and replayed batches on the real topic")
    args = ap.parse_args(argv)
    if R.mqtt is None:
        sys.exit("paho-mqtt is missing. Install it with:  py -m pip install paho-mqtt")
    ok = run_checks(args.broker, args.port or (1883 if args.plain else 8883), args.plain,
                    args.secrets, args.inject)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
