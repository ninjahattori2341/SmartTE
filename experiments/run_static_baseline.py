#!/usr/bin/env python3
"""
SmartTE - Static Baseline Experiment Runner
============================================

This script automates static routing baseline measurements for the SmartTE project.
It systematically evaluates TCP throughput and loaded latency under different
competing traffic loads across Path A and Path B.

Matrix of Configurations:
  - Primary path (h1 -> h2): Path A or Path B
  - Competing traffic (h3 -> h4 over Path A): 0 Mbps, 5 Mbps, 9 Mbps (UDP)
  - Repetitions: 5 trials per configuration (default)

Metrics Collected per Trial:
  - Receiver TCP throughput (Mbps) via iperf3 JSON (-J)
  - TCP retransmissions
  - Unloaded / loaded RTT (min, avg, max, mdev in ms) via concurrent ICMP pings (first packet discarded)
  - Ping packet loss percentage
  - Competing flow sent throughput and packet loss percentage

All raw outputs (iperf3 JSON, ping raw text) and a structured CSV are saved under
results/raw/ with full metadata for reproducible evaluation.
"""

import argparse
import csv
import datetime
import json
import logging
import math
import os
import re
import subprocess
import sys
import time
from types import SimpleNamespace

# Ensure project root is in python module search path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from topology.datacenter_topology import (
    build_topology,
    install_flows,
    cleanup_previous,
    DEFAULT_DELAY_ACCESS,
    DEFAULT_DELAY_A,
    DEFAULT_DELAY_B,
    DEFAULT_QUEUE,
    PATH_A_BW,
    PATH_B_BW,
    ACCESS_BW
)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
log = logging.getLogger('smartte-runner')


def get_git_commit():
    """Retrieve current git commit hash for provenance tracking."""
    try:
        git_dir = os.path.join(PROJECT_ROOT, '.git')
        head_file = os.path.join(git_dir, 'HEAD')
        if os.path.exists(head_file):
            with open(head_file) as f:
                ref = f.read().strip()
            if ref.startswith('ref: '):
                ref_path = os.path.join(git_dir, ref[5:])
                if os.path.exists(ref_path):
                    with open(ref_path) as f:
                        return f.read().strip()
            return ref
    except Exception:
        pass
    return 'UNKNOWN'


def parse_ping_output(ping_text):
    """
    Parse ping output to extract packet loss and RTT statistics.
    Per experimental methodology, the FIRST ping packet is discarded to eliminate
    cold-cache/initial queue setup artifacts.
    """
    loss_match = re.search(r'([\d\.]+)%\s*packet loss', ping_text)
    ping_loss_pct = float(loss_match.group(1)) if loss_match else 0.0

    # Extract all ping round trip samples
    rtt_samples = [float(m) for m in re.findall(r'time=([\d\.]+)\s*ms', ping_text)]

    if len(rtt_samples) > 1:
        # Discard the first packet
        valid_samples = rtt_samples[1:]
    elif len(rtt_samples) == 1:
        valid_samples = rtt_samples
    else:
        valid_samples = []

    if valid_samples:
        rtt_min = min(valid_samples)
        rtt_max = max(valid_samples)
        rtt_avg = sum(valid_samples) / len(valid_samples)
        variance = sum((x - rtt_avg) ** 2 for x in valid_samples) / len(valid_samples)
        rtt_mdev = math.sqrt(variance)
    else:
        rtt_min = rtt_avg = rtt_max = rtt_mdev = 0.0

    return {
        'ping_loss_pct': ping_loss_pct,
        'rtt_min_ms': round(rtt_min, 3),
        'rtt_avg_ms': round(rtt_avg, 3),
        'rtt_max_ms': round(rtt_max, 3),
        'rtt_mdev_ms': round(rtt_mdev, 3),
        'samples_count': len(valid_samples)
    }


def run_trial(net, path, competing_mbps, trial_idx, duration, raw_dir, queue_pkts):
    """
    Execute a single trial under a specific path and competing traffic load.
    Returns a dictionary of structured metrics.
    """
    timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    trial_tag = f"{path}_c{competing_mbps}_t{trial_idx}"
    log.info("--- Starting Trial [%s]: Path=%s, Competing=%d Mbps (Duration=%ds) ---",
             trial_tag, path, competing_mbps, duration)

    h1 = net['h1']
    h2 = net['h2']
    h3 = net['h3']
    h4 = net['h4']

    # 1. Start iperf3 servers on receivers
    h2.cmd('iperf3 -s -p 5201 -D')
    if competing_mbps > 0:
        h4.cmd('iperf3 -s -p 5202 -D')
    time.sleep(1)

    # Temporary files for raw process output inside Mininet
    competing_raw_file = f"/tmp/competing_{trial_tag}.json"
    ping_raw_file = f"/tmp/ping_{trial_tag}.txt"

    # 2. Start competing UDP flow if configured
    if competing_mbps > 0:
        log.info("Starting competing UDP flow on h3 -> h4 (%d Mbps)...", competing_mbps)
        # Run competing UDP with extra duration to ensure continuous load during primary TCP transfer
        comp_cmd = f"iperf3 -c 10.0.0.4 -p 5202 -u -b {competing_mbps}M -t {duration + 6} -J > {competing_raw_file} &"
        h3.cmd(comp_cmd)
        log.info("Waiting 2s for competing flow to ramp up...")
        time.sleep(2)

    # 3. Launch concurrent ping at 0.2s interval
    # Number of ping packets: duration / 0.2
    ping_count = int(duration / 0.2)
    log.info("Starting concurrent ping h1 -> h2 (%d packets, 0.2s interval)...", ping_count)
    h1.cmd(f"ping -i 0.2 -c {ping_count} 10.0.0.2 > {ping_raw_file} &")

    # 4. Run primary TCP iperf3 test for specified duration
    log.info("Running primary TCP flow h1 -> h2 for %d seconds...", duration)
    tcp_json_str = h1.cmd(f"iperf3 -c 10.0.0.2 -p 5201 -t {duration} -J")

    # Wait briefly for background ping to finalize
    time.sleep(1)

    # 5. Read back raw ping output
    ping_text = h1.cmd(f"cat {ping_raw_file}")

    # Read back competing output if present
    competing_json_str = ""
    if competing_mbps > 0:
        competing_json_str = h3.cmd(f"cat {competing_raw_file}")

    # 6. Terminate all test processes on hosts
    for h in [h1, h2, h3, h4]:
        h.cmd('killall -9 iperf3 ping 2>/dev/null')
    # Clean temporary files
    h1.cmd(f"rm -f {ping_raw_file} {competing_raw_file} 2>/dev/null")

    # Save raw outputs to experiment directory
    raw_tcp_path = os.path.join(raw_dir, f"{trial_tag}_iperf3.json")
    with open(raw_tcp_path, 'w') as f:
        f.write(tcp_json_str)

    raw_ping_path = os.path.join(raw_dir, f"{trial_tag}_ping.txt")
    with open(raw_ping_path, 'w') as f:
        f.write(ping_text)

    if competing_mbps > 0 and competing_json_str:
        raw_comp_path = os.path.join(raw_dir, f"{trial_tag}_competing.json")
        with open(raw_comp_path, 'w') as f:
            f.write(competing_json_str)

    # 7. Parse metrics
    # Parse TCP metrics
    tcp_throughput_mbps = 0.0
    tcp_retransmits = 0
    try:
        tcp_data = json.loads(tcp_json_str)
        if 'end' in tcp_data and 'sum_received' in tcp_data['end']:
            tcp_throughput_mbps = round(tcp_data['end']['sum_received']['bits_per_second'] / 1e6, 3)
            tcp_retransmits = tcp_data['end']['sum_sent'].get('retransmits', 0)
        elif 'error' in tcp_data:
            log.warning("iperf3 reported error: %s", tcp_data['error'])
    except Exception as e:
        log.error("Failed to parse iperf3 TCP JSON for trial %s: %s", trial_tag, e)

    # Parse ping metrics
    ping_metrics = parse_ping_output(ping_text)

    # Parse competing metrics
    competing_sent_mbps = 0.0
    competing_loss_pct = 0.0
    if competing_mbps > 0 and competing_json_str:
        try:
            comp_data = json.loads(competing_json_str)
            if 'end' in comp_data and 'sum' in comp_data['end']:
                competing_sent_mbps = round(comp_data['end']['sum']['bits_per_second'] / 1e6, 3)
                competing_loss_pct = round(comp_data['end']['sum'].get('lost_percent', 0.0), 2)
        except Exception as e:
            log.warning("Could not parse competing UDP JSON: %s", e)
            competing_loss_pct = "NOT_AVAILABLE"

    # Cooldown before next trial
    time.sleep(2)

    return {
        'timestamp_utc': timestamp_utc,
        'algorithm': 'static',
        'path': path,
        'competing_mbps': competing_mbps,
        'trial': trial_idx,
        'tcp_throughput_mbps': tcp_throughput_mbps,
        'tcp_retransmits': tcp_retransmits,
        'rtt_min_ms': ping_metrics['rtt_min_ms'],
        'rtt_avg_ms': ping_metrics['rtt_avg_ms'],
        'rtt_max_ms': ping_metrics['rtt_max_ms'],
        'rtt_mdev_ms': ping_metrics['rtt_mdev_ms'],
        'ping_loss_pct': ping_metrics['ping_loss_pct'],
        'competing_loss_pct': competing_loss_pct,
        'bottleneck_mbps': PATH_A_BW if path == 'A' else PATH_B_BW,
        'queue_pkts': queue_pkts,
        'tcp_duration_s': duration,
        'notes': 'first ping discarded'
    }


def main():
    parser = argparse.ArgumentParser(description='SmartTE Static Baseline Experiment Runner')
    parser.add_argument('--paths', nargs='+', choices=['A', 'B'], default=['A', 'B'],
                        help='Primary paths to evaluate (default: A B)')
    parser.add_argument('--competing-rates', nargs='+', type=int, default=[0, 5, 9],
                        help='Competing UDP traffic rates on Path A in Mbps (default: 0 5 9)')
    parser.add_argument('--trials', type=int, default=5,
                        help='Number of trials per configuration (default: 5)')
    parser.add_argument('--duration', type=int, default=15,
                        help='Duration in seconds for TCP transfer (default: 15)')
    parser.add_argument('--queue', type=int, default=DEFAULT_QUEUE,
                        help='Queue limit (max_queue_size in pkts) on bottleneck links (default: 100)')
    parser.add_argument('--smoke-test', action='store_true', default=False,
                        help='Run a quick smoke test (1 trial, 5s, Path A, 0 Mbps competing)')
    args = parser.parse_args()

    # Create timestamped run identifier
    utc_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    run_id = f"static_baseline_{utc_str}"

    raw_base_dir = os.path.join(PROJECT_ROOT, 'results', 'raw')
    os.makedirs(raw_base_dir, exist_ok=True)

    csv_path = os.path.join(raw_base_dir, f"{run_id}.csv")
    trial_raw_dir = os.path.join(raw_base_dir, run_id)
    os.makedirs(trial_raw_dir, exist_ok=True)

    # Save environment metadata
    metadata = {
        'run_id': run_id,
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'git_commit': get_git_commit(),
        'cli_args': vars(args),
        'kernel': os.uname().release,
        'python_version': sys.version,
        'bottleneck_bw_a': PATH_A_BW,
        'bottleneck_bw_b': PATH_B_BW,
        'access_bw': ACCESS_BW,
        'delay_access': DEFAULT_DELAY_ACCESS,
        'delay_a': DEFAULT_DELAY_A,
        'delay_b': DEFAULT_DELAY_B,
        'queue_pkts': args.queue
    }
    with open(os.path.join(trial_raw_dir, 'metadata.json'), 'w') as f:
        json.dump(metadata, f, indent=2)

    fieldnames = [
        'run_id', 'timestamp_utc', 'algorithm', 'path', 'competing_mbps', 'trial',
        'tcp_throughput_mbps', 'tcp_retransmits', 'rtt_min_ms', 'rtt_avg_ms',
        'rtt_max_ms', 'rtt_mdev_ms', 'ping_loss_pct', 'competing_loss_pct',
        'bottleneck_mbps', 'queue_pkts', 'tcp_duration_s', 'notes'
    ]

    # Initialize CSV file with headers
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

    log.info("Initialized run: %s", run_id)
    log.info("Output CSV: %s", csv_path)
    log.info("Raw artifacts directory: %s", trial_raw_dir)

    if args.smoke_test:
        paths_to_run = ['A']
        competing_rates_to_run = [0]
        trials_count = 1
        duration_to_run = 5
        log.info("=== SMOKE TEST MODE ACTIVATED (1 trial, 5s) ===")
    else:
        paths_to_run = args.paths
        competing_rates_to_run = args.competing_rates
        trials_count = args.trials
        duration_to_run = args.duration

    results_list = []

    # Iterate over the experimental matrix
    for path in paths_to_run:
        for c_rate in competing_rates_to_run:
            log.info("============================================================")
            log.info("CONFIGURATION: Primary Path=%s | Competing Path A UDP=%d Mbps", path, c_rate)
            log.info("============================================================")

            # Clean and launch topology once per configuration block
            cleanup_previous()

            comp_setting = 'A' if c_rate > 0 else 'off'
            topo_args = SimpleNamespace(
                path=path,
                competing=comp_setting,
                bw_a=PATH_A_BW,
                bw_b=PATH_B_BW,
                access_bw=ACCESS_BW,
                delay_access=DEFAULT_DELAY_ACCESS,
                delay_a=DEFAULT_DELAY_A,
                delay_b=DEFAULT_DELAY_B,
                queue=args.queue,
                no_cli=True
            )

            net = build_topology(topo_args)
            try:
                net.start()
                time.sleep(2)

                # Clear residual flows and install flows
                for sw in ['s1', 's2', 's3', 's4']:
                    net[sw].dpctl('del-flows', '-O', 'OpenFlow13')
                time.sleep(1)

                install_flows(net, path=path, competing=comp_setting)
                time.sleep(1)

                for t in range(1, trials_count + 1):
                    row = run_trial(net, path, c_rate, t, duration_to_run, trial_raw_dir, args.queue)
                    row['run_id'] = run_id

                    # Write to CSV immediately
                    with open(csv_path, 'a', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writerow(row)

                    results_list.append(row)
                    log.info("Result: Throughput=%.2f Mbps, Retrans=%d, RTT_avg=%.2f ms, Loss=%.1f%%",
                             row['tcp_throughput_mbps'], row['tcp_retransmits'],
                             row['rtt_avg_ms'], row['ping_loss_pct'])
            finally:
                log.info("Cleaning up network for configuration...")
                net.stop()
                cleanup_previous()

    log.info("============================================================")
    log.info("EXPERIMENT COMPLETE. %d total trials recorded.", len(results_list))
    log.info("CSV output available at: %s", csv_path)
    log.info("============================================================")

    # Print summary table if multiple trials were run
    if not args.smoke_test and results_list:
        print_summary_table(results_list)


def print_summary_table(results):
    """Compute and display mean, standard deviation, and count per configuration."""
    groups = {}
    for r in results:
        key = (r['path'], r['competing_mbps'])
        if key not in groups:
            groups[key] = {'tp': [], 'rtt': []}
        groups[key]['tp'].append(r['tcp_throughput_mbps'])
        groups[key]['rtt'].append(r['rtt_avg_ms'])

    def stats(arr):
        n = len(arr)
        if n == 0:
            return 0.0, 0.0, 0
        mean = sum(arr) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in arr) / n) if n > 1 else 0.0
        return mean, std, n

    print("\n" + "=" * 80)
    print("EXPERIMENTAL SUMMARY TABLE (Mean +/- Std Dev)")
    print("=" * 80)
    print(f"{'Path':<6} | {'Competing':<10} | {'Throughput (Mbps)':<22} | {'Average RTT (ms)':<22} | {'n':<4}")
    print("-" * 80)
    for (path, comp), data in sorted(groups.items()):
        tp_mean, tp_std, tp_n = stats(data['tp'])
        rtt_mean, rtt_std, rtt_n = stats(data['rtt'])
        print(f"Path {path:<1} | {comp:>2} Mbps    | {tp_mean:>6.2f} +/- {tp_std:<5.2f} Mbps    | {rtt_mean:>6.2f} +/- {rtt_std:<5.2f} ms     | {tp_n:<4}")
    print("=" * 80 + "\n")


if __name__ == '__main__':
    main()
