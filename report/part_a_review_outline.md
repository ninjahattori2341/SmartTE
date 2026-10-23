# Part A review structure

This structure summarizes the scope and organization of the compiled Part A review. The review is four to six pages excluding references and uses the verified sources in [references.md](references.md).

## Review title

Centralized Traffic Engineering in Data-Center Networks: Path Selection, Stability, and Measurement

## Research question and central argument

- **Question:** Does a switching margin plus a minimum dwell time reduce unnecessary path changes for a simple congestion-aware controller, while preserving useful throughput and latency in a controlled two-path emulation?
- **Scope statement:** This is a small implementation study, not a new traffic-engineering algorithm. Prior work already covers centralized WAN scheduling, data-center flow scheduling, multipath load balancing, safe updates, and routing stability.
- **Thesis to refine after reviewing evidence:** Central control makes network-wide observations actionable, but its benefit depends on the workload model, telemetry cost, and update behavior. Stability mechanisms should therefore be evaluated alongside throughput and delay.

## Suggested structure and approximate length

1. **Introduction (½ page):** Define traffic engineering and motivate multipath data-center fabrics. Contrast the question SmartTE can test with production-scale claims it cannot test. State the research question.
2. **Distributed routing and weight-based TE (¾ page):** Use OSPF/RFC 2328 and Fortz et al. to explain distributed shortest-path forwarding and centralized/offline weight optimization [1], [15], [16]. Explain why centralized control does not automatically mean centralized packet forwarding.
3. **Centralized WAN TE (¾ page):** Compare B4 and SWAN [8], [9]. Discuss application demand, priorities/rate control, path scheduling, update safety, and why production scale differs from the two-path experiment.
4. **Data-center multipath and flow scheduling (1 page):** Establish topology/path multiplicity using fat-tree and VL2 [5], [6]. Contrast Hedera's global scheduling and MicroTE's traffic predictability with a simple periodic port-counter score [7], [11]. Place DevoFlow's controller-visibility tradeoff here or in Section 6 [10].
5. **Stability and safe updates (¾ page):** Explain ECMP disruption [2], update consistency [13], and hybrid routing stability [14]. Separate transient rule-installation correctness from repeated algorithmic route changes.
6. **Controller overhead and evaluation method (½ page):** Use DevoFlow and Mininet studies [10], [12], [17]. Explain why telemetry rate and emulation fidelity matter.
7. **Synthesis and research gap (½ page):** Compare what the papers measure, their common assumptions, tensions, limitations, and the exact bounded SmartTE hypothesis. Do not claim that hysteresis or congestion-aware routing is new.

## Comparison questions to answer in the final prose

- Does each design optimize link utilization, application demand, flow completion, or another objective?
- Is the decision per packet, flow, traffic class, path, or link weight?
- What information is available: topology, demand matrix, per-flow counters, port counters, or predictions?
- Are results from proof/analysis, simulation, emulation, testbed, or production deployment?
- How does each paper account for controller overhead and route-update transients?
- Which findings are comparable to SmartTE, and which are only motivation because the scales and workloads differ?

## Evidence and writing checklist

- Cite only sources in [references.md](references.md); [18] is background and is not peer reviewed.
- At least 8 peer-reviewed papers or original standards are already verified; cite at least 15 entries across the review and references.
- Attribute every numerical result to its paper and evaluation method. Do not copy any paper's result into the SmartTE results section.
- Preserve the negative-result option. The hypothesis is a question, not a conclusion.
- Keep the final paper within the requested 4–6 pages and check the VIT citation, similarity, and AI-use requirements yourself.
