# SmartTE project progress

Updated 2026-10-11.

## M2-S1: environment, queue, and path evidence

**VERIFIED BY EXECUTION**

- Step 0 inspection and `py_compile` passed. Environment details are in [step0_environment.txt](../logs/m2_verification/step0_environment.txt): WSL2 Ubuntu 24.04.5, `andy2341`, aarch64, Python 3.12.3, Mininet 2.3.0, Open vSwitch 3.3.9, Git 2.43.0.
- Queue audits at 100 and 20 packets show the requested `netem limit` on all eight inter-switch interfaces. Runner metadata records `queue_limit_verified: true`; raw `tc` output is in [queue 100](../logs/m2_verification/static_baseline_20261011_095057/A_c0_tc.txt) and [queue 20](../logs/m2_verification/static_baseline_20261011_095125/A_c0_tc.txt). No qdisc fix was needed.
- The full path-evidence run recorded nine primary trial rows with `experiment_status=ok`: three h1–h2 trials on Path A, three on Path B, and three with h3–h4 configured on Path A. Its final h3–h4 check returned false because of the counter-key bug below; the live recheck with the corrected validator passed. CSV and raw output are in [the run folder](../logs/m2_verification/static_baseline_20261011_100417/).
- Corrected live h3–h4 validation passed in [path_validation_recheck_20261011_103528](../logs/m2_verification/path_validation_recheck_20261011_103528/summary.json): with h3–h4 rules off, ping loss was 100% and both core paths had zero packet delta; with Path A rules on, ping loss was 0%, Path A had 80 packet-counter increments, Path B had zero, and no duplicate reply was seen.
- Saved h1/h2 neighbor dumps show `PERMANENT` ARP entries. No `DUP!` marker appears in the full path run’s ping logs. After cleanup, `ovs-vsctl list-br`, `ip netns list`, and the `iperf3`/`ping` process check returned no entries.
- Seven helper unit tests pass. They cover numeric and named OVS ports, split RX/TX lines, packet-delta keys, path validation, duplicate replies, and complete background iperf JSON.

## M2-S2: contention gate and frozen settings

**VERIFIED BY EXECUTION**

- The first contention pilot (`static_baseline_20261011_104020`) exposed a runner defect: the background UDP iperf client had not written its JSON before cleanup. Those competing-flow rows are excluded from results. The failed outputs and CSV are retained in [the diagnostic run folder](../logs/m2_verification/static_baseline_20261011_104020/).
- Fixed the runner to wait for complete receiver-side UDP JSON (or a reported iperf error) before cleanup. Seven runner-helper unit tests passed after the change.
- Repeated the same short gate at 0, 5, and 9 Mbps, two trials each, for 10-second TCP runs. All six rows are `ok` in [the verified pilot CSV](../logs/m2_verification/static_baseline_20261011_104335/static_baseline_20261011_104335.csv). Mean h1-h2 receiver throughput was 9.487, 4.409, and 0.766 Mbps respectively. Competing receiver throughput was 4.965/4.982 Mbps at 5 Mbps offered and 8.805/8.907 Mbps at 9 Mbps offered; reported UDP loss was 0.203-0.536% and 0.837-1.681% respectively. The 0 Mbps rows have no competing UDP measurement. The gate passes: competing traffic measurably reduced h1-h2 throughput.
- Utilization values are sampled from OVS port `tx_bytes`, not inferred from iperf. The measured Path A utilization was 95.6-99.9% in loaded pilot rows; Path B was 0%. Port deltas recorded zero packets on the unused Path B during each Path A trial. No duplicate ping replies were reported.

**FROZEN FOR THE REMAINING COMPARISONS**

- Shared topology: Path A and Path B core links 10 Mbps, host access links 100 Mbps; access delay 1 ms, Path A delay 5 ms, Path B delay 10 ms; static ARP and the same IPv6 control-frame suppression for these IPv4 runs.
- Queue limit: 100 packets for the primary comparison, verified from `tc` output on all eight inter-switch interfaces. Queue 20 is reserved for the queue-sensitivity comparison and was independently verified. No queue fix was needed.
- Workload: h1-h2 TCP receiver throughput and ping RTT/loss; optional h3-h4 UDP on Path A at offered rates 0, 5, or 9 Mbps. Main matrix duration 15 seconds, five trials per configuration. Keep these settings and the same measurement/decision objective for static, B, and C; do not tune from the main results.

## M2 work remaining

- **IN PROGRESS:** Full static A/B matrix and queue-sensitivity comparison are pending.
- **NOT STARTED:** M3 controller, M4 algorithms and pilot, M5 E1-E4, analysis, and Section 8 deliverables.
- **OPEN RISK:** Mininet prints `sch_htb: quantum of class 50001 is big` warnings on 100 Mbps access links. The requested core queue limits were visible and verified; the warning did not stop the recorded trials.

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
