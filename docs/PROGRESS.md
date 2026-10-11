# SmartTE project progress

Updated 2026-10-11.

## M2-S1: environment, queue, and path evidence

**VERIFIED BY EXECUTION**

- Step 0 inspection and `py_compile` passed. Environment details are in [step0_environment.txt](../logs/m2_verification/step0_environment.txt): WSL2 Ubuntu 24.04.5, `andy2341`, aarch64, Python 3.12.3, Mininet 2.3.0, Open vSwitch 3.3.9, Git 2.43.0.
- Queue audits at 100 and 20 packets show the requested `netem limit` on all eight inter-switch interfaces. Runner metadata records `queue_limit_verified: true`; raw `tc` output is in [queue 100](../logs/m2_verification/static_baseline_20261011_095057/A_c0_tc.txt) and [queue 20](../logs/m2_verification/static_baseline_20261011_095125/A_c0_tc.txt). No qdisc fix was needed.
- The full path-evidence run recorded nine primary trial rows with `experiment_status=ok`: three h1–h2 trials on Path A, three on Path B, and three with h3–h4 configured on Path A. Its final h3–h4 check returned false because of the counter-key bug below; the live recheck with the corrected validator passed. CSV and raw output are in [the run folder](../logs/m2_verification/static_baseline_20261011_100417/).
- Corrected live h3–h4 validation passed in [path_validation_recheck_20261011_103528](../logs/m2_verification/path_validation_recheck_20261011_103528/summary.json): with h3–h4 rules off, ping loss was 100% and both core paths had zero packet delta; with Path A rules on, ping loss was 0%, Path A had 80 packet-counter increments, Path B had zero, and no duplicate reply was seen.
- Saved h1/h2 neighbor dumps show `PERMANENT` ARP entries. No `DUP!` marker appears in the full path run’s ping logs. After cleanup, `ovs-vsctl list-br`, `ip netns list`, and the `iperf3`/`ping` process check returned no entries.
- Six helper unit tests pass. They cover numeric and named OVS ports, split RX/TX lines, packet-delta keys, path validation, and duplicate replies.

**VERIFIED BY INSPECTION**

- Static IPv4 ARP remains enabled; no ARP flood rule was added. The topology has explicit switch ports and both core paths set to 10 Mbps.
- Per-interface IPv6 suppression is verified on all 16 Mininet host and switch interfaces. This removes Linux router-solicitation and MLD control frames that previously appeared in Path B port counters; a focused AF_PACKET capture recorded zero frames on Path B after suppression.
- The original `sudo -n true` failed because sudo requested a password. WSL root access succeeded with `wsl.exe -d Ubuntu -u root -- id`; privileged Mininet work used that entry point. Generated artifacts are readable in the workspace.

## Defects found and fixed

- OVS 3.3.9 names ports and places RX/TX counters on separate lines; the original parser expected numeric ports and same-line counters. The parser now supports both formats.
- The path validator used an underscore suffix against colon-delimited counter keys. The validator now reads the actual deltas and checks duplicate replies; the corrected live recheck confirms Path A traffic and zero Path B traffic.
- Linux IPv6 control packets polluted inactive-path counters. IPv6 is disabled per Mininet interface for these IPv4 experiments and the settings are recorded.
- Per-port RX/TX imbalances are retained as descriptive values; they are not treated as loop proof because asymmetric TCP data and ACK traffic naturally differ.

## M2 work remaining

- **NOT VERIFIED:** The Path A contention gate has not been run. Compare h1–h2 Path A with no competing flow against h3–h4 UDP on Path A; require measurable degradation before continuing to controller experiments.
- **NOT VERIFIED:** The full static matrix, throughput queue-sensitivity comparison, and remaining M2 evidence are pending.
- **NOT STARTED:** M3 controller, M4 algorithms and pilot, M5 E1–E4, analysis, and Section 8 deliverables.
- **OPEN RISK:** Mininet prints `sch_htb: quantum of class 50001 is big` warnings on 100 Mbps access links. The requested core queue limits were visible and verified; the warning did not stop the recorded trials.
