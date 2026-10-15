# Week 6 Replay Attack Datasets (packet track)

Fall 2026 CpE-1, Cyber-Attack Modeling and Dataset Generation.

A2 replay family on the authenticated packet path. Eleven labeled episodes on the Week 3
clean carrier, each scored by the unmodified Spring receiver freshness logic.

## Layout

- packet/ Eleven episode CSVs in the Week 4 packet format, each with a JSON sidecar
  carrying episode metadata, parameters, class balance and a frozen sha256.
- cpe2_format/w06_replay_cpe2_format.csv Flat single file for the CpE-2 loader, all
  episodes concatenated.
- harness/ Offline receiver harness, dataset generator, independent verifier, and
  w06_package.py which rebuilds the manifest and the flat CpE-2 file from packet/.
- superseded/v1_A2-3_timing_artifact/ First A2.3 build, kept for traceability only. Do not use.
- w06_manifest.json Per-episode summary with receiver verdicts and checksums.
- w06_replay_detection_notes.md Findings and handover notes.

## Attack codes

- A2.1 packet_replay_verbatim, IP-T. Runs r01 low sequence (reboot hole, accepted),
  r02 regressing sequence (REPLAY), r03 exact duplicate (DUPLICATE).
- A2.2 window_replay, IP-T. Windows of 1, 5, 20, 60 packets from session start, accepted
  through the reboot hole.
- A2.3 payload_replay_fresh_header, IP-F. Windows of 1, 5, 20, 60 packets, all accepted
  (ACCEPTED or OOO_GAP). Generator v2: forged headers inherit seq, timestamp and interval from
  the live packet they replace.

## Labeling

The ground-truth label is attack_code, set by construction. receiver_detection_result is
the receiver verdict, carried as a feature only, and must not be used as a label.

## Limitation

A2.3 timing matches clean traffic in v2. Its remaining packet-layer signature is that each
forged payload repeats an earlier payload in the same episode, which is a property of replay and
not a generator artifact. Carrier sensor values are the firmware pseudo-random stub, so
twin-based physical scoring is deferred until real sensor channels are integrated. See
w06_replay_detection_notes.md, Revision v2.
