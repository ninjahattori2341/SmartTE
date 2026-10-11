# SmartTE: congestion-aware path selection in a data-center network

SmartTE compares fixed OpenFlow paths with two centralized policies in a small Mininet diamond. The primary TCP pair is h1–h2. The optional competing UDP pair is h3–h4. Path A is s1–s2–s4; Path B is s1–s3–s4. The controller polls switch port counters and changes only the primary pair’s forwarding rules.

## Project status

- M2 static path, contention, and queue evidence: complete; see [progress](docs/PROGRESS.md).
- M3 OS-Ken static-rule reproduction: complete.
- M4 B/C logic, unit tests, and parameter pilot: complete.
- M5 110-row campaign and its analysis: in progress. Use the completed campaign path and actual status summary documented in `docs/PROGRESS.md` before citing experiment conclusions.
- Student screenshots and final rewriting: still the student’s work; see the [screenshot checklist](report/screenshot_checklist.md) and rewrite the Part A/B/C drafts in your own words.

## Verified environment

The recorded host is WSL2 Ubuntu 24.04.5 on aarch64, Python 3.12.3, Mininet 2.3.0, Open vSwitch 3.3.9, and Git 2.43.0. Mininet runs with root privileges. The experiment scripts use `/usr/bin/python3` for Mininet; OS-Ken runs in a separate Python 3.10.22 virtual environment. Analysis uses its own Python 3.10.22 environment. System Python was not used for package installation.

## Installation

Install or enable Mininet, Open vSwitch, `iproute2`/`tc`, `iperf3`, and Python 3.12 on WSL2 Ubuntu. Start Open vSwitch, then check the environment:

```bash
python3 --version
mn --version
ovs-vsctl --version
sudo -n true
```

If passwordless sudo is unavailable, run the privileged commands from a WSL root shell. From Windows PowerShell, this project used `wsl.exe -d Ubuntu -u root -- ...`.

The controller was installed only in an isolated Python environment. To reproduce the layout on a machine with `uv`:

```bash
uv python install 3.10.22
uv venv --python 3.10.22 ~/.local/share/smartte/os-ken-py310
~/.local/share/smartte/os-ken-py310/bin/python -m pip install -r requirements/controller-osken-py310.lock
```

The environment used OS-Ken 4.2.2, Python 3.10.22, Eventlet 0.41.2, and OpenFlow 1.3. Ryu was tried first but failed to install through its legacy setuptools entry point; a source attempt then failed at runtime on Eventlet compatibility. The project repository identifies OS-Ken as the maintained alternative. See the exact install and runtime evidence in `logs/m3_verification/ryu_install.txt`, `ryu_compatibility.txt`, and `osken_spike_eventlet/`.

Install analysis packages in a separate isolated environment:

```bash
uv venv --python 3.10.22 ~/.local/share/smartte/analysis-py310
~/.local/share/smartte/analysis-py310/bin/python -m pip install -r requirements/analysis-py310.lock
```

Do not install these packages into the system Python.

## Topology and forwarding

| Item | Setting |
|---|---|
| Hosts | h1 `10.0.0.1`, h2 `10.0.0.2`, h3 `10.0.0.3`, h4 `10.0.0.4` |
| Switches | s1 ingress, s2 Path A middle, s3 Path B middle, s4 egress |
| Access links | 100 Mbps, 1 ms |
| Path A | 10 Mbps per core link, 5 ms per link |
| Path B | 10 Mbps per core link, 10 ms per link |
| Primary pair | h1–h2; OpenFlow 1.3 rules match IPv4 source and destination |
| Competing pair | h3–h4, pinned to Path A in the experiments that use it |
| Core queue | 100 packets in the primary comparisons; verified from `tc` on all eight directed core interfaces |
| ARP | Mininet static ARP; no ARP flood rules are installed |

The topology and controller import port assignments and path rules from `topology/spec.py`. Forwarding is OpenFlow flow-table forwarding, not Linux IP routing. Static ARP is deliberate: the switches run in secure mode and flooding ARP into the s1–s2–s4–s3 cycle could create a broadcast storm.

## Policies

- **Static:** keep the primary pair on its configured path.
- **B:** every poll, choose the path with the lower maximum core-link utilization; switch when it is measurably lower than the current path.
- **C:** B plus a switching margin and a minimum dwell time. The M4 pilot freezes the reference at 1,000 ms polling, a 15-percentage-point margin, and 5,000 ms dwell. E3 contains the declared sensitivity settings.

For controller decisions, Path A’s score is the greater utilization of s1 port 3 and s2 port 2; Path B’s score is the greater utilization of s1 port 4 and s3 port 2. These OpenFlow `tx_bytes` counters include the controlled h1–h2 traffic. The CSV’s utilization fields use the downstream egress ports s2:2 and s3:2. Utilization is `(delta_tx_bytes * 8) / (actual_monotonic_interval_s * configured_capacity_bps) * 100`, never an iperf-derived estimate.

## Running experiments

Run network experiments as root, from the repository root. Each trial starts a fresh Mininet network and retains its raw output. `mn -c` is used during cleanup.

```bash
# Static topology, interactive Mininet CLI
python3 topology/datacenter_topology.py --path A --competing A --queue 100

# M2 static matrix (30 planned rows, expected (calculated))
/usr/bin/python3 experiments/run_static_baseline.py --paths A B --competing-rates 0 5 9 --trials 5 --duration 15 --queue 100

# M3 controller-installed static reproduction (10 planned rows, expected (calculated))
/usr/bin/python3 experiments/run_controller_campaign.py --mode static --trials 5

# M4 one-trial-per-variant pilot (5 planned rows, expected (calculated))
/usr/bin/python3 experiments/run_controller_campaign.py --mode pilot

# M5 E1–E4 campaign (110 planned rows, expected (calculated)); allow about 45 minutes
/usr/bin/python3 experiments/run_controller_campaign.py --mode m5 --trials 5
```

The campaign prints the CSV and raw-trial directory at completion. Raw CSVs are written to `results/raw/`; each controller trial has a manifest, ping/iperf output, queue captures, counter records, controller event logs, cookie-cleanup checks, and `controller_overhead.csv`. The shared columns and null rules are in [the data dictionary](results/DATA_DICTIONARY.md).

## Analysis

After a campaign has a completed metadata record, run the reproducible summaries and figures with the analysis environment:

```bash
~/.local/share/smartte/analysis-py310/bin/python analysis/analyse_results.py --csv results/raw/m5_campaign_<timestamp>.csv
~/.local/share/smartte/analysis-py310/bin/python analysis/plot_results.py --csv results/raw/m5_campaign_<timestamp>.csv
```

Replace `<timestamp>` with the actual completed CSV name. Without `--csv`, the scripts choose the newest campaign whose metadata says it completed all 110 planned rows. Outputs are written to `results/processed/<campaign>/`, with publication-sized PNG and PDF figures. Confidence intervals use a two-sided Student-t interval with sample standard deviation; they are descriptive, and the project does not claim statistical significance without a specified test.

## Reproduction and troubleshooting

- Clear stale Mininet state with `mn -c` before and after a run.
- If port 6653 is occupied, stop the process using it before launching a controller. The campaign checks this port before each trial.
- If the controller fails before four switch connections, inspect `controller_process.log` in the trial folder and check that OS-Ken uses the isolated Python 3.10 environment.
- If Eventlet prints its deprecation warning, the warning is recorded; OS-Ken still starts in the verified environment. The launcher selects the Eventlet hub before the app manager starts.
- If a queue is not visible as 100 on all eight core interfaces, do not treat the trial as verified. Inspect its saved `tc` output; the runner marks an unverified queue trial excluded.
- Mininet can print an HTB quantum warning for 100 Mbps access links. The recorded trials completed; the warning and separate access queues are discussed in `docs/PROGRESS.md`.
- M5 rows with a non-`ok` status remain in the CSV. Read the notes and raw files before excluding or interpreting one.

## Report material

- [Verified bibliography](report/references.md) and [literature notes](report/literature_notes.md)
- [Part A draft](report/part_a_draft.md), [Part B simulation draft](report/part_b_simulation.md), and [Part C discussion draft](report/part_c_alignment.md)
- [Viva guide](report/viva_guide.md), [screenshot checklist](report/screenshot_checklist.md), and [team contribution template](report/team_contribution.md)

The Part A/B/C files are source drafts marked for student rewriting. The screenshot checklist explicitly records that no screenshots are included yet.

## Repository map

| Path | Purpose |
|---|---|
| `topology/` | Shared path/port spec and Mininet topology |
| `controller/` | Static, B, and C rules, OS-Ken launcher, telemetry and cleanup |
| `experiments/` | Static baseline and controller campaign runners |
| `tests/` | Pure Python decision and runner-helper tests |
| `results/raw/` | Per-run CSVs and per-trial raw evidence |
| `results/processed/` | Generated summaries, quality tables, and charts |
| `analysis/` | Reproducible CSV analysis and plot scripts |
| `report/` | Verified bibliography, literature notes, draft report material, viva and screenshot guides |
| `docs/PROGRESS.md` | Milestone status, evidence links, and open risks |

## Suggested division for three teammates

Use [the contribution template](report/team_contribution.md) to record actual ownership. A useful split is topology/queue/path evidence, controller/policy/tests, and analysis/literature/report preparation. Keep interfaces explicit: `topology/spec.py` defines paths and ports, the stable CSV schema is defined in `results/DATA_DICTIONARY.md`, and the controller policy is selected through its configuration fields. Everyone should understand the whole system for the individual viva.

## Student completion tasks

Capture the original screenshots listed in [the screenshot checklist](report/screenshot_checklist.md); rewrite the Part A, Part B, and Part C drafts in your own words; confirm the course’s similarity and AI-use declaration requirements; fill in actual team contributions; and review all report conclusions against the final raw CSV and figures.
