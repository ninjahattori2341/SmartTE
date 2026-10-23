# Team contributions

The following division of work has been confirmed by the team. Git history, code, raw evidence, and report material provide supporting evidence; commit authorship alone is not used as the sole basis for attribution.

## Team members

| Student name / ID | Responsibilities | Supporting project evidence | Report role |
|---|---|---|---|
| Aayush Santosh Singh — 25BCE2341 | Controller and algorithm implementation; OpenFlow integration; topology configuration; experiment execution; technical debugging. | `controller/`, `topology/`, `experiments/`, `tests/`, and raw experiment evidence. | Technical implementation review and viva preparation. |
| Ashwin Krishna G — 25BDS0038 | Literature review; comparative experiment-result interpretation and visualization; report preparation and documentation. | `report/`, `analysis/`, processed results, figures, and documentation. | Literature, analysis, and documentation review. |
| Both | System design discussions; testing and validation; final report review; viva preparation. | Shared repository review, raw/processed results, and final report materials. | Final review. |


## Shared interfaces

Each member should understand the full system for the individual viva.

| Area | Primary responsibility | Interface and evidence |
|---|---|---|
| Topology and workload | Aayush | `topology/spec.py`, `topology/datacenter_topology.py`, and queue/path/ARP evidence. |
| Controller and policies | Aayush | `controller/`, `experiments/run_controller_campaign.py`, and unit tests. |
| Data, analysis, and report | Ashwin | `results/DATA_DICTIONARY.md`, `analysis/`, `results/processed/`, and `report/`. |

## Handoff checklist

- [x] Contribution split confirmed by the team.
- [ ] Every result in a report table points to a raw CSV and an analysis command.
- [ ] Every screenshot is original, captured by a team member, and has a caption and source command.
- [ ] Both members can explain the topology, static ARP choice, port-counter formula, B/C decision logic, and limitations.
