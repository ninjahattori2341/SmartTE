# SmartTE viva guide

**Study guide for the student.** Explain the implementation in your own words and use the linked raw evidence when asked about a measured result. Do not quote a number from this guide without checking the completed campaign tables in `results/processed/`.

## One-minute explanation

SmartTE is a small software-defined networking experiment. Four Open vSwitches form a diamond with two 10 Mbps routes between h1 and h2. A second pair, h3 and h4, can create competing UDP traffic on Path A. The OS-Ken controller polls switch port counters once per second. It estimates each path's utilization from the change in transmitted bytes divided by elapsed time and link capacity. The experiment compares fixed routing, policy B (move to the less-used path when it is meaningfully better), and policy C (B plus a 15 percentage-point improvement margin and a 5-second minimum dwell). TCP receiver throughput, ping delay/loss, path counters, route changes, reaction/recovery, and controller overhead are recorded. All policies use the same topology and workloads. This is a controlled Mininet emulation, so its results describe this setup rather than production networks.

## How a packet gets through

1. h1 sends an IPv4 packet for h2 to switch s1.
2. The selected flow-table rule on s1 sends it onto Path A through s2, or Path B through s3.
3. The middle switch forwards the packet to s4, and s4 sends it to h2. Reverse-direction rules carry replies back along the selected route.
4. Switches use OpenFlow 1.3 flow entries. Permanent ARP neighbor entries are preinstalled, so ARP does not need a broadcast flood rule in the looped diamond.
5. For a route change, the controller installs the new path rules and updates the ingress forwarding decision, then removes only the old rules owned by its cookie. The evidence checks the final flow tables and selected-path counters; this implementation does not claim a formal per-packet consistency guarantee.

## What the controller measures

For a port counter sample, utilization is calculated as:

`(current_tx_bytes - previous_tx_bytes) * 8 / (elapsed_seconds * capacity_bps) * 100`

Path A's decision score is the higher of its two core-link utilization estimates (s1→s2 and s2→s4). Path B uses the higher of s1→s3 and s3→s4. Taking the maximum prevents an average from hiding one saturated hop. The controlled TCP flow is included in these counters. Utilization is not derived from iperf. Missing/decreasing counters, invalid capacity, or a sample interval shorter than 0.5 seconds is rejected by the helper instead of treated as a valid score.

The two paths have the same configured 10 Mbps rate. Path A has 5 ms per core link and Path B has 10 ms per core link. Host access links are 100 Mbps with 1 ms configured delay. Core netem limits are verified from `tc`; the main comparisons use 100 packets. Static ARP and IPv6 control-frame suppression are applied consistently to remove unrelated control packets from the IPv4 measurements.

## Policy definitions

| Policy | Decision rule | What to watch |
|---|---|---|
| Static | Keep the configured initial path for the trial. | Gives a fixed-path reference, including when its path is loaded or fails. |
| B | At each valid poll, choose the path with lower maximum core-link utilization; switch if the improvement exceeds the 0.01 percentage-point comparison epsilon. | Responds directly to measured load and may switch repeatedly as measurements move. |
| C | Use B's candidate, but switch only after at least 5 seconds since the previous switch and when the improvement is at least 15 percentage points. | Trades responsiveness for fewer changes; a high margin or dwell can delay a useful move. |

The M4 pilot selected the frozen reference settings before M5. M5 uses a 1,000 ms poll interval; E3 varies C's margin/dwell only as a declared sensitivity experiment. Main-run results were not used to retune the policy.

## Questions you may be asked

### Why use a controller?

A controller has a view of both candidate routes and can compare measurements from both. OpenFlow rules let it program a chosen path. This setup demonstrates that control loop with real OVS flow tables, but it is much smaller than a production controller deployment.

### Why does the topology have two paths and a competing flow?

The two paths make route choice observable. The h3–h4 UDP pair places load on Path A. The M2 contention gate checked that this load actually reduces h1–h2 throughput on A before policy experiments were run. Path B provides an alternate route with spare capacity in that scenario.

### Why compare B and C?

B isolates reactive best-path selection. C adds a hysteresis margin and dwell timer to reduce switches that may be caused by small or short-lived score differences. The comparison asks whether those controls changed route-switch behavior and the measured TCP/latency outcomes under the chosen workload; it does not assume C must win.

### Why use port counters instead of iperf for utilization?

iperf measures the application flow's delivered rate. A switch port counter measures all transmitted bytes on that egress, including packet headers and other traffic. The controller needs a path load estimate that includes competing traffic, so it uses counter deltas over a measured monotonic interval. iperf remains the source for receiver throughput.

### What does the queue limit mean?

The 100-packet limit is the configured netem packet limit on each inter-switch interface and was checked in `tc` output. It is not a measured queue occupancy. It controls the maximum configured queue length, while transient occupancy was not continuously sampled. The 100 Mbps access links also have their own queues and are documented separately.

### Why static ARP?

The switches run in secure mode and the intended OpenFlow rules match IPv4. Static ARP lets the endpoints resolve their neighbors without flooding broadcast ARP through a topology containing a layer-2 cycle. The project explicitly does not install ARP flood rules.

### What does a path-change count show, and what does it not show?

It counts logged controller changes to the primary flow's selected route. It is a direct measure of control behavior, not proof that every packet experienced a disruption. Ping loss/RTT and the raw event and counter logs give separate evidence about packet outcomes.

### How is reaction time defined?

For a load-on comparison it is the time from the logged competing-load onset to the first FlowMod event that changes the primary path. It measures when the controller sent an action, not the exact time the first affected packet arrived or the time all switches finished applying it. Recovery is separately defined from the relevant load-off or link-down event and uses logged action/counter evidence.

### What is the most important limitation?

This is a single-host Mininet emulation with one primary TCP flow, one competing UDP pair, two paths, and a small sample count. It does not reproduce hardware switch forwarding, a large traffic matrix, distributed controller delay, or production failure conditions. Confidence intervals are descriptive; the project does not claim statistical significance from them.

## Results to cite in the viva

Use the final campaign only: [processed results folder](../results/processed/) and [completed campaign CSV](../results/raw/). State the experiment ID, policy, load/failure condition, sample size, mean and spread or interval, and the corresponding evidence path. Report E4 only if the final fairness audit supports a direct comparison. Do not use the earlier interrupted 20-row campaign.

## Student preparation

- Be able to identify each switch port and route from `topology/spec.py`.
- Open one real controller event log and explain the scores, decision reason, and before/after path.
- Trace a summary row back to its raw trial files and analysis command.
- Learn the significance and limitation of every result you present; do not claim that a small emulation proves general network performance.
- Complete the report in your own words and follow the course's AI-use, citation, and similarity rules.
