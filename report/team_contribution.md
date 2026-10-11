# Team contribution template

**Fill this in with the team. Do not claim work that the named person did not complete.** Link code changes, commits, evidence, and report sections so the division can be checked.

## Team members

| Student name / ID | Concrete tasks completed | Evidence or commit | Report section drafted/reviewed | Confirmation |
|---|---|---|---|---|
| Member 1 | [Fill in] | [Commit, file, or evidence path] | [Section] | [Initial/date] |
| Member 2 | [Fill in] | [Commit, file, or evidence path] | [Section] | [Initial/date] |


## Suggested division with shared interfaces

These are proposed ownership areas, not a record of who did the work. Each member should review the full system for the individual viva.

| Area | Suggested lead | Interface and evidence to hand off |
|---|---|---|
| Topology and workload | Member 1 | `topology/spec.py`, `topology/datacenter_topology.py`, queue/path/ARP evidence; document port numbers and link settings. |
| Controller and policies | Member 2 | `controller/`, `experiments/run_controller_campaign.py`, unit tests; hand off the environment variables, decision log fields, and policy semantics. |
| Data and report | Member 3 | `results/DATA_DICTIONARY.md`, `analysis/`, `report/`; hand off the raw CSV, processing command, chart sources, and literature verification links. |

## Handoff checklist

- [ ] Every result in a report table points to a raw CSV and an analysis command.
- [ ] Every screenshot is original, captured by a team member, and has a caption and source command.
- [ ] All teammates can explain the topology, static ARP choice, port-counter formula, B/C decision logic, and limitations.
- [ ] The final contribution table matches actual commits, evidence, and writing.
