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
   all 86 attacked packets. This is the variant that most directly justifies the digital
   twin, since only physical implausibility against the concurrent load condition can
   separate it from clean traffic.

## Handover notes for CpE-2

- Do not train on the receiver verdict. receiver_detection_result is a detector output,
  listed in the taxonomy prohibited label sources. The ground-truth label is attack_code.
- A2.3 is not separable at the packet layer by construction. On this carrier the sensor
  values are the firmware pseudo-random stub, so the A2.3 rows are identical in
  distribution to clean rows. Any classifier that appears to separate them on this file
  is reading a carrier artifact, not the attack. Twin-based physical scoring is required,
  and is deferred until the real sensor channels are integrated.
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
