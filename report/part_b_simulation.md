# SmartTE simulation and evaluation

> **DRAFT FOR STUDENT REWRITE.** This draft reports measured evidence from the repository. Rewrite it in your own words and check every value against the cited raw CSV and processed tables before submission.

## Aim and experimental design

The experiment compares three ways to route the primary h1–h2 TCP flow in a four-switch diamond: a fixed static path, Algorithm B, which follows the lower measured path score, and Algorithm C, which adds a switching margin and minimum dwell. The h3–h4 pair can send competing UDP traffic over Path A. The aim is to observe how path choice changes TCP receiver throughput, ping delay and loss, counter-based utilization, route changes, reaction/recovery, and controller overhead. The design does not assume one policy will outperform the others.

## Emulated network

| Component | Configuration |
|---|---|
| Hosts | h1–h4; primary pair h1–h2; competing pair h3–h4 |
| Switches | Open vSwitch s1–s4, OpenFlow 1.3 |
| Path A | s1–s2–s4, 10 Mbps per core link and 5 ms delay per link |
| Path B | s1–s3–s4, 10 Mbps per core link and 10 ms delay per link |
| Host access | 100 Mbps and 1 ms delay |
| Main core queue | Netem limit 100 packets, verified on all eight directed core interfaces with `tc` |
| Address resolution | Static ARP; no ARP flood rules |
| Telemetry | OpenFlow `tx_bytes` counters and monotonic sample intervals |

The path and port assignments come from `topology/spec.py`. Each route has forward and reverse IPv4 rules. Static ARP avoids sending broadcast requests into the layer-2 cycle. IPv6 control traffic is disabled on Mininet interfaces during these IPv4 trials so it cannot appear as unrelated path load.

## Policies and measurements

Path A's score is the maximum utilization of s1→s2 and s2→s4; Path B's score is the maximum of s1→s3 and s3→s4. For each port, utilization is `(delta_tx_bytes × 8) / (elapsed_seconds × configured_capacity_bps) × 100`. The TCP flow is included in the counters. Receiver-side iperf3 provides TCP throughput; ping provides RTT and loss. The runner also records receiver-side UDP rate/loss, path changes and decision counts, event-based reaction/recovery measures, controller CPU/polling samples, queue audits, and post-run cookie cleanup.

Algorithm B switches to the lower score when the improvement exceeds the comparison epsilon. Algorithm C uses a 1,000 ms polling interval, 15-percentage-point improvement margin, and 5,000 ms minimum dwell in the frozen reference configuration. The five-setting C pilot used one trial per setting to choose the reference before the main campaign; it is exploratory and is not used as evidence of superiority. E3 declares its parameter sensitivity in advance.

## M2 validation and contention gate

Before running controller experiments, the static baseline was checked for route use, queue configuration, and measurable contention. The contention gate used two trials at each offered h3–h4 UDP rate and 10-second h1–h2 TCP windows. Mean h1–h2 receiver throughput was 9.487 Mbps at zero competing load, 4.409 Mbps at 5 Mbps offered, and 0.766 Mbps at 9 Mbps offered. Thus Path A load reduced TCP throughput in this setup. The competing UDP receiver measured 4.965–4.982 Mbps at 5 Mbps offered and 8.805–8.907 Mbps at 9 Mbps offered. Utilization was measured from switch counters; the Path A loaded pilot measured 95.6–99.9% utilization, while the unused Path B packet delta was zero in the Path A-only trials. This passed the precondition for the controller comparison.

The frozen 30-trial static matrix (five trials per condition) further shows the path asymmetry under competition. Values below are mean ± sample standard deviation from the CSV; path utilization is based on the counter port on each path.

| Primary route | h3–h4 offered UDP (Mbps) | h1–h2 TCP (Mbps) | Path A utilization (%) | Path B utilization (%) |
|---|---:|---:|---:|---:|
| A | 0 | 9.50 ± 0.03 | 96.65 ± 0.10 | 0.00 ± 0.00 |
| A | 5 | 4.52 ± 0.07 | 97.43 ± 0.80 | 0.00 ± 0.00 |
| A | 9 | 0.74 ± 0.09 | 98.62 ± 1.17 | 0.00 ± 0.00 |
| B | 0 | 9.44 ± 0.03 | 0.00 ± 0.00 | 95.56 ± 0.23 |
| B | 5 | 9.46 ± 0.03 | 51.58 ± 0.04 | 95.77 ± 0.08 |
| B | 9 | 9.45 ± 0.03 | 92.82 ± 0.24 | 95.64 ± 0.22 |

The queue sensitivity trials at Path A with 9 Mbps competing UDP also illustrate why the core queue limit was held fixed. With three trials per effective queue, the 20-packet, 100-packet, and observed 1,000-packet default settings had mean TCP rates of 0.81 ± 0.04, 0.81 ± 0.04, and 1.34 ± 0.16 Mbps. Mean RTT was 43.54 ± 1.18, 141.21 ± 2.91, and 873.37 ± 64.24 ms, respectively. These are small-sample observations, not a queue optimization result. Core limits were visible in `tc`; Mininet also creates separate access-link queues.

## Controller reproduction and pilot

Ryu was attempted first in an isolated Python 3.10 environment. Its legacy packaging path failed, and a source attempt failed with Eventlet runtime incompatibilities. OS-Ken 4.2.2 then ran in the isolated environment with OpenFlow 1.3. In the 60-second controller spike, both pinned paths passed ping/TCP checks without a `DUP!` marker; path counters showed traffic on the selected route and zero packet delta on the unused route. Controller `tx_bytes` matched `ovs-ofctl` on checked ports. Cookie-owned flow cleanup was checked after process exit.

The controller-installed static reproduction completed 10/10 trials. Mean receiver TCP throughput was 9.472 ± 0.048 Mbps on Path A and 9.475 ± 0.014 Mbps on Path B (five trials each). This reproduces the pinned static behavior through controller-installed rules. The M4 pilot then checked that B can change paths and that C's margin/dwell conditions are applied; one pilot trial per setting is not a comparative performance estimate.

## M5 main results

The frozen campaign completed all 110 planned rows: E1 15, E2 40, E3 40, and E4 15. The raw CSV records 105 `ok` rows and five `failed` rows. All five failed rows are the static E4 control, where the pinned Path A is deliberately broken; the receiver TCP JSON is unavailable and ping loss is 93.33% in each trial. There are no aborted or queue-excluded rows. The interrupted earlier campaign is excluded. Every M5 trial manifest reports queue 100 verified from `tc`; the quality audit found no `DUP!` ping replies and verified cookie cleanup on all controller trials.

The summaries below use mean ± sample SD, `n=5`, from [the completed CSV](../results/raw/m5_campaign_20261011T115819Z.csv). Processed tables and figures are in [the campaign analysis folder](../results/processed/m5_campaign_20261011T115819Z/). The 95% Student-t intervals in the processed CSVs are descriptive; no significance test was specified.

### E1: no competing UDP

| Policy | TCP receiver Mbps | Mean ping RTT ms | Ping loss % | Successful path changes/trial |
|---|---:|---:|---:|---:|
| Static | 9.50 ± 0.02 | 179.07 ± 4.26 | 2.13 ± 1.52 | 0 |
| B | 7.81 ± 0.32 | 40.86 ± 1.18 | 4.27 ± 7.51 | 16 |
| C (15 pp / 5 s) | 9.31 ± 0.08 | 182.80 ± 4.42 | 4.53 ± 1.19 | 3 |

With no h3–h4 competitor, B still switched repeatedly while responding to the controlled TCP flow's own port-counter load; it averaged 16 successful route changes and lower TCP throughput than the other policies. C averaged three changes and retained throughput close to the static reference, but its mean RTT was similar to static. C's margin and dwell reduced switching in this case; they did not improve every metric.

### E2: sustained competing UDP

| Primary policy / start path | UDP offered Mbps | UDP received Mbps | TCP receiver Mbps | Mean RTT ms | Ping loss % | Successful path changes/trial | Reaction time s |
|---|---:|---:|---:|---:|---:|---:|---:|
| Static / A | 5 | 4.94 ± 0.01 | 5.95 ± 0.10 | 159.86 ± 11.67 | 3.40 ± 2.30 | 0 | — |
| Static / B | 5 | 4.99 ± 0.00 | 9.46 ± 0.05 | 195.68 ± 21.20 | 1.60 ± 0.89 | 0 | — |
| B / A | 5 | 4.99 ± 0.00 | 6.26 ± 0.24 | 51.80 ± 1.62 | 10.60 ± 5.32 | 18.20 ± 0.45 | 0.206 ± 0.029 |
| C / A (15 pp / 5 s) | 5 | 4.93 ± 0.01 | 7.44 ± 0.11 | 140.72 ± 3.29 | 4.40 ± 0.89 | 4 | 2.206 ± 0.033 |
| Static / A | 9 | 8.64 ± 0.05 | 3.31 ± 0.12 | 152.75 ± 8.28 | 5.20 ± 2.95 | 0 | — |
| Static / B | 9 | 8.99 ± 0.00 | 9.48 ± 0.03 | 203.64 ± 14.43 | 1.20 ± 1.30 | 0 | — |
| B / A | 9 | 8.81 ± 0.05 | 6.22 ± 0.37 | 68.31 ± 6.57 | 12.20 ± 3.63 | 14.60 ± 0.89 | 0.229 ± 0.031 |
| C / A (15 pp / 5 s) | 9 | 8.98 ± 0.00 | 9.45 ± 0.01 | 206.71 ± 15.15 | 1.40 ± 0.55 | 2 | — |

The static references show the shared-bottleneck effect: at 9 Mbps offered, pinning the primary TCP flow to A gave 3.31 Mbps, while pinning it to B gave 9.48 Mbps. B moved frequently and averaged 6.22–6.26 Mbps across the two loads. C averaged 7.44 Mbps at 5 Mbps offered and 9.45 Mbps at 9 Mbps offered, with fewer changes than B. For C at 9 Mbps, no load-on reaction time was recorded; the event log contains no path-change FlowMod tagged after the load-on event. Do not present this as a measured reaction delay.

### E3: three scheduled bursts and C sensitivity

| Policy / margin / dwell | TCP receiver Mbps | Mean RTT ms | Ping loss % | Successful path changes/trial |
|---|---:|---:|---:|---:|
| Static / A | 5.27 ± 0.05 | 124.07 ± 3.42 | 8.00 ± 1.94 | 0 |
| Static / B | 9.50 ± 0.01 | 204.97 ± 22.01 | 1.33 ± 0.47 | 0 |
| B / reference | 6.07 ± 0.31 | 62.78 ± 3.99 | 7.47 ± 2.92 | 25 |
| C / 10 pp / 5 s | 9.10 ± 0.35 | 184.35 ± 15.93 | 4.13 ± 0.87 | 5 |
| C / 15 pp / 2 s | 8.87 ± 0.36 | 112.77 ± 19.58 | 4.00 ± 1.33 | 7.80 ± 0.84 |
| C / 15 pp / 5 s | 8.86 ± 0.14 | 182.16 ± 16.90 | 5.07 ± 1.01 | 5 |
| C / 15 pp / 10 s | 7.84 ± 0.07 | 149.19 ± 17.63 | 6.53 ± 0.87 | 3 |
| C / 30 pp / 5 s | 8.85 ± 0.33 | 192.19 ± 18.36 | 5.33 ± 1.25 | 5 |

B had the most route changes and lower TCP throughput in the burst schedule. The C variants generally changed paths fewer times and delivered higher mean TCP throughput than B, with trade-offs among RTT, loss, and responsiveness. A longer dwell reduced changes in the observed sample but also had the lowest C throughput. These five-trial results do not identify a universally best margin/dwell setting; the reference parameters remained frozen and were not retuned from these results.

### E4: Path A link-down diagnostic

All policies used the same queue, 15-second TCP workload, initial configuration A, and s2–s4 link-down event. Static produced no receiver TCP result in 5/5 trials and mean ping loss of 93.33%. B averaged 9.210 ± 0.240 Mbps; C averaged 9.214 ± 0.013 Mbps. The event audit shows B had already moved to B before link-down in 5/5 trials, whereas C was still on A at failure and changed to B just after it in 5/5. Thus E4 is a same-protocol policy outcome, but it is not a like-for-like failover-latency comparison: B's path was already different when the failure occurred.

The raw E4 `path_changes` cells count rejected switch decisions as well as successful transitions: B averages 17 logged switch decisions but one successful route change per trial; C averages 11.8 decisions and one successful route change. The controller refuses the failed-path requests, so these repeated attempts do not represent additional data-plane transitions. [The path-change audit](../results/processed/m5_campaign_20261011T115819Z/path_change_audit.csv) preserves both counts. E4 is therefore diagnostic and is excluded from the main B-versus-C path-change comparison. Its recovery-time values should not be used to rank B and C because B had left A before the failure event.

### Controller overhead

Across E1–E3 controller-stat cycles, mean OpenFlow polling round-trip was 2.304 ms for static, 2.340 ms for B, and 2.430 ms for C. Mean OS-Ken process CPU time per statistics cycle was 1.605, 1.612, and 1.663 ms, respectively. Mean decision CPU time was 0.0101 ms for B and 0.0196 ms for C. These are measurements from this small WSL2/Mininet setup, not evidence of controller scalability.

## Evidence and limits

Primary evidence includes the raw CSV and per-trial files, [the analysis metadata](../results/processed/m5_campaign_20261011T115819Z/analysis_metadata.json), [the quality audit](../results/processed/m5_campaign_20261011T115819Z/data_quality.csv), and [the progress record](../docs/PROGRESS.md). Definitions and null rules are in [the data dictionary](../results/DATA_DICTIONARY.md). This is a single-host Mininet emulation with a narrow topology and traffic matrix, so its results do not establish behavior on physical switches or at production scale.
