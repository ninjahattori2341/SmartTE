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

## M2-S3: static matrix and queue sensitivity

**VERIFIED BY EXECUTION**

- The frozen static matrix completed 30/30 trials with `experiment_status=ok`: path A/B x offered h3-h4 UDP 0/5/9 Mbps x five trials, 15-second TCP windows, queue 100. Full CSV, metadata, per-trial iperf/ping/counter files, and `tc` captures are in [static run 104756](../logs/m2_verification/static_baseline_20261011_104756/). A second validation found all 30 ping files free of `DUP!` and no unexpected unused-path packets in the Path A-only trials.
- Table below reports mean and sample standard deviation from the CSV (`n=5`). TCP is receiver-side iperf3; path utilization is derived from OVS `tx_bytes`, using s2 port 2 for Path A and s3 port 2 for Path B. RTT summaries use ping samples with the first received sample discarded as a precaution; ping loss retains every transmitted request in the denominator.

| Primary path | UDP offered (Mbps) | TCP receiver Mbps | RTT avg (ms) | RTT p95 (ms) | Ping loss (%) | UDP received Mbps / loss (%) | Path A / B utilization (%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 0 | 9.50 +/- 0.03 | 165.74 +/- 15.58 | 244.00 +/- 7.18 | 3.73 +/- 1.46 | n/a | 96.65 +/- 0.10 / 0.00 +/- 0.00 |
| A | 5 | 4.52 +/- 0.07 | 137.69 +/- 6.05 | 178.60 +/- 8.85 | 0.27 +/- 0.60 | 4.98 +/- 0.01 / 0.17 +/- 0.10 | 97.43 +/- 0.80 / 0.00 +/- 0.00 |
| A | 9 | 0.74 +/- 0.09 | 140.46 +/- 4.88 | 155.00 +/- 8.86 | 3.47 +/- 2.42 | 8.85 +/- 0.04 / 1.47 +/- 0.49 | 98.62 +/- 1.17 / 0.00 +/- 0.00 |
| B | 0 | 9.44 +/- 0.03 | 208.91 +/- 26.24 | 267.40 +/- 3.85 | 1.87 +/- 0.73 | n/a | 0.00 +/- 0.00 / 95.56 +/- 0.23 |
| B | 5 | 9.46 +/- 0.03 | 189.22 +/- 8.31 | 263.20 +/- 3.49 | 2.40 +/- 1.12 | 4.99 +/- 0.00 / 0.00 +/- 0.00 | 51.58 +/- 0.04 / 95.77 +/- 0.08 |
| B | 9 | 9.45 +/- 0.03 | 191.69 +/- 8.04 | 265.60 +/- 3.65 | 1.33 +/- 0.94 | 8.98 +/- 0.01 / 0.07 +/- 0.16 | 92.82 +/- 0.24 / 95.64 +/- 0.22 |

- The gate passes. Relative to the Path A 0 Mbps baseline (9.50 Mbps), mean h1-h2 throughput declined about 52.4% at 5 Mbps and 92.2% at 9 Mbps: `(baseline - loaded) / baseline * 100`. On Path B, mean throughput remained between 9.44 and 9.46 Mbps while Path A carried the competing flow.
- Counter evidence shows the A-only 9 Mbps trial `A_c9_t1` had 16,913 transmitted packets on s2 port 2 and zero packet delta on the unused Path B. With primary Path B and a Path A competitor (`B_c9_t1`), Path A and B egress deltas were 16,273 and 6,719 packets. The competing and primary flows therefore use the intended shared Path A core while Path B retains spare capacity. A separate single-flow 9 Mbps UDP validation measured 8.976 Mbps received, 0% receiver loss, and 90.314% Path A utilization from s2 port 2 (`delta_tx_bytes=11,577,014`, monotonic interval 10.254905 s); the utilization is 0.314 percentage points above 90%.
- Queue sensitivity used three fresh 15-second Path A / 9 Mbps trials at each effective limit. Queue 100 was independently rerun rather than sampled from the main matrix. All nine rows were `ok`; the 100-packet and 20-packet limits were explicitly visible on every core interface. With `--queue 0`, Mininet omitted `max_queue_size`; `tc` showed the default netem limit of 1,000 packets on each core interface, which the runner now resolves and records. Evidence: [queue 20](../logs/m2_verification/static_baseline_20261011_110325/), [queue 100](../logs/m2_verification/static_baseline_20261011_110630/), [Mininet default](../logs/m2_verification/static_baseline_20261011_110455/), and [default queue audit](../logs/m2_verification/static_baseline_20261011_110307/).

| Effective core limit | h1-h2 TCP Mbps | RTT avg ms | RTT p95 ms | Ping loss % | UDP received Mbps / loss % | Path A utilization % |
|---:|---:|---:|---:|---:|---:|---:|
| 20 | 0.81 +/- 0.04 | 43.54 +/- 1.18 | 48.87 +/- 3.46 | 8.00 +/- 1.33 | 8.81 +/- 0.04 / 1.98 +/- 0.41 | 98.87 +/- 0.67 |
| 100 | 0.81 +/- 0.04 | 141.21 +/- 2.91 | 149.67 +/- 3.79 | 4.00 +/- 1.33 | 8.89 +/- 0.02 / 1.00 +/- 0.25 | 99.47 +/- 0.33 |
| 1000 (Mininet default) | 1.34 +/- 0.16 | 873.37 +/- 64.24 | 1489.33 +/- 244.96 | 9.33 +/- 1.33 | 8.33 +/- 0.09 / 2.67 +/- 0.97 | 98.73 +/- 1.46 |

**QUEUE AND LATENCY INTERPRETATION**

- On each 10 Mbps core egress, 100 packets of 1,514 bytes correspond to about 121 ms of serialization time (`100 * 1514 * 8 / 10,000,000`). `tc` shows two serial core-link netem queues along a path, so the earlier 145 ms estimate (24 ms path RTT plus one 121 ms queue) was incomplete; two queues can contribute about 242 ms in one direction. This makes 188.7 ms plausible under load. The experiment did not continuously sample transient queue occupancy, so it does not prove that a particular ping saw a full queue.
- The four 100 Mbps access interfaces also show HTB plus `netem limit 1000 delay 1ms` in the raw `tc` evidence. These queues are outside the core `queue_limit_pkts` treatment. They do not set the configured 10 Mbps bottleneck, but a backlog there could also add delay; the trials did not measure access-queue occupancy over time.
- The three queue settings show a latency/loss tradeoff in this small sample. Do not call any setting best from n=3. Keep the primary static/B/C comparison fixed at the verified 100-packet core limit.

**M2 COMPLETE**

- The zero-load static path evidence, queue audits at 20/100/default, static contention gate, full static matrix, and queue-sensitivity trials are recorded. The UDP-only port-counter validation measured the requested near-90% utilization.
- Ten helper unit tests and `py_compile` for the runner and topology passed after adding verified default-queue support.
- **OPEN RISK:** Mininet prints `sch_htb: quantum of class 50001 is big` warnings on 100 Mbps access links. All recorded trials completed; access queues are visible and are discussed above.
- **NEXT:** M3 controller setup in an isolated Python environment; reproduce the static baseline using controller-installed rules before B/C measurements.

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
