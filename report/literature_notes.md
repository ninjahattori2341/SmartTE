# Literature notes: centralized traffic engineering and SmartTE

**Evidence status: VERIFIED BY INSPECTION.** These notes summarize the linked papers and standards listed in [references.md](references.md). They describe published work, not our Mininet results. Unless a note says otherwise, limitations below concern what that cited work studies; SmartTE-specific limitations are kept in [Part B](part_b_simulation.md).

## Centralized and distributed control

### OSPF and traffic engineering with IGP weights — [1], [15], [16]

- **Problem and approach:** OSPF is a distributed link-state IGP: routers exchange link-state information and compute shortest paths from configured link weights. Fortz and Thorup formulate weight selection as a traffic-engineering problem using a network topology and projected demand; Fortz, Rexford, and Thorup later describe adjusting OSPF/IS-IS weights using network-wide traffic and topology information while keeping the deployed IGP forwarding model.
- **Method and supported point:** RFC 2328 specifies OSPFv2. The INFOCOM study evaluates OSPF weight optimization on a projected backbone demand, while the Communications Magazine article reviews practical weight-adaptation techniques. Together they show that centralized/offline optimization and distributed packet forwarding can coexist; “centralized” does not require replacing every router’s forwarding plane.
- **Limits and relevance:** These methods work at the network-wide demand/weight level, not by moving one TCP pair between two paths every second. They are useful context for SmartTE’s difference from ordinary shortest-path routing, but are not a direct performance comparison.

### SDN architecture and OpenFlow — [3], [4], [18]

- RFC 7426 gives SDN terminology and separates application, control, management, and forwarding concerns. The ONF OpenFlow 1.3 specification defines the controller-switch protocol and flow-table operations used by this implementation.
- The OpenFlow CCR article is useful historical context for flow-table control, but its own front matter labels it a non-peer-reviewed editorial note. It is deliberately not counted toward the peer-reviewed-reference minimum.
- **SmartTE distinction:** The controller writes OpenFlow rules matching IPv4 source and destination fields and output ports. It does not configure Linux IP routes; forwarding in these experiments is OpenFlow flow-table forwarding. Static ARP entries are provided by Mininet, and no ARP flood rule is installed.

## WAN traffic engineering

### B4 — [8]

- **Problem and approach:** B4 is Google’s private WAN connecting data centers. The paper describes centrally controlled traffic engineering, edge demand measurement/rate limiting, application priorities, and splitting traffic over multiple paths.
- **Method and supported point:** The authors report experience from a production deployment over three years. Its design is enabled by substantial control of both the applications and WAN edge, and by elastic bulk-transfer demand. The paper reports high average link utilization under that operating model.
- **Limits and relevance:** This is production WAN engineering across many sites, services, and links. SmartTE uses one pair of flows and two 10 Mbps paths in a single-host emulation, so B4 motivates central coordination but does not predict SmartTE’s throughput or validate this controller.

### SWAN — [9]

- **Problem and approach:** SWAN centrally controls how much inter-datacenter traffic services send and updates forwarding to fit current demand. Its update method uses spare link and table capacity to avoid congestion during asynchronous switch updates.
- **Method and supported point:** The paper reports a testbed prototype and data-driven simulations of two production networks; it reports carrying 60% more traffic than the practice used as its comparison.
- **Limits and relevance:** SWAN combines scheduling, rate control, and safe network-wide updates. SmartTE only moves one flow between two paths and does not allocate service rates or reserve update capacity. The published 60% result is not comparable to our experiment.

## Data-center topology, multipath, and congestion estimation

### Fat-tree and VL2 — [5], [6]

- **Problem and approach:** Al-Fares et al. use commodity switches and a fat-tree design to build a scalable data-center fabric with many paths. VL2 aims to provide flexible layer-2 semantics at data-center scale and uses Valiant Load Balancing to spread traffic across paths.
- **Method and supported point:** These are architecture papers; they reason about multi-stage commodity fabrics and routing/load-balancing methods, rather than a two-route controller experiment.
- **Limits and relevance:** They explain why multipath capacity matters and why a diamond is a teaching-scale simplification. Their scale and traffic diversity are far beyond this four-switch topology.

### Hedera — [7]

- **Problem and approach:** Hedera addresses collisions from static per-flow multipath hashing in multi-rooted data-center fabrics. It uses a centralized scheduler with a global view to identify and schedule large flows over available paths.
- **Method and supported finding:** The authors describe a commodity-switch implementation and evaluate an 8,192-host data-center simulation; the paper reports simulated bisection bandwidth at 96% of optimal and up to 113% better than the static balancing methods it compares.
- **Limits and relevance:** Those figures are simulation results for Hedera’s workload and topology. SmartTE has only one primary flow and two known routes; its experiment measures TCP, ping, and port counters instead of global flow scheduling. Hedera supports the motivation for path-aware decisions, not a numerical baseline for SmartTE.

### MicroTE — [11]

- **Problem and approach:** MicroTE studies fine-grained data-center traffic engineering under changing but partly predictable traffic matrices. It combines short-term prediction with coordinated route decisions.
- **Method and supported finding:** Its evaluations use data-center traces and synthetic traffic; the paper reports that compared techniques can fall 15–20% below an optimal solution and that MicroTE approaches the optimum in its evaluations.
- **Limits and relevance:** MicroTE depends on a broader traffic matrix and predictability absent from SmartTE. It is relevant to the value and cost of traffic knowledge, but its optimality gap does not transfer to our topology.

### ECMP and route disruption — [2]

- RFC 2992 analyzes hash-threshold ECMP and explicitly treats disruption as the fraction of flows whose path changes when next hops change. It notes that stable paths matter to transports such as TCP.
- This is an analysis of a particular ECMP selection method, not a congestion-aware controller or a hysteresis/dwell-time evaluation. It provides a precise reason to record path changes in SmartTE.

## Stability, path updates, and controller overhead

### Consistent network updates — [13]

- Reitblatt et al. formalize per-packet and per-flow consistency when changing network configurations and describe mechanisms for applying updates with OpenFlow.
- The paper addresses transient correctness while rules change, not repeated congestion-driven switching. SmartTE sends downstream forwarding rules before ingress rules and removes only its cookie-owned old rules; it does not claim the paper’s formal consistency guarantee or use its versioned per-packet mechanism.

### Routing stability in hybrid SDNs — [14]

- **Problem and approach:** Tseng et al. study route instability when distributed routing and centralized SDN controls coexist and make conflicting route adjustments. They define a stability objective and propose per-priority global, greedy, and local-search approaches.
- **Method and supported point:** Their controller design is evaluated by simulation with Abilene and tier-1 backbone data. The paper supports the general concern that centralized control can produce repeated route changes if the control rules are inconsistent.
- **Limits and relevance:** This is hybrid routing at backbone scale, not a two-path SDN-only controller. It does not test SmartTE’s percentage-point margin and dwell rule, so it motivates measuring stability without proving that this particular rule will help.

### DevoFlow and controller cost — [10]

- **Problem and approach:** DevoFlow argues that fine-grained controller visibility and frequent statistics/flow events can impose costs. It keeps most microflow decisions in the switches and directs controller attention toward significant flows.
- **Method and supported finding:** Its simulations report fewer flow-table entries and controller messages than fine-grained alternatives for its workloads (10–53× fewer average switch entries and 10–42× fewer control messages in the paper’s evaluation).
- **Limits and relevance:** DevoFlow changes the OpenFlow control model and evaluates simulated networks. SmartTE uses OS-Ken polling at 1-second intervals and records per-cycle process CPU time, round-trip polling time, and FlowMod counts; these measurements describe this implementation only and do not establish large-network scalability.

## Emulation and reproducibility

### Mininet — [12], [17]

- Lantz et al. describe Mininet as a lightweight, interactive environment for prototyping networks using real applications and kernel/network code in process and namespace isolation.
- Handigol et al. test container-based emulation with Mininet-HiFi and reproduce selected published experiments. They also state that performance fidelity is not generally proven, and discuss resource isolation and monitoring as necessary to improve repeatability.
- **Limits and relevance:** Mininet makes it practical to test real OpenFlow/OVS behavior, but a single WSL2 host does not emulate backbone scale, hardware forwarding, physical link timing, or controller distribution. The citations justify using emulation while requiring a careful limits section; they do not validate every measured value in this workspace.

## Comparison matrix

| Work | Control/decision scope | Evidence method | What it supports here | Key difference from SmartTE |
|---|---|---|---|---|
| OSPF / Fortz et al. [1], [15], [16] | Link-state shortest paths; centrally optimized IGP weights | Protocol standard, backbone optimization and operational analysis | Distributed routing can be traffic-engineered from a network-wide view | Weight setting and demand matrices rather than per-poll flow moves |
| B4 / SWAN [8], [9] | WAN-wide application scheduling, rates, priorities, and paths | Production deployment; prototype plus trace/data-driven simulation | Central coordination can use global demand and capacity information | Many sites/services and rate controls vs. two paths and one primary flow |
| Fat-tree / VL2 [5], [6] | Fabric architecture and multipath distribution | Design and data-center evaluation | Multiple paths are a source of aggregate capacity | Much larger fabric and different traffic-distribution design |
| Hedera / MicroTE [7], [11] | Large-flow scheduling / traffic-matrix prediction | Simulation, traces, and prototype evaluation | Static hashing or limited information can leave capacity unused | Broader flow knowledge than the live port-counter score here |
| RFC 2992 / Reitblatt et al. [2], [13] | ECMP path disruption / safe configuration transition | Analysis and formal update mechanisms | Path changes and update correctness deserve separate measurement | Neither is this congestion controller’s margin/dwell algorithm |
| Tseng et al. [14] | Stability across hybrid control loops | Realistic network-data simulations | Conflicting control actions can cause repeated route switching | Hybrid backbone design rather than this SDN-only diamond |
| DevoFlow [10] | Local vs. centralized flow handling and telemetry overhead | Simulation | Polling and controller visibility have costs | Different OpenFlow model and scale |
| Mininet studies [12], [17] | Emulation and reproducibility | Single-host emulation and reproduced experiments | Real code and protocol stacks can be exercised repeatably | Emulation fidelity is workload- and resource-dependent |

## Synthesis: agreements, tensions, and bounded research question

- **Agreement:** Across WAN and data-center work, a global view can help coordinate paths or rates when the workload, edge, and network are observable [7]–[11]. That does not mean all controllers use the same telemetry or solve the same optimization problem.
- **Tension:** More frequent centralized observation can improve responsiveness, but controller visibility and updates consume resources [10], and changing routes can disturb transport flows [2], [13], [14]. Safe installation and stable decision-making are related but distinct concerns.
- **Distributed comparison:** OSPF/IS-IS engineering changes link weights while leaving routers to compute and forward shortest paths [1], [15], [16]. OpenFlow exposes flow-table control through a controller-switch interface [3], [4]. SmartTE is a small centralized path-selection exercise, not a replacement design for production IGPs.
- **Defensible scope:** The reviewed sources cover traffic engineering, multipath scheduling, update consistency, route disruption, and controller overhead. This study tests a narrow question in one controlled emulation: whether a switching margin plus a minimum dwell reduces unnecessary route changes for a periodic maximum-utilization score that includes the controlled flow, while retaining acceptable TCP throughput and ping latency. The reviewed set does not establish that this exact configuration is new, and no novelty claim is made.
- **Evidence boundary:** Literature findings above come from the cited papers’ own stated evaluations. SmartTE’s results must be drawn only from the raw CSVs and analysis scripts. Differences in scale, workloads, traffic matrices, hardware, and measurement method prevent direct numeric comparison.
