# Week 6 Replay Attack Datasets (packet track)

Fall 2026 CpE-1, Cyber-Attack Modeling and Dataset Generation.

A2 replay family on the authenticated packet path. Eleven labeled episodes on the Week 3
clean carrier, each scored by the unmodified Spring receiver freshness logic.

## Layout

- packet/ Eleven episode CSVs in the Week 4 packet format, each with a JSON sidecar
  carrying episode metadata, parameters, class balance and a frozen sha256.
- cpe2_format/w06_replay_cpe2_format.csv Flat single file for the CpE-2 loader, all
  episodes concatenated.
- harness/ Offline receiver harness, dataset generator, and independent verifier.
- w06_manifest.json Per-episode summary with receiver verdicts and checksums.
- w06_replay_detection_notes.md Findings and handover notes.

## Attack codes

- A2.1 packet_replay_verbatim, IP-T. Runs r01 low sequence (reboot hole, accepted),
  r02 regressing sequence (REPLAY), r03 exact duplicate (DUPLICATE).
- A2.2 window_replay, IP-T. Windows of 1, 5, 20, 60 packets from session start, accepted
  through the reboot hole.
- A2.3 payload_replay_fresh_header, IP-F. Windows of 1, 5, 20, 60 packets, all ACCEPTED.

## Labeling

The ground-truth label is attack_code, set by construction. receiver_detection_result is
the receiver verdict, carried as a feature only, and must not be used as a label.

## Limitation

Carrier sensor values are the firmware pseudo-random stub, so A2.3 is not separable at
the packet layer. Twin-based physical scoring is deferred until real sensor channels are
integrated.
