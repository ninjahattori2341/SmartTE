# SmartTE interpretation and alignment with prior work

This section connects the project design to verified sources in [the bibliography](references.md) and interprets the completed M5 analysis. Results are specific to the documented emulation and workload.

## What this experiment can say

The M2 static measurements demonstrate that the selected path matters when traffic shares a bottleneck in this emulation. With h1–h2 pinned to Path A, adding 5 Mbps of h3–h4 UDP reduced mean TCP receiver throughput from 9.50 to 4.52 Mbps; at 9 Mbps offered it was 0.74 Mbps. With h1–h2 pinned to Path B and h3–h4 using Path A, h1–h2 throughput remained around 9.44–9.46 Mbps. The counter evidence confirms that the intended routes carried the traffic. This establishes a useful test condition for comparing path-selection policies; it does not establish a general advantage for centralized traffic engineering.

The controller estimates each route's bottleneck from the maximum of its two core-link utilization samples. This is a deliberately simple path score. It has no global traffic matrix, application priorities, predictions, rate controls, or flow-size scheduler. Therefore, published results from larger TE systems provide context for design choices, not performance targets.

## Relation to routing and traffic engineering

OSPF computes shortest paths from distributed link-state information, while traffic-engineering work can centrally optimize IGP weights and leave forwarding decisions to the routers [1], [15], [16]. SmartTE has a different control scope: the controller directly changes OpenFlow rules for one identified flow pair. This makes route changes easy to observe, but does not model the broader demand matrix and operator configuration used in IGP-weight optimization.

Data-center and WAN work also uses centralized information in different ways. Hedera schedules large flows over a multi-rooted fabric [7]; MicroTE uses short-term traffic patterns [11]; B4 and SWAN coordinate WAN traffic, service priorities, rates, and paths [8], [9]. Their topologies, scale, workload information, and control actions differ from this four-switch emulation. SmartTE's port-counter method is a simpler current-load signal. It cannot inherit those papers' measured gains, and those papers do not establish that the chosen B or C rules will help here.

The use of two routes is motivated by multipath designs such as fat-tree and VL2 [5], [6]. The SmartTE topology is only a small diamond: it provides two candidate routes but lacks the path diversity, scale, and traffic diversity of those architectures. It is intended to make controlled path selection and counter evidence inspectable.

## Stability, updates, and overhead

Policy C adds an improvement margin and dwell timer to reduce changes caused by small or short-lived score differences. This addresses route-decision stability, which is distinct from safe rule-update consistency. ECMP disruption analysis motivates recording how often routes change [2]. Consistent-update research studies whether packets experience a consistent configuration while rules are replaced [13]. Hybrid-SDN stability work studies interaction between centralized and distributed routing controls [14]. SmartTE is neither an ECMP implementation nor a hybrid network, and its rule-update sequence does not claim the formal guarantees of consistent-update mechanisms.

The experiment separately measures route changes, packet outcomes, and controller overhead. This separation matters because fewer path changes alone do not prove better service, and low controller CPU in a four-switch Mininet run does not prove scalability. DevoFlow's analysis of fine-grained controller visibility illustrates that telemetry and control messages have costs [10]; SmartTE's OS-Ken polling and per-cycle overhead samples describe only this implementation and workload.

## M5 result alignment

The completed M5 campaign provides a bounded answer to the question. In E1, B averaged 16 successful route changes per 15-second trial and 7.81 Mbps TCP; C at the frozen 15-point/5-second setting averaged three changes and 9.31 Mbps, compared with static's 9.50 Mbps. In E2, B averaged 18.2 and 14.6 changes at 5 and 9 Mbps offered, while C averaged 4 and 2. C's TCP receiver means were 7.44 Mbps at 5 Mbps offered and 9.45 Mbps at 9 Mbps offered; the static A/B references show that Path A congestion, rather than a uniform path-capacity shortage, drove the difference. In E3, B averaged 25 changes and 6.07 Mbps, while C variants averaged 3–7.8 changes and 7.84–9.10 Mbps. These results support a stability/throughput trade-off in this implementation and workload. They do not show that C improves every latency or loss metric: E1 mean RTT for C was close to static, and E2/E3 RTT and loss varied by scenario and C setting.

The E3 sensitivity grid does not identify a winning C setting. For example, the 15-point/10-second setting made fewer changes (3 per trial) but had the lowest C throughput (7.84 Mbps); the 10-point/5-second setting averaged 9.10 Mbps and five changes. The reference setting was frozen before the main run and was not retuned from these outcomes.

E4 applied the same Path A link-down protocol to all three policies, but the path state had already diverged when the failure occurred: B was on B before link-down in all five trials, while C was still on A and moved after the event. Static stayed pinned and produced no TCP receiver result in five trials. This makes E4 useful as a diagnostic policy-outcome record, not a like-for-like recovery-latency ranking. The raw CSV also counts failed switch decisions in its E4 `path_changes` field; the [event audit](../results/processed/m5_campaign_20261011T115819Z/path_change_audit.csv) distinguishes the one successful transition from repeated rejected attempts. The main B/C path-change comparisons use E1–E3.

The data-quality audit found all 110 requested queue configurations verified at 100 packets, no `DUP!` ping replies, and cookie cleanup verified for every controller run. The 105 `ok` rows cover E1–E3 and controller E4; the five `failed` rows are the expected static E4 outages. The confidence intervals are descriptive and should not be described as statistical significance.

## Limitations and defensible conclusion

The emulator uses one host, four OVS switches, one primary TCP pair, one competing UDP pair, two paths, and a small number of repeated trials. Mininet enables testing real host networking and OpenFlow behavior, but performance fidelity is not guaranteed for arbitrary network conditions [12], [17]. WSL2 scheduling, host load, Linux qdiscs, and the stated HTB warning can affect timing. The configured queue limit is verified, but queue occupancy was not continuously measured. Static ARP avoids ARP flooding in the looped topology, which narrows the control traffic represented.

The defensible conclusion is narrow: on this topology and workload, the 15-point/5-second C setting made fewer successful route changes than B in E1–E3, and it retained higher mean TCP throughput in the loaded and burst cases. It did not produce consistently lower RTT or loss, and the declared sensitivity settings show that changing margin and dwell shifts the trade-off. The experiment characterizes this implementation and software environment. It cannot establish a new general TE algorithm, production-scale performance, or superiority across networks.
