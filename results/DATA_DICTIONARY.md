# Results CSV data dictionary

The CSV schema is shared by direct-`dpctl` static baseline, controller-installed
static rules, Algorithm B, and Algorithm C. Keep the column names and order
below stable. CSV nulls are written as empty fields;
the reason must be recorded in `notes`. Numeric zero is reserved for a measured
zero or a defined static control value.

| # | Column | Unit / type | Definition and null rule |
|---:|---|---|---|
| 1 | `run_id` | string | Unique ID for one runner invocation; never null. |
| 2 | `experiment_id` | string | Stable experiment family identifier; never null. |
| 3 | `timestamp_utc` | ISO 8601 UTC | Trial start time; never null. |
| 4 | `algorithm` | string | Algorithm label. Static rows use `static`; never null. |
| 5 | `scenario` | string | Stable experiment and configuration label (for example E2, selected policy, path, and offered load); never null. |
| 6 | `trial` | integer | One-based trial number within the scenario; never null. |
| 7 | `flow_pair` | string | Primary source-destination pair, currently `h1-h2`; never null. |
| 8 | `competing_pair` | string | Competing source-destination pair (`h3-h4`). Empty when no competing flow is configured. |
| 9 | `initial_path` | string | Selected primary path at trial start (`A` or `B`); never null. |
| 10 | `competing_path` | string | Selected competing path. Empty when no competing path/flow is configured. |
| 11 | `offered_load_mbps` | Mbps | Requested competing UDP rate, including a requested zero rate; never null for this workload. |
| 12 | `bottleneck_mbps` | Mbps | Configured capacity of the primary selected path; never null. |
| 13 | `delay_a_ms` | ms per Path A link | Configured Path A link delay converted to milliseconds; empty only if config cannot be parsed. |
| 14 | `delay_b_ms` | ms per Path B link | Configured Path B link delay converted to milliseconds; empty only if config cannot be parsed. |
| 15 | `queue_limit_pkts` | packets | Effective inter-switch netem limit verified in `tc` output on every core interface. With runner option `--queue 0`, the runner omits Mininet `max_queue_size` and records the default limit actually shown by `tc` (currently 1000 packets). Empty if the effective limit cannot be established. |
| 16 | `queue_config` | string | Qdisc description observed with `tc` on every inter-switch interface. It identifies an explicit `max_queue_size` or the Mininet default and must say `NOT VERIFIED` unless a consistent effective packet limit is visible on every interface. |
| 17 | `tcp_duration_s` | seconds | Requested duration of the primary TCP transfer; never null. |
| 18 | `tcp_throughput_mbps` | Mbps | Receiver-side iperf3 `end.sum_received.bits_per_second` converted to Mbps. Empty if receiver-side result is unavailable; explain in `notes`. |
| 19 | `tcp_retransmits` | packets | Sender-side iperf3 `end.sum_sent.retransmits`. Empty if unavailable; explain in `notes`. |
| 20 | `rtt_min_ms` | ms | Minimum retained ping RTT after discarding the first received RTT sample as a precaution. Empty if no retained RTT samples. |
| 21 | `rtt_avg_ms` | ms | Mean of retained ping RTT samples after the precautionary first-sample discard. Empty if no retained RTT samples. |
| 22 | `rtt_max_ms` | ms | Maximum retained ping RTT after the precautionary first-sample discard. Empty if no retained RTT samples. |
| 23 | `rtt_mdev_ms` | ms | Population standard deviation of retained ping RTT samples. Empty if no retained RTT samples. |
| 24 | `p95_rtt_ms` | ms | Nearest-rank 95th percentile of retained ping RTT samples. Empty if no retained RTT samples. |
| 25 | `ping_loss_pct` | percent | Packet loss percentage from ping's summary. Denominator is the number of transmitted echo requests reported by ping; the first request remains included even though its first received RTT sample is discarded. Empty if ping produced no summary. |
| 26 | `competing_achieved_mbps` | Mbps | Receiver-reported competing UDP delivery rate from iperf3 `end.sum_received`. Empty when no UDP flow was configured or the receiver metric is unavailable; state the reason in `notes`. Do not substitute requested/sender rate. |
| 27 | `competing_loss_pct` | percent | Receiver-reported UDP loss percentage (`lost_packets / packets * 100` from iperf3's receiver summary). Empty when no UDP flow was configured or the metric is unavailable; state the reason in `notes`. |
| 28 | `measured_path_a_utilization_pct` | percent | `(delta_tx_bytes * 8) / (monotonic_interval_seconds * configured_Path_A_capacity_bps) * 100`, using OpenFlow s2 port 2 egress toward s4. Counts all traffic and headers. Empty on counter wrap/decrease, missing counters, or interval under 0.5 s. |
| 29 | `measured_path_b_utilization_pct` | percent | Same calculation using OpenFlow s3 port 2 egress toward s4 and configured Path B capacity. Counts all traffic and headers. Empty on counter wrap/decrease, missing counters, or interval under 0.5 s. |
| 30 | `final_path` | string | Final selected primary path. Static rows keep the initial path; never null for a recorded static trial. |
| 31 | `path_changes` | count | Controller path-change value. Static control value is 0. In the raw M5 CSV this is counted from `decision=switch` events; if the controller rejects a request for an unavailable path, it can exceed successful route transitions. Use processed `path_change_audit.csv` and the event `path_changes_total` counter for actual changes. |
| 32 | `decision_count` | count | Number of controller decisions. Static control value is 0. |
| 33 | `reaction_time_s` | seconds | Time from the competing-load onset event to the first logged FlowMod send that changes the primary path. This is a controller-action timestamp, not a direct packet-arrival time. Empty for no-load/static rows or if no switch occurs. |
| 34 | `recovery_time_s` | seconds | After a load-off event, time to the first logged recovery FlowMod; for E4 link failure, time from link-down to the first later OpenFlow `tx_bytes` sample showing traffic on Path B. Empty when there is no recovery event or no counter confirmation. |
| 35 | `controller_poll_interval_ms` | ms | Configured port-statistics polling interval. Empty only for direct-`dpctl` static trials with no controller. Controller-installed static rules still poll at 1,000 ms. |
| 36 | `switching_threshold` | utilization percentage points | Algorithm C switching margin. Empty for static and B. |
| 37 | `minimum_dwell_time_ms` | ms | Controller minimum dwell time. Empty for static rows. |
| 38 | `experiment_status` | enum | One of `ok`, `failed`, `aborted`, or `excluded`. Failed and aborted trials remain in the CSV. |
| 39 | `raw_log_ref` | relative path | Reference to the trial manifest/raw evidence; never null for a recorded row. |
| 40 | `git_commit` | Git SHA | Commit recorded at run start; use `UNKNOWN` only if unavailable. |
| 41 | `git_dirty` | boolean | `true` iff `git status --porcelain` was non-empty at run start; `false` iff empty. If the command fails, leave empty and explain in `notes`. |
| 42 | `notes` | string | Reasons for null values, anomalies, evidence limitations, first-sample handling, and other trial-specific context. |

## Measurement and provenance rules

- `queue_limit_pkts` records the effective netem limit, not the CLI request. `--queue 100` and `--queue 20` set explicit limits; `--queue 0` omits Mininet `max_queue_size` and discovers the default netem limit from `tc`. The runner excludes trials if the effective value cannot be verified consistently on all eight directed core interfaces. The current Mininet default was observed as `netem limit 1000`.
- Mininet applies a netem delay qdisc to the 100 Mbps access interfaces too. Their current `tc` output also shows `netem limit 1000`; these access queues are separate from the experimental core queue setting and are recorded in the qdisc evidence.
- Static path utilization uses OVS `tx_bytes`; controller-run utilization uses OpenFlow `OFPPortStatsReply.tx_bytes`, sampled around the TCP window with monotonic timestamps. The raw counter values and actual interval belong in the trial's `openflow_utilization_counters.json` or static counter files.
- The CSV's measured utilization fields use s2 port 2 for Path A and s3 port 2 for Path B, both egressing toward s4. For controller decisions, each path score is the maximum utilization of both core egress links: Path A s1 port 3 and s2 port 2; Path B s1 port 4 and s3 port 2. The controlled h1–h2 traffic is included in these counters and scores.
- The path utilization counters include all egress traffic and headers, so utilization can be slightly greater than iperf throughput.
- Controller overhead is stored separately in each controller trial's `controller_overhead.csv` and `controller_overhead.json`. The CSV records poll round-trip seconds, controller process CPU seconds per stats cycle, decision CPU seconds, and FlowMod count after the cycle. It does not add columns to the shared results schema.
- For the M5 raw `path_changes` field, a rejected attempt to select a failed path can be counted as a switch decision even when the route does not change. The analysis retains that value and compares it with the controller's successful `path_changes_total` in `path_change_audit.csv`; processed path-change summaries use the successful event counter where available.
- For scheduled UDP runs, `competing_achieved_mbps` is the sum of receiver-reported bytes divided by the sum of active receiver intervals. `competing_loss_pct` uses iperf3's receiver `lost_packets / packets * 100` across its burst summaries; empty means there was no competing workload or no valid receiver summary.
- The first received RTT sample is discarded as a precaution. This is not a claim that the sample has a known cause; packet loss remains computed from ping's full transmitted count.
- A null competing rate/loss for a zero-load scenario means no competing UDP flow was configured. It is not a measured zero.
- If a trial has a missing required measurement, preserve the row, set `experiment_status` to `failed` or `aborted` as appropriate, and explain the missing field in `notes`.
