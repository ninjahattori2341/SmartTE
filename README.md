# SmartTE: Centralized Traffic Engineering in Data-Center Networks

SmartTE is a **BACSE203 Computer Networks, Fall 2026 (Topic 9)** case study. It compares fixed forwarding with centralized path selection for a TCP flow in a Mininet/Open vSwitch (OVS) diamond topology. It is an experimental emulation, **not** a production deployment.

## Contents

- [Team](#team)
- [Problem and objectives](#problem-and-objectives)
- [Architecture](#architecture)
- [Routing policies](#routing-policies)
- [Environment and setup](#environment-and-setup)
- [Repository layout](#repository-layout)
- [Run, test, and analyse](#run-test-and-analyse)
- [Experimental methodology](#experimental-methodology)
- [Results](#results-and-discussion)
- [Limitations](#limitations)
- [Reproducibility](#reproducibility-and-data-provenance)
- [Contributions](#team-contributions)

## Team

| Member | Registration number |
|---|---|
| Aayush Santosh Singh | 25BCE2341 |
| Ashwin Krishna G | 25BDS0038 |

## Problem and objectives

Congestion can degrade a fixed path even when another equal-capacity path is available. SmartTE tests whether a central OpenFlow controller can use switch-port counters to select a less congested path for one controlled flow.

Objectives are to verify static forwarding, compare Static/B/C policies, measure receiver-side TCP throughput plus RTT/loss and counter utilization, and preserve raw trial evidence for reproducible analysis.

## Architecture

h1-to-h2 is the primary TCP pair. Optional h3-to-h4 UDP traffic is pinned to Path A when contention is required. Forwarding uses OpenFlow 1.3 IPv4 rules and static ARP, not Linux IP routing.

~~~mermaid
flowchart LR
  h1["h1 10.0.0.1"] -->|100 Mbps, 1 ms| s1
  h3["h3 10.0.0.3"] -->|100 Mbps, 1 ms| s1
  s1 -->|Path A: 10 Mbps, 5 ms| s2
  s2 -->|10 Mbps, 5 ms| s4
  s1 -->|Path B: 10 Mbps, 10 ms| s3
  s3 -->|10 Mbps, 10 ms| s4
  s4 -->|100 Mbps, 1 ms| h2["h2 10.0.0.2"]
  s4 -->|100 Mbps, 1 ms| h4["h4 10.0.0.4"]
  c["OS-Ken controller"] -.->|OpenFlow 1.3| s1
  c -.-> s2
  c -.-> s3
  c -.-> s4
~~~

Path A is s1 -> s2 -> s4; Path B is s1 -> s3 -> s4. Fixed ports: s1: 1=h1, 2=h3, 3=s2, 4=s3; s2: 1=s1, 2=s4; s3: 1=s1, 2=s4; s4: 1=h2, 2=h4, 3=s2, 4=s3. Core links default to 10 Mbps with a verified 100-packet queue; access links are 100 Mbps.

Mininet creates the emulation; OVS supplies OpenFlow forwarding and port statistics; OS-Ken manages controller-owned rules. [analysis/](analysis/) converts raw evidence to summaries, quality audits, event audits, and figures.

## Routing policies

| Policy | Behavior |
|---|---|
| **Static** | Keeps the primary flow on its configured path. |
| **B** | At every poll, selects the lower path score; switches only when the improvement exceeds the 0.01 percentage-point tie epsilon. |
| **C / SmartTE** | Applies B, then requires a configured improvement margin and a minimum dwell time since the previous change. |

A score is the maximum core-egress utilization: A uses s1:3 and s2:2; B uses s1:4 and s3:2. The controlled flow is included. The CSV's downstream utilization fields use s2:2 and s3:2.

utilization (%) = delta_tx_bytes x 8 / (monotonic_interval_s x capacity_bps) x 100

Unavailable/reset counters and intervals below 0.5 seconds are rejected. Frozen M5 reference settings were 1,000 ms polling, a 15 percentage-point C margin, and 5,000 ms C dwell time; E3 deliberately varies C settings.

## Environment and setup

The recorded host was WSL2 Ubuntu 24.04.5 on aarch64, with Python 3.12.3, Mininet 2.3.0, OVS 3.3.9, and Git 2.43.0. Network experiments require root. OS-Ken used an isolated Python 3.10.22 environment with OS-Ken 4.2.2 and Eventlet 0.41.2; analysis used another Python 3.10.22 environment. Locked packages are in [requirements/](requirements/).

Install Mininet, OVS, iproute2/tc, iperf3, and Python, start OVS, and verify:

~~~bash
python3 --version
mn --version
ovs-vsctl --version
sudo -n true
~~~

The recorded isolated-environment setup used uv:

~~~bash
uv python install 3.10.22
uv venv --python 3.10.22 ~/.local/share/smartte/os-ken-py310
~/.local/share/smartte/os-ken-py310/bin/python -m pip install -r requirements/controller-osken-py310.lock

uv venv --python 3.10.22 ~/.local/share/smartte/analysis-py310
~/.local/share/smartte/analysis-py310/bin/python -m pip install -r requirements/analysis-py310.lock
~~~

These setup commands are documented from project evidence; they were not re-executed by this README update. Ryu was evaluated but proved incompatible in the recorded environment, so OS-Ken is the supported controller. Mininet may emit an HTB quantum warning on 100 Mbps access links.

## Repository layout

| Path | Purpose |
|---|---|
| [topology/](topology/) | Diamond topology and shared host/path/port specification. |
| [controller/](controller/) | OS-Ken launcher, controller, and B/C policy helpers. |
| [experiments/](experiments/) | Static-baseline and controller-campaign runners. |
| [tests/](tests/) | Policy and runner-helper unit tests. |
| [results/raw/](results/raw/) | Raw CSVs, metadata, and per-trial evidence. |
| [results/processed/](results/processed/) | Summaries, audits, and generated figures. |
| [analysis/](analysis/) | Analysis and plotting scripts. |
| [report/](report/) | Drafts, bibliography, viva guide, and contribution template. |
| [docs/PROGRESS.md](docs/PROGRESS.md) | Milestone evidence and environment notes. |

## Run, test, and analyse

Run privileged network commands from the repository root. Each campaign starts a fresh Mininet network and cleanup uses mn -c.

~~~bash
# Interactive static topology
sudo /usr/bin/python3 topology/datacenter_topology.py --path A --competing off --queue 100

# Static matrix: A/B x 0/5/9 Mbps UDP x five trials
sudo /usr/bin/python3 experiments/run_static_baseline.py \
  --paths A B --competing-rates 0 5 9 --trials 5 --duration 15 --queue 100

# Controller campaigns
sudo /usr/bin/python3 experiments/run_controller_campaign.py --mode static --trials 5
sudo /usr/bin/python3 experiments/run_controller_campaign.py --mode pilot
sudo /usr/bin/python3 experiments/run_controller_campaign.py --mode m5 --trials 5

# Pure Python tests; does not require Mininet
python3 -m unittest discover -s tests -v
~~~

The runner starts OS-Ken with its configured interpreter, so install the controller environment first. Regenerate outputs:

~~~bash
~/.local/share/smartte/analysis-py310/bin/python analysis/analyse_results.py \
  --csv results/raw/m5_campaign_20261011T115819Z.csv
~/.local/share/smartte/analysis-py310/bin/python analysis/plot_results.py \
  --csv results/raw/m5_campaign_20261011T115819Z.csv
~~~

Without --csv, both scripts select the newest completed 110-row M5 campaign and write under results/processed/<CSV-stem>/.

## Experimental methodology

Principal comparisons use 10 Mbps core links, 100 Mbps access links, a 100-packet core queue verified on eight directed core interfaces, static ARP, and IPv6 control-frame suppression. TCP is receiver-side iperf3; RTT/loss comes from ping; utilization comes from OVS/OpenFlow port counters. The first received RTT sample is omitted from RTT summaries as a precaution but remains in the ping-loss denominator.

| Experiment | Design |
|---|---|
| **E1 — baseline** | Static, B, and C without competing UDP; five trials each. |
| **E2 — congestion** | Path-A UDP at 5 or 9 Mbps; Static A/B references and B/C beginning on A; five trials/scenario. |
| **E3 — bursty/sensitivity** | Three 5-second, 9 Mbps Path-A UDP bursts from seconds 5, 15, and 25 of a 30-second TCP run; B/C variants plus static references. |
| **E4 — link failure** | s2-s4 is disabled one second into a 15-second TCP run; all policies begin on A. |

M5 has 110 planned rows: E1 15, E2 40, E3 40, E4 15. A trial preserves its manifest, iperf/ping output, queue audit, counters, controller events, and cleanup checks. Missing required measurements remain in the raw CSV with a status and note.

## Results and discussion

The completed committed campaign is **m5_campaign_20261011T115819Z**: 110 recorded/planned rows, 105 ok, 5 failed, 0 aborted, and 0 excluded. Generic processed summaries include only ok rows; E4 retains all outcomes. The 95% Student-t intervals are descriptive—no hypothesis-significance test was performed.

- E2, 5 Mbps competing UDP: mean TCP receiver throughput was 5.946 Mbps for Static-on-A versus 9.465 Mbps for Static-on-B (five trials each), demonstrating the intended contention contrast.
- E1: B averaged 16 successful path changes/trial, while reference C averaged 3. This is an observed behavior of this implementation, not a general result for centralized TE.
- E4: all five Static trials failed after the Path-A outage and have no TCP throughput measurement. B and C each successfully rerouted once in every trial; their mean counter-confirmed recovery times were 0.193 s and 1.005 s, respectively. The event audit confirms that neither policy had successfully changed before the failure.

The raw path_changes field can count rejected requests for an unavailable path. Use [path_change_audit.csv](results/processed/m5_campaign_20261011T115819Z/path_change_audit.csv) for successful transitions. Complete values, CIs, quality audit, E4 outcomes, and figures are in [results/processed/m5_campaign_20261011T115819Z/](results/processed/m5_campaign_20261011T115819Z/). These are archived measurements, not live telemetry.

## Limitations

- A four-host/four-switch emulation with one TCP pair and one optional UDP pair does not establish data-center-scale behavior.
- Emulated queues, time, and host resources differ from hardware networks and production control planes.
- WSL2 requires privileged execution and produced the recorded access-link HTB warning; Ryu compatibility was inadequate in this environment.
- E4 is a single-link diagnostic, not a broad resilience evaluation. It also records rejected route-selection attempts after a failed path becomes unavailable, so decisions must be separated from successful transitions.
- Queue occupancy and packet-level transient behavior were not continuously measured; missing data was retained rather than imputed.

## Reproducibility and data provenance

Raw evidence is intentionally retained. [metadata.json](results/raw/m5_campaign_20261011T115819Z/metadata.json) records campaign commit 58acacd120a1b8b85b81d8a46c1f273479d18942 and git_dirty: true. Exact reproduction from that commit alone is therefore not claimed: uncommitted controller/campaign state existed at capture time.

The source CSV is [results/raw/m5_campaign_20261011T115819Z.csv](results/raw/m5_campaign_20261011T115819Z.csv); per-trial evidence is in the sibling directory. [analysis_metadata.json](results/processed/m5_campaign_20261011T115819Z/analysis_metadata.json) records its SHA-256, row counts, and aggregation rules. [results/DATA_DICTIONARY.md](results/DATA_DICTIONARY.md) defines the fields and null rules. Do not overwrite raw data when rerunning; create a new campaign.

## Team contributions

The team confirms the following division of work. Git history remains supporting evidence, rather than the sole basis for attribution.

| Member | Responsibilities |
|---|---|
| Aayush Santosh Singh — 25BCE2341 | Controller/algorithm implementation, OpenFlow integration, topology configuration, experiment execution, and technical debugging. |
| Ashwin Krishna G — 25BDS0038 | Literature review, comparative result interpretation/visualization, report preparation, and documentation. |
| Both | System design, testing/validation, final report review, and viva preparation. |

The detailed contribution record is maintained in [report/team_contribution.md](report/team_contribution.md).

## Academic references and related work

[report/references.md](report/references.md) contains the verified bibliography, including OpenFlow, Mininet, Hedera, MicroTE, and network-update literature. The Part A/B/C drafts are supporting course material; this README does not replace them.

## Academic-use statement

This is an academic case study. Retain provenance, attribute sources, and follow course rules on authorship, similarity, and AI-use declarations.
