# Screenshot checklist for the student

**NOT VERIFIED:** No screenshots were created or attached in this repository. Capture genuine screenshots yourself from your WSL session; do not use the evidence logs as if they were screenshots. Save the originals in `screenshots/` and keep terminal text readable.

## Before capture

```bash
cd /home/andy2341/smartte
mn -c
```

If the topology cleanup reports leftovers, resolve them before the next live capture. Start the controller and topology only in the specific steps below. Keep the command, prompt, and relevant output visible in each image.

## Required images

| File to save | What to show | Suggested caption |
|---|---|---|
| `01_topology_net_links.png` | Mininet interactive CLI after starting the diamond topology; type `net` and `links`. Show h1–h4, s1–s4, and both routes. | “SmartTE’s four-switch diamond topology with two candidate paths.” |
| `02_static_flow_rules.png` | In a second root terminal, `ovs-ofctl -O OpenFlow13 dump-flows s1` and `dump-flows s2` for a static Path A run. Show the IPv4 source/destination matches and output ports. | “Static OpenFlow rules pin h1–h2 to Path A.” |
| `03_queue_tc.png` | `tc qdisc show dev s1-eth3`, `s2-eth2`, `s1-eth4`, and `s3-eth2`; include `s4-eth3`/`s4-eth4` if the terminal fits. The visible output must include `netem ... limit 100`. | “The configured 100-packet netem limit is visible on core egress interfaces.” |
| `04_static_arp.png` | Mininet CLI output from `h1 ip neigh show` and `h2 ip neigh show`, showing permanent neighbor entries. | “Static ARP entries let IPv4 traffic use secure-mode switches without ARP flooding.” |
| `05_path_counters.png` | Before/after `ovs-ofctl -O OpenFlow13 dump-ports s2` and `dump-ports s3` for a Path A run. Include counter deltas from the matching evidence file or a terminal calculation. | “Path A counters increase while the unused Path B counters remain at zero in this validation.” |
| `06_ping_iperf.png` | Mininet commands/results for `h1 ping -c 20 h2` and a manual `iperf3` TCP run. Show the actual output, not a typed summary. | “Connectivity and TCP throughput on the selected static path.” |
| `07_controller_decision.png` | A controller trial’s `controller_events.jsonl` opened in a terminal, filtered to a switch event, with timestamp, both path scores, reason, and path before/after visible. | “OS-Ken records the measured scores and the FlowMod path change.” |
| `08_analysis_throughput.png` | The generated throughput figure opened at readable size with title, axes, legend, and confidence-interval note visible. | “Measured TCP receiver throughput by experiment and policy.” |
| `09_analysis_stability.png` | B-vs-C path-change plot and/or the C margin/dwell sensitivity plot at readable size. | “Observed route changes and the declared C parameter sensitivity.” |

## Commands for the live topology image

In a WSL terminal with the required privileges:

```bash
cd /home/andy2341/smartte
mn -c
python3 topology/datacenter_topology.py --path A --competing A --queue 100
```

At the `mininet>` prompt, enter:

```text
net
links
```

Leave the CLI open while taking `01_topology_net_links.png`. In a second root terminal, capture the flow, `tc`, and port-counter commands listed in the table. Use `Ctrl-D` at the Mininet prompt, then run `mn -c` after the capture.

## Commands for the controller decision image

The recorded pilot evidence is under `results/raw/m4_pilot_20261011T114337Z/`. To create a fresh run for a live capture (this runs five short variants):

```bash
cd /home/andy2341/smartte
/usr/bin/python3 experiments/run_controller_campaign.py --mode pilot
```

Use the new run folder path printed by the runner, then show a real event line:

```bash
rg -n '"decision": "switch"' results/raw/m4_pilot_<new-run-id>/<scenario>_t01/controller_events.jsonl
```

Replace `<new-run-id>` and `<scenario>` with the path printed by your run. Do not edit the line or crop away its source path. The result may differ from the earlier pilot because it is a new run.

## Commands for analysis screenshots

After the completed M5 analysis:

```bash
cd /home/andy2341/smartte
/home/andy2341/.local/share/smartte/analysis-py310/bin/python analysis/analyse_results.py
/home/andy2341/.local/share/smartte/analysis-py310/bin/python analysis/plot_results.py
```

Open genuine PNG files from `results/processed/<campaign>/figures/`. Include the filename and chart title in the screenshot. Do not paste a generated chart into a terminal screenshot or present it as a live Mininet view.

## Privileged WSL shell and live traffic commands

The topology needs Linux root privileges. Use a WSL shell where `sudo -n true` succeeds, or open a dedicated root shell from Windows Terminal with `wsl.exe -d Ubuntu -u root`. Run the topology command in that privileged shell. If running from a normal shell with working sudo, prefix the command with `sudo`.

For the topology screenshot, use the command above without `--no-cli`; it installs the requested static primary and competing flow rules and opens the Mininet CLI. While it is running:

```text
mininet> h1 ip neigh show
mininet> h2 ip neigh show
mininet> h2 iperf3 -s -p 5201 > /tmp/smartte_h2_iperf3.log 2>&1 &
mininet> h1 iperf3 -c 10.0.0.2 -p 5201 -t 15
mininet> h1 ping -c 20 10.0.0.2
```

For the flow-table image, use `ovs-ofctl -O OpenFlow13 dump-flows s1` and `ovs-ofctl -O OpenFlow13 dump-flows s2` in the privileged shell. The Path A flow rules are IPv4 source/destination matches; the s1 output port for the h1-to-h2 direction is 3, and s2's is 2. For counter evidence, capture `dump-ports s2` and `dump-ports s3` before and after the traffic, then show the counter delta from the same trial. A live demonstration is a new observation; do not label it as an M5 trial.

The controller event search can use standard `grep` if ripgrep (`rg`) is not installed:

```bash
grep -n '"decision": "switch"' results/raw/m4_pilot_<new-run-id>/<scenario>_t01/controller_events.jsonl
```

Use the exact path printed for the new pilot run. If the controller does not switch in a new run, capture a genuine event that explains its decision or use an existing recorded event only with its original evidence path and date.
