# Week 6 Replay Attack Datasets and Detection Notes

Fall 2026 CpE-1, Cyber-Attack Modeling and Dataset Generation.

## Summary

This week models the A2 replay family from the attack taxonomy on the authenticated
packet path, and measures what the deployed receiver freshness logic does against each
variant. Eleven labeled episodes were generated on the Week 3 clean carrier and every
stream was scored by the unmodified freshness function from the Spring host receiver.
The label for each record is the attacker action, set by construction. The receiver
verdict is carried as a separate feature and is never used as a label.

Three replay variants are covered, matching the taxonomy:

- A2.1 packet_replay_verbatim (IP-T). A captured packet is resent byte for byte.
- A2.2 window_replay (IP-T). A contiguous captured segment is resent, window length varied.
- A2.3 payload_replay_fresh_header (IP-F). A stale payload is resent under a current
  sequence number and timestamp with the HMAC recomputed, modeling a compromised node.

## What the receiver catches, and what it does not

The receiver applies four freshness rules in order: duplicate sequence, sequence
regression, board timestamp regression, and a host staleness window of 30 seconds. A
sequence at or below 5 arriving after a higher one is treated as a device reboot and
accepted, which resets the tracker.

| Variant | Injection | Window lengths | Receiver result | Caught at comm layer |
|---|---|---|---|---|
| A2.1 verbatim, regressing sequence | IP-T | 1 | REPLAY | Yes |
| A2.1 verbatim, exact duplicate | IP-T | 1 | DUPLICATE | Yes |
| A2.1 verbatim, low sequence | IP-T | 1 | REBOOT_RESET, accepted | No |
| A2.2 window from session start | IP-T | 1, 5, 20, 60 | REBOOT_RESET then ACCEPTED | No |
| A2.3 fresh header payload replay | IP-F | 1, 5, 20, 60 | ACCEPTED | No |

Findings:

1. Straightforward verbatim replay is caught. A resent packet whose sequence regresses
   below the last accepted one is flagged REPLAY, and an exact resend of the current
   packet is flagged DUPLICATE. The freshness layer handles the naive case.

2. The reboot heuristic is a replay hole. Any replayed packet carrying a sequence at or
   below 5 is accepted as a reboot and resets the receiver tracker. An attacker who
   begins a replay at the start of a captured session therefore has the entire window
   accepted, at every window length tested (1, 5, 20 and 60 packets). Window length is
   the difficulty parameter for concealment, not for detection, because detection does
   not improve with length once the reboot path is taken.

3. Fresh header payload replay defeats the communication layer completely. When the
   sequence and timestamp advance normally and the HMAC is recomputed over the stale
   payload, every packet is ACCEPTED. Recall at the communication layer is zero across
   all 86 attacked packets. (In the v2 files 13 of the 86 carry OOO_GAP rather than ACCEPTED because
   they inherit the carrier fault-injection gaps. OOO_GAP is an accepting verdict.) This is the variant that most directly justifies the digital
   twin, since only physical implausibility against the concurrent load condition can
   separate it from clean traffic.

## Handover notes for CpE-2

- Do not train on the receiver verdict. receiver_detection_result is a detector output,
  listed in the taxonomy prohibited label sources. The ground-truth label is attack_code.
- A2.3 header timing now matches clean traffic (revision v2, below). Each forged packet carries the
  sequence number, board timestamp and host interval of the live packet it replaces, so timing and
  sequence features carry no attack information. The remaining packet-layer signature is content.
  The replayed window is taken from the start of the same session, so every forged payload exactly
  repeats an earlier payload in the episode (86 of 86), against 12 of 276 chance repeats among clean
  rows on the rand() stub. That is a property of replay itself and a payload-history check is a
  legitimate detector for it. It weakens if the replayed segment lies outside the detector memory.
  Physical scoring against the concurrent load condition still needs the real sensor channels and is
  deferred until sensor integration.
- Class balance per episode is recorded in each JSON sidecar. Group any split by episode,
  since a single replay window is one correlated event, not N independent samples.

## Required action

The reboot heuristic accepting any sequence at or below 5 is a concrete firmware and
receiver weakness, not only a dataset artifact. Recommended fix for the receiver team: a
per boot session nonce or session identifier carried inside the HMAC, so a replayed low
sequence packet from an earlier session cannot be accepted as a fresh reboot. This also
closes the reboot equals replay ambiguity noted in the Spring handoff.

## Reproduction

The generator, the offline receiver harness, and the independent verifier are in the
harness folder. The harness loads the unmodified Spring receiver freshness logic and
drives it with a virtual clock. The verifier recomputes every ciphertext, every HMAC,
and every receiver verdict from the stored plaintext, with no state shared from the
generator. All eleven episodes pass.

## Revision v2 (September 28, 2026): A2.3 header timing fix

The first A2.3 build gave every forged packet a sequence step of 1 and a board timestamp step and
host interval of exactly 205 ms. Live single-step intervals on the carrier range from 124 to 506 ms
and are never exactly 205 ms, and the live sequence skips by two roughly every fifth packet because
of firmware fault injection. A timing rule scored the v1 episodes almost perfectly (AUC 0.99 on
distance from 205 ms), so a classifier would have learned the generator rather than the attack.

The generator now takes seq_num, timestamp_ms, host_delta_ms and the PWM fields for each forged
packet from the concurrent carrier packet it replaces. Only the telemetry is stale. The verifier
gained an independent check that every A2.3 attack row matches the Week 3 carrier header for that
sequence number, and all four episodes pass it. A2.1 and A2.2 regenerate byte-identical. Record
counts are unchanged (704 clean, 175 attack). The manifest and the flat CpE-2 file are rebuilt by
harness/w06_package.py, which reproduced the v1 files byte for byte before the fix. The v1 files
are kept in superseded/v1_A2-3_timing_artifact/ for traceability and must not be used.

File names keep the multi channel and PENDING severity tokens. Both are valid in labels_schema
v1.0.0. multi reflects that temperature and humidity are replayed together, and PENDING reflects
that no clean-condition sigma exists for the stub channels, so severity cannot be banded.
