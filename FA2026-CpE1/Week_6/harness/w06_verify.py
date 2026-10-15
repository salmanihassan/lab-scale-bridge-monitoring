"""Independent verification of the Week 6 replay datasets. Recomputes, from the
stored decrypted plaintext of every row: (1) AES-ECB ciphertext == encrypted_hex,
(2) HMAC over the canonical string == hmac, (3) the receiver verdict, replaying
each episode fresh through the unmodified receiver logic, == receiver_detection_result.
Also checks sidecar sha256 and class balance. Uses no state from the generator."""
import importlib.util, os, glob, json, csv, hashlib, hmac as H
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
HERE=os.path.dirname(os.path.abspath(__file__)); W6=os.path.dirname(HERE)
AES_KEY=b"LabKey12LabKey12"
HMAC_KEY=bytes([0x4d,0x79,0x53,0x65,0x63,0x75,0x72,0x65,0x44,0x69,0x67,0x69,0x74,0x61,0x6c,0x54,
                0x77,0x69,0x6e,0x4b,0x65,0x79,0x32,0x30,0x32,0x36,0x21,0x40,0x23,0x24,0x25,0x5e])
spec=importlib.util.spec_from_file_location("h",os.path.join(HERE,"w06_replay_harness.py"))
h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
MOD=h.load_receiver("/tmp/w06verify")

def check(path):
    rows=list(csv.DictReader(open(path)))
    ct_ok=hm_ok=0; ct_bad=[]; hm_bad=[]
    for r in rows:
        pt=r["decrypted"]
        ct=AES.new(AES_KEY,AES.MODE_ECB).encrypt(pad(pt.encode(),16)).hex().upper()
        if ct==r["encrypted_hex"]: ct_ok+=1
        else: ct_bad.append(r["seq_num"])
        o=json.loads(pt); t=o["telemetry"]
        canon=f'{o["device_id"]}|{o["seq_num"]}|{o["timestamp_ms"]}|{t["temperature_c"]:.1f}|{t["humidity"]:.1f}'
        if H.new(HMAC_KEY,canon.encode(),hashlib.sha256).hexdigest()==r["hmac"]: hm_ok+=1
        else: hm_bad.append(r["seq_num"])
    # replay verdicts fresh
    h.reset(MOD); t=0.0; vbad=0
    for r in rows:
        t+=(int(r["host_delta_ms"]) if r["host_delta_ms"] else 205)/1000.0
        d={"schema_version":"1.1.0","device_id":r["device_id"],"seq_num":int(r["seq_num"]),
           "timestamp_ms":int(r["timestamp_ms"]),
           "telemetry":{"temperature_c":float(r["temperature_c"]),"humidity":float(r["humidity"]),
                        "pwm_duty_us":7000,"pwm_period_us":10000},"hmac":r["hmac"]}
        st=h.process(MOD,d,t)
        if st!=r["receiver_detection_result"]: vbad+=1
    # sidecar
    sc=json.load(open(path[:-4]+".json"))
    sha=hashlib.sha256(open(path,"rb").read()).hexdigest()
    sha_ok=(sha==sc["integrity"]["sha256"])
    natk=sum(1 for r in rows if r["attack_active"]=="True")
    bal=sc["class_balance"]; bal_ok=(bal["attack_records"]==natk and bal["clean_records"]==len(rows)-natk)
    return dict(n=len(rows),ct_bad=ct_bad,hm_bad=hm_bad,verdict_bad=vbad,sha_ok=sha_ok,bal_ok=bal_ok)

CARRIER=os.path.join(W6,"..","Week 3","w03_A0-0_none_none_r01.csv")
CAR={int(r["seq_num"]):r for r in csv.DictReader(open(CARRIER)) if r["session_id"]=="S20260501-02"}

def header_timing(path):
    """A2.3 only (v2 check). Every forged row must carry the seq_num, timestamp_ms and
    host_delta_ms of the live carrier packet with that sequence, read independently from
    the Week 3 carrier, so forged headers cannot differ from clean traffic in timing."""
    rows=list(csv.DictReader(open(path))); bad=0; n=0
    for r in rows:
        if r["attack_active"]!="True": continue
        n+=1; c=CAR.get(int(r["seq_num"]))
        if c is None or c["timestamp_ms"]!=r["timestamp_ms"] or c["host_delta_ms"]!=r["host_delta_ms"]: bad+=1
    seqs=[int(r["seq_num"]) for r in rows]
    mono=all(b>a for a,b in zip(seqs,seqs[1:]))
    return n,bad,mono

allok=True
for p in sorted(glob.glob(os.path.join(W6,"packet","*.csv"))):
    r=check(p)
    ok=(not r["ct_bad"] and not r["hm_bad"] and r["verdict_bad"]==0 and r["sha_ok"] and r["bal_ok"])
    tmsg=""
    if "_A2-3_" in p:
        n,bad,mono=header_timing(p)
        tok=(bad==0 and mono); ok=ok and tok
        tmsg=(f"{'':31}A2.3 header timing: {n-bad}/{n} forged rows match live carrier header, "
              f"sequence strictly increasing={mono} -> {'PASS' if tok else 'FAIL'}")
    allok&=ok
    print(f"{os.path.basename(p):30} n={r['n']:3} ct_bad={len(r['ct_bad'])} hmac_bad={len(r['hm_bad'])} "
          f"verdict_mismatch={r['verdict_bad']} sha={'ok' if r['sha_ok'] else 'BAD'} bal={'ok' if r['bal_ok'] else 'BAD'} -> {'PASS' if ok else 'FAIL'}")
    if tmsg: print(tmsg)
print("\nALL EPISODES:", "PASS" if allok else "FAIL")
