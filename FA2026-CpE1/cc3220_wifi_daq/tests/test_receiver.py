#!/usr/bin/env python3
"""
Tests for host/dt_receiver.py, host/dt_setup_security.py and host/dt_security_check.py.

  python test_receiver.py typical.json worst.json            # unit tests only
  python test_receiver.py typical.json worst.json --e2e      # also stage 2a and 2b
                                                             # through a real mosquitto
typical.json and worst.json are signed by test_payload.c (C signer) with the
test key bytes 0x00..0x1f and kid "ktest".
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.path.join(HERE, "..", "host")
sys.path.insert(0, HOST)
import dt_receiver as R  # noqa: E402

TEST_KEY = bytes(range(32))
KEYS = {"ktest": ("CC3220SF_NODE_01", TEST_KEY), "kother": ("CC3220SF_NODE_02", b"\x01" * 32)}
TOPIC = "bridge/CC3220SF_NODE_01/batch"
fails = 0


def check(cond, what):
    global fails
    print(("PASS " if cond else "FAIL ") + what)
    fails += 0 if cond else 1


def resign(raw, key=TEST_KEY, **changes):
    """Change fields of a signed packet and sign it again, laid out as the board does."""
    d = json.loads(raw)
    d.pop("mac")
    d.update(changes)
    body = json.dumps(d, separators=(",", ":")).encode()[:-1]   # without the closing brace
    return R.sign(body, key)


def unit(typical, worst):
    tmp = tempfile.mkdtemp()
    t0 = json.loads(typical)["t0_ms"]

    rw = R.Receiver(tmp, "w", KEYS, quiet=True, state_path=os.path.join(tmp, "sw.json"))
    check(rw.on_batch(worst, TOPIC)[0] == "accepted", "worst-case packet signed in C verifies in Python")
    rw.close()

    state = os.path.join(tmp, "state.json")
    rx = R.Receiver(tmp, "u", KEYS, quiet=True, state_path=state)

    def v(raw, topic=TOPIC, rx_ms=None):
        return rx.on_batch(raw, topic, rx_ms if rx_ms is not None else t0 + 1100)[0]

    check(v(typical) == "accepted", "typical packet signed in C accepted (seq 41)")
    check(v(resign(typical, seq=44)) == "accepted", "seq 44 accepted after a gap")
    check(v(resign(typical, seq=44)) == "duplicate", "same packet again is a duplicate")
    check(v(resign(typical, seq=43)) == "replay", "older seq of the same boot is a replay")
    tampered = typical.replace(b'"l1":[319500', b'"l1":[319999', 1)
    check(tampered != typical and v(tampered) == "bad_mac", "one changed value breaks the signature")
    check(v(resign(typical, key=b"\x02" * 32, seq=50)) == "bad_mac", "signed with a guessed key")
    check(v(resign(typical, kid="knone", seq=51)) == "unknown_kid", "unknown key id")
    check(v(resign(typical, key=b"\x01" * 32, kid="kother", seq=52)) == "wrong_key",
          "another device's key cannot sign for this device")
    stage1 = json.loads(typical)
    stage1.pop("mac")
    check(v(json.dumps(stage1).encode()) == "unsigned", "unsigned (stage 1 style) packet rejected")
    check(v(resign(typical, seq=53), topic="bridge/CC3220SF_NODE_09/batch") == "wrong_topic",
          "signed packet moved to another device's topic")
    check(v(resign(typical, seq=54), rx_ms=t0 + 1100 + 15000) == "stale",
          "packet held back 15 s is stale")
    check(v(resign(typical, seq=55)) == "accepted", "next fresh packet accepted")
    short = json.loads(typical)
    short["ax"] = short["ax"][:50]
    short.pop("mac")
    check(v(R.sign(json.dumps(short, separators=(",", ":")).encode()[:-1], TEST_KEY)) == "malformed",
          "signed but malformed packet rejected")
    check(v(b"{not json") == "malformed", "garbage rejected")
    check(v(resign(typical, boot_id="deadbeef", seq=0, t0_ms=500), rx_ms=1600) == "accepted",
          "new boot accepted")
    check(v(resign(typical, seq=56)) == "stale_boot", "packet from the replaced boot is stale_boot")
    rx.close()
    check(rx.n_missing == 2 + 10, f"gaps counted (missing={rx.n_missing}: 42, 43 and 45..54)")
    check(rx.n_boots == 1, f"reboot counted (boots={rx.n_boots})")
    check(rx.verdicts["accepted"] == 4, f"4 accepted ({dict(rx.verdicts)})")

    # Replay state survives a receiver restart.
    rx2 = R.Receiver(tmp, "u2", KEYS, quiet=True, state_path=state)
    check(rx2.on_batch(typical, TOPIC, t0 + 1100)[0] == "stale_boot",
          "after a restart, the old boot is still refused")
    check(rx2.on_batch(resign(typical, boot_id="deadbeef", seq=1, t0_ms=1500), TOPIC, 2600)[0] == "accepted",
          "after a restart, the current boot continues")
    rx2.close()

    with open(os.path.join(tmp, "u_samples.csv")) as f:
        rows = list(csv.reader(f))
    check(rows[0][:12] == ["Time_ms", "X_g", "Y_g", "Z_g", "Temp1_C", "Temp2_C", "Temp3_C",
                           "LoadCell1_Raw", "LoadCell2_Raw", "Motor", "LoadCell1_New",
                           "LoadCell2_New"], "first 12 columns match the serial stream CSV")
    check(len(rows) == 1 + 4 * 100, f"only accepted packets reach the samples ({len(rows) - 1} rows)")
    r0 = rows[1]
    check(r0[0] == "123450" and r0[1] == "-0.5078" and r0[4] == "30.50" and r0[5] == "",
          f"typical row decoded {r0[:8]}")
    check(rows[18][1] == "" and rows[1 + 5][8] == "639400" and rows[1][8] == "",
          "nulls become empty fields (failed accel read, load 2 before first reading)")
    with open(os.path.join(tmp, "u_packets.csv")) as f:
        pk = list(csv.DictReader(f))
    verdicts = [p["verdict"] for p in pk]
    check(verdicts.count("bad_mac") == 2 and "replay" in verdicts and "stale" in verdicts
          and pk[1]["missing_before"] == "2", f"packet log records verdicts {verdicts}")
    with open(os.path.join(tmp, "u_rejected.log")) as f:
        check(len(f.readlines()) == rx.n_rejected, "every rejection is in the rejected log")
    shutil.rmtree(tmp)


# ---------------------------------------------------------------- end to end

def e2e_stage(stage, typical, sec, tmp):
    """Fake board (real board login and key) -> mosquitto -> dt_receiver.py, then the self-test."""
    plain = stage == "2a"
    test_port = 18830 if plain else 18883
    conf = open(os.path.join(sec, f"mosquitto_{stage}.conf")).read()
    conf = conf.replace("listener 1883 0.0.0.0" if plain else "listener 8883 0.0.0.0",
                        f"listener {test_port} 127.0.0.1")
    if os.geteuid() == 0:
        conf += "user root\n"            # container only: keep access to the 0600 files
    conf_path = os.path.join(tmp, f"m_{stage}.conf")
    with open(conf_path, "w") as f:
        f.write(conf)
    log_path = conf_path + ".log"
    log = open(log_path, "w")
    broker = subprocess.Popen(["mosquitto", "-c", conf_path], stdout=log, stderr=subprocess.STDOUT)
    time.sleep(0.8)

    with open(os.path.join(sec, "keys.json")) as f:
        info = json.load(f)
    kid = info["active_kid"]
    key = bytes.fromhex(info["hmac_keys"][kid]["key_hex"])
    out_dir = os.path.join(tmp, "runs_" + stage)
    cmd = [sys.executable, os.path.join(HOST, "dt_receiver.py"), "--port", str(test_port),
           "--secrets", os.path.join(sec, "keys.json"), "--out-dir", out_dir, "--name", "e2e",
           "--max-packets", "6"]
    if plain:
        cmd.append("--plain")
    recv = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(1.5)

    board = R.make_client("dtnode01")
    board.username_pw_set("dt_node01", info["mqtt_users"]["dt_node01"]["password"])
    if not plain:
        board.tls_set_context(R.tls_context(os.path.join(sec, "ca.crt")))
    board.will_set("bridge/CC3220SF_NODE_01/status", "offline", qos=1, retain=True)
    board.connect("127.0.0.1", test_port)
    board.loop_start()
    board.publish("bridge/CC3220SF_NODE_01/status", "online", qos=1, retain=True).wait_for_publish(3)
    now = int(time.time() * 1000)
    sent = {}
    for seq in (100, 101, 103, 104):  # 102 lost
        sent[seq] = resign(typical, key=key, kid=kid, seq=seq, t0_ms=now - 1000 + (seq - 100) * 150)
        board.publish(TOPIC, sent[seq], qos=1).wait_for_publish(3)
        time.sleep(0.15)
    board.publish(TOPIC, sent[104].replace(b'"seq":104', b'"seq":105', 1), qos=1).wait_for_publish(3)
    board.publish(TOPIC, sent[101], qos=1).wait_for_publish(3)
    try:
        out, _ = recv.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        recv.kill()
        out, _ = recv.communicate()
    board.loop_stop()
    board.disconnect()

    lines = [ln for ln in out.splitlines() if ln.strip()]
    print("   receiver said:\n     " + "\n     ".join(lines))
    first = lines[0] if lines else ""
    link_ok = ("NO TLS" in first) if plain else ("TLSv1.2" in first or "TLSv1.3" in first)
    check(link_ok, f"{stage}: receiver link is {'plain' if plain else 'TLS'}")
    check("accepted         : 4" in out and "missing packets  : 1" in out,
          f"{stage}: 4 genuine packets accepted through mosquitto, 1 missing")
    check("bad_mac        : 1" in out and "replay         : 1" in out,
          f"{stage}: tampered and replayed packets rejected end to end")
    check("[status]" in out and "online" in out, f"{stage}: retained status topic seen")
    with open(os.path.join(out_dir, "e2e_samples.csv")) as f:
        n = sum(1 for _ in f) - 1
    check(n == 400, f"{stage}: 400 sample rows written ({n})")

    import dt_security_check as C
    msgs = []
    ok = C.run_checks("127.0.0.1", test_port, plain, os.path.join(sec, "keys.json"), out=msgs.append)
    print("   security check said:\n     " + "\n     ".join(msgs))
    check(ok, f"{stage}: every attacker move in dt_security_check.py was stopped")
    broker.terminate()
    broker.wait()
    log.close()
    blog = open(log_path).read().lower()
    check("not authorised" in blog or "not authorized" in blog,
          f"{stage}: mosquitto log records the refused logins")


def e2e(typical):
    tmp = tempfile.mkdtemp()
    sec = os.path.join(tmp, "secrets")
    hpath = os.path.join(tmp, "secrets.h")
    gen = subprocess.run([sys.executable, os.path.join(HOST, "dt_setup_security.py"), "--out", sec,
                          "--secrets-h", hpath, "--broker-ip", "172.20.10.2"], capture_output=True, text=True)
    check(gen.returncode == 0, "dt_setup_security.py ran" + ("" if gen.returncode == 0 else ": " + gen.stderr))
    again = subprocess.run([sys.executable, os.path.join(HOST, "dt_setup_security.py"), "--out", sec,
                            "--secrets-h", hpath], capture_output=True, text=True)
    check(again.returncode != 0 and "already exists" in again.stdout + again.stderr,
          "a second run refuses to overwrite keys without --force")
    v = subprocess.run(["openssl", "verify", "-CAfile", os.path.join(sec, "ca.crt"),
                        os.path.join(sec, "server.crt")], capture_output=True, text=True)
    check(v.returncode == 0, "openssl: server certificate chains to the project CA")
    text = subprocess.run(["openssl", "x509", "-in", os.path.join(sec, "server.crt"), "-noout", "-text"],
                          capture_output=True, text=True).stdout
    check("IP Address:172.20.10.2" in text and "IP Address:127.0.0.1" in text and "TLS Web Server" in text,
          "server certificate has the broker IPs and serverAuth")
    h = open(hpath).read()
    info = json.load(open(os.path.join(sec, "keys.json")))
    kid = info["active_kid"]
    keyhex = info["hmac_keys"][kid]["key_hex"]
    check(f'"{kid}"' in h and ", ".join(f"0x{keyhex[i:i + 2]}" for i in range(0, 64, 2)) in h
          and "BEGIN CERTIFICATE" in h and info["mqtt_users"]["dt_node01"]["password"] in h,
          "secrets.h carries the same key, kid, board password and CA as keys.json")
    check(info["mqtt_users"]["dt_receiver"]["password"] not in h,
          "secrets.h does not contain the receiver's password")
    with open(os.path.join(tmp, "t.c"), "w") as f:
        f.write('#include <stdio.h>\n#include "secrets.h"\nint main(void){fputs(DT_CA_PEM, stdout);'
                'return sizeof(DT_HMAC_KEY)!=32;}\n')
    cc = subprocess.run(["gcc", "-std=c99", "-Wall", "-Werror", "-I", tmp, "-o", os.path.join(tmp, "t"),
                         os.path.join(tmp, "t.c")], capture_output=True, text=True)
    pem = subprocess.run([os.path.join(tmp, "t")], capture_output=True).stdout if cc.returncode == 0 else b""
    check(pem == open(os.path.join(sec, "ca.crt"), "rb").read(),
          "secrets.h compiles and its CA string equals ca.crt" + ("" if cc.returncode == 0 else ": " + cc.stderr))

    for stage in ("2a", "2b"):
        e2e_stage(stage, typical, sec, tmp)
    shutil.rmtree(tmp)


if __name__ == "__main__":
    typical = open(sys.argv[1], "rb").read()
    worst = open(sys.argv[2], "rb").read()
    unit(typical, worst)
    if "--e2e" in sys.argv:
        e2e(typical)
    print("ALL PASS" if fails == 0 else f"{fails} FAILED")
    sys.exit(1 if fails else 0)
