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
import shutil
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
    disable_ipv6_interface_noise,
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

FIELDNAMES = [
    'run_id', 'experiment_id', 'timestamp_utc', 'algorithm', 'scenario', 'trial',
    'flow_pair', 'competing_pair', 'initial_path', 'competing_path',
    'offered_load_mbps', 'bottleneck_mbps', 'delay_a_ms', 'delay_b_ms',
    'queue_limit_pkts', 'queue_config', 'tcp_duration_s',
    'tcp_throughput_mbps', 'tcp_retransmits', 'rtt_min_ms', 'rtt_avg_ms',
    'rtt_max_ms', 'rtt_mdev_ms', 'p95_rtt_ms', 'ping_loss_pct',
    'competing_achieved_mbps', 'competing_loss_pct',
    'measured_path_a_utilization_pct', 'measured_path_b_utilization_pct',
    'final_path', 'path_changes', 'decision_count', 'reaction_time_s',
    'recovery_time_s', 'controller_poll_interval_ms', 'switching_threshold',
    'minimum_dwell_time_ms', 'experiment_status', 'raw_log_ref', 'git_commit',
    'git_dirty', 'notes'
]

INTERSWITCH_INTERFACES = [
    's1-eth3', 's2-eth1', 's2-eth2', 's4-eth3',
    's1-eth4', 's3-eth1', 's3-eth2', 's4-eth4'
]

PATH_EGRESS = {
    'A': ('s2', 2, PATH_A_BW),
    'B': ('s3', 2, PATH_B_BW)
}


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


def get_git_dirty():
    """Return the tracked/untracked workspace state from git status --porcelain."""
    try:
        result = subprocess.run(
            ['git', '-C', PROJECT_ROOT, '-c', f'safe.directory={PROJECT_ROOT}',
             'status', '--porcelain'],
            capture_output=True, text=True, check=True
        )
        return bool(result.stdout.strip())
    except Exception as exc:
        log.warning('Could not determine git dirty state: %s', exc)
        return None


def delay_to_ms(delay):
    """Convert Mininet delay strings such as 5ms to milliseconds."""
    match = re.fullmatch(r'\s*([\d.]+)\s*(ms|s|us)?\s*', str(delay), re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or 'ms').lower()
    scale = {'us': 0.001, 'ms': 1.0, 's': 1000.0}[unit]
    return round(value * scale, 6)


def nearest_rank_p95(samples):
    """Return the nearest-rank 95th percentile, or None without samples."""
    if not samples:
        return None
    ordered = sorted(samples)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return round(ordered[index], 3)


def _run_command(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as exc:
        return 1, f'{type(exc).__name__}: {exc}'


def capture_queue_config(net, queue_pkts, raw_dir, label):
    """Capture qdisc/class state and only verify a limit visible on every core iface."""
    per_iface = {}
    raw_lines = []
    limit_pattern = re.compile(rf'\blimit\s+{int(queue_pkts)}\b')
    all_limits_visible = queue_pkts is not None and int(queue_pkts) > 0

    for iface in INTERSWITCH_INTERFACES:
        commands = [
            ['tc', 'qdisc', 'show', 'dev', iface],
            ['tc', '-s', 'qdisc', 'show', 'dev', iface],
            ['tc', 'class', 'show', 'dev', iface]
        ]
        observed = []
        raw_lines.append(f'=== {iface} ===')
        for command in commands:
            code, output = _run_command(command)
            raw_lines.append(f'$ {" ".join(command)} [exit={code}]')
            raw_lines.append(output)
            observed.append(output)
        qdisc_text = observed[0] if observed else ''
        per_iface[iface] = qdisc_text or '(no qdisc output)'
        if not any(limit_pattern.search(text) for text in observed):
            all_limits_visible = False

    # Access-link state is recorded separately because it is outside the queue
    # limit requested for the inter-switch links.
    access_lines = []
    for iface in ('s1-eth1', 's1-eth2', 's4-eth1', 's4-eth2'):
        code, output = _run_command(['tc', 'qdisc', 'show', 'dev', iface])
        access_lines.append(f'{iface} [exit={code}]: {output or "(no qdisc output)"}')
    for host_name in ('h1', 'h3', 'h2', 'h4'):
        iface = f'{host_name}-eth0'
        output = net[host_name].cmd(f'tc qdisc show dev {iface}').strip()
        access_lines.append(f'{host_name}/{iface}: {output or "(no qdisc output)"}')

    with open(os.path.join(raw_dir, f'{label}_tc.txt'), 'w') as f:
        f.write('\n'.join(raw_lines))
        f.write('\n=== host access interfaces ===\n')
        f.write('\n'.join(access_lines))
        f.write('\n')

    observed_description = '; '.join(
        f'{iface}={description}' for iface, description in per_iface.items()
    )
    if all_limits_visible:
        description = f'verified queue limit {int(queue_pkts)} packets; {observed_description}'
    else:
        description = (
            f'NOT VERIFIED: requested max_queue_size={queue_pkts} packets; '
            f'tc output did not show that limit on every inter-switch interface; '
            f'{observed_description}'
        )

    return {
        'queue_config': description,
        'queue_limit_verified': bool(all_limits_visible),
        'access_qdisc': '; '.join(access_lines),
        'raw_log': f'{label}_tc.txt'
    }


def capture_switch_snapshot(net, raw_dir, trial_tag, phase):
    """Save required port and flow counter output for one side of a trial."""
    output_lines = []
    parsed = {'ports': {}, 'flows': {}}
    for sw in ['s2', 's3']:
        output = net[sw].cmd(f'ovs-ofctl -O OpenFlow13 dump-ports {sw}').strip()
        output_lines.extend([f'=== {sw} ports ===', output])
        parsed['ports'][sw] = output
    for sw in ['s1', 's2', 's3', 's4']:
        output = net[sw].cmd(f'ovs-ofctl -O OpenFlow13 dump-flows {sw}').strip()
        output_lines.extend([f'=== {sw} flows ===', output])
        parsed['flows'][sw] = output
    filename = f'{trial_tag}_{phase}_switch_counters.txt'
    with open(os.path.join(raw_dir, filename), 'w') as f:
        f.write('\n'.join(output_lines) + '\n')
    return parsed, filename


def parse_port_counters(output):
    counters = {}
    current_port = None
    for line in output.splitlines():
        port_match = re.search(r'^\s*port\s+(.+?):', line)
        if port_match:
            current_port = port_match.group(1).strip().strip('"')
            counters.setdefault(current_port, {})
        if current_port is None:
            continue
        for direction in ('rx', 'tx'):
            match = re.search(rf'{direction} pkts=(\d+),\s*bytes=(\d+)', line)
            if match:
                counters[current_port][f'{direction}_packets'] = int(match.group(1))
                counters[current_port][f'{direction}_bytes'] = int(match.group(2))
    return counters


def packet_delta_sum(port_deltas, switch):
    """Sum RX and TX packet deltas for a switch's ports."""
    prefix = f'{switch}:'
    return sum(
        value for key, value in port_deltas.items()
        if key.startswith(prefix) and key.endswith((':rx_packets', ':tx_packets'))
    )


def parse_flow_counters(output):
    flows = {}
    for line in output.splitlines():
        match = re.search(r'\bn_packets=(\d+)', line)
        if not match:
            continue
        key = re.sub(r'\bn_packets=\d+', 'n_packets=N', line)
        key = re.sub(r'\bn_bytes=\d+', 'n_bytes=N', key)
        key = re.sub(r',?\s*duration=[^,]+', '', key)
        flows[key.strip()] = int(match.group(1))
    return flows


def write_snapshot_delta(before, after, raw_dir, trial_tag, primary_path,
                         competing_path=None, competing_active=False):
    """Write counter differences and flag traffic observed on the unused path."""
    port_deltas = {}
    for sw in ('s2', 's3'):
        before_ports = parse_port_counters(before['ports'].get(sw, ''))
        after_ports = parse_port_counters(after['ports'].get(sw, ''))
        for port in sorted(set(before_ports) | set(after_ports), key=str):
            old = before_ports.get(port, {})
            new = after_ports.get(port, {})
            for metric in ('rx_packets', 'tx_packets', 'rx_bytes', 'tx_bytes'):
                if metric in old and metric in new:
                    port_deltas[f'{sw}:{port}:{metric}'] = new[metric] - old[metric]

    rx_gt_tx_imbalances = []
    for sw in ('s2', 's3'):
        ports = parse_port_counters(before['ports'].get(sw, ''))
        after_ports = parse_port_counters(after['ports'].get(sw, ''))
        for port in set(ports) | set(after_ports):
            rx_delta = port_deltas.get(f'{sw}:{port}:rx_packets')
            tx_delta = port_deltas.get(f'{sw}:{port}:tx_packets')
            if rx_delta is not None and tx_delta is not None and rx_delta > tx_delta:
                rx_gt_tx_imbalances.append({
                    'switch': sw, 'port': port,
                    'rx_packets_delta': rx_delta,
                    'tx_packets_delta': tx_delta
                })

    flow_deltas = {}
    for sw in ('s1', 's2', 's3', 's4'):
        old_flows = parse_flow_counters(before['flows'].get(sw, ''))
        new_flows = parse_flow_counters(after['flows'].get(sw, ''))
        for rule, count in new_flows.items():
            if rule in old_flows:
                flow_deltas[f'{sw}:{rule}'] = count - old_flows[rule]

    active_paths = {primary_path}
    if competing_active and competing_path:
        active_paths.add(competing_path)
    unused_path = next(iter({'A', 'B'} - active_paths)) if len(active_paths) == 1 else None
    unused_switch = {'A': 's2', 'B': 's3'}.get(unused_path)
    unused_packets = packet_delta_sum(port_deltas, unused_switch) if unused_switch else 0
    report = {
        'port_counter_deltas': port_deltas,
        'rx_gt_tx_direction_imbalances': rx_gt_tx_imbalances,
        'counter_interpretation': (
            'Per-port RX/TX packet-count imbalance is descriptive and can occur '
            'with asymmetric TCP data and ACK traffic; it is not by itself a loop verdict.'
        ),
        'flow_n_packets_deltas': flow_deltas,
        'unused_path': unused_path,
        'unused_path_switch': unused_switch,
        'unused_path_packet_delta_sum': unused_packets,
        'unused_path_traffic_detected': unused_packets > 0
    }
    filename = f'{trial_tag}_counter_deltas.json'
    with open(os.path.join(raw_dir, filename), 'w') as f:
        json.dump(report, f, indent=2)
    return report, filename


def sample_core_tx_bytes(net, path):
    sw, port, capacity_mbps = PATH_EGRESS[path]
    output = net[sw].cmd(f'ovs-ofctl -O OpenFlow13 dump-ports {sw}').strip()
    port_counters = parse_port_counters(output)
    interface = f'{sw}-eth{port}'
    values = port_counters.get(interface) or port_counters.get(str(port))
    if not values or 'tx_bytes' not in values:
        return None, {'switch': sw, 'port': port, 'output': output}
    return values['tx_bytes'], {
        'switch': sw, 'port': port, 'interface': interface,
        'capacity_mbps': capacity_mbps
    }


def evaluate_h3_h4_validation(ping_text, port_deltas, competing_path):
    """Evaluate saved ping and port-counter evidence for h3-h4 path isolation."""
    path_packets = {
        'A': packet_delta_sum(port_deltas, 's2'),
        'B': packet_delta_sum(port_deltas, 's3'),
    }
    ping = parse_ping_output(ping_text)
    duplicate_reply_detected = 'DUP!' in ping_text
    should_work = competing_path != 'off'
    if should_work:
        expected_path = competing_path
        other_path = 'B' if expected_path == 'A' else 'A'
        passed = (
            ping['ping_loss_pct'] == 0.0 and path_packets[expected_path] > 0
            and path_packets[other_path] == 0 and not duplicate_reply_detected
        )
        expectation = (
            f'h3-h4 ping succeeds and Path {expected_path} has packets; '
            f'Path {other_path} has none'
        )
    else:
        passed = (
            ping['ping_loss_pct'] == 100.0 and path_packets['A'] == 0
            and path_packets['B'] == 0 and not duplicate_reply_detected
        )
        expectation = 'h3-h4 ping fails and neither core path has packets'
    return {
        'expected': expectation,
        'observed_ping_loss_pct': ping['ping_loss_pct'],
        'duplicate_reply_detected': duplicate_reply_detected,
        'path_a_packet_delta_sum': path_packets['A'],
        'path_b_packet_delta_sum': path_packets['B'],
        'passed': passed,
    }


def validate_h3_h4(net, competing_path, raw_dir, label):
    """Check the requested h3-h4 rule behavior and save path-counter evidence."""
    before, before_ref = capture_switch_snapshot(net, raw_dir, label, 'h3h4_before')
    ping_text = net['h3'].cmd('ping -c 20 10.0.0.4')
    ping_ref = f'{label}_h3_h4_ping.txt'
    with open(os.path.join(raw_dir, ping_ref), 'w') as f:
        f.write(ping_text)
    after, after_ref = capture_switch_snapshot(net, raw_dir, label, 'h3h4_after')
    deltas, delta_ref = write_snapshot_delta(
        before, after, raw_dir, f'{label}_h3h4', 'A',
        competing_path=competing_path,
        competing_active=competing_path != 'off'
    )
    result = evaluate_h3_h4_validation(
        ping_text, deltas['port_counter_deltas'], competing_path
    )
    result['raw_files'] = [ping_ref, before_ref, after_ref, delta_ref]
    with open(os.path.join(raw_dir, f'{label}_h3_h4_validation.json'), 'w') as f:
        json.dump(result, f, indent=2)
    return result


def parse_ping_output(ping_text):
    """
    Parse ping loss and RTT statistics. The first received RTT sample is discarded
    as a precaution; packet loss still uses ping's full transmitted-packet count.
    """
    loss_match = re.search(r'([\d\.]+)%\s*packet loss', ping_text)
    ping_loss_pct = float(loss_match.group(1)) if loss_match else None

    # Discard sequence 1 when available, even if it was the only RTT sample.
    sequenced = re.findall(
        r'icmp_seq=(\d+).*?time=([\d\.]+)\s*ms', ping_text
    )
    if sequenced:
        valid_samples = [float(value) for seq, value in sequenced if int(seq) != 1]
    else:
        rtt_samples = [float(m) for m in re.findall(r'time=([\d\.]+)\s*ms', ping_text)]
        valid_samples = rtt_samples[1:]

    if valid_samples:
        rtt_min = min(valid_samples)
        rtt_max = max(valid_samples)
        rtt_avg = sum(valid_samples) / len(valid_samples)
        variance = sum((x - rtt_avg) ** 2 for x in valid_samples) / len(valid_samples)
        rtt_mdev = math.sqrt(variance)
    else:
        rtt_min = rtt_avg = rtt_max = rtt_mdev = None

    return {
        'ping_loss_pct': ping_loss_pct,
        'rtt_min_ms': round(rtt_min, 3) if rtt_min is not None else None,
        'rtt_avg_ms': round(rtt_avg, 3) if rtt_avg is not None else None,
        'rtt_max_ms': round(rtt_max, 3) if rtt_max is not None else None,
        'rtt_mdev_ms': round(rtt_mdev, 3) if rtt_mdev is not None else None,
        'p95_rtt_ms': nearest_rank_p95(valid_samples),
        'samples_count': len(valid_samples),
        'discard_rule': 'first received RTT sample discarded as a precaution'
    }


def run_trial(net, path, competing_mbps, trial_idx, duration, raw_dir, queue_pkts,
              run_id, experiment_id, competing_path, queue_config, git_commit, git_dirty,
              path_evidence=False):
    """Run one trial and preserve raw counters, qdisc state, and measurement provenance."""
    timestamp_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    trial_tag = f"{path}_c{competing_mbps}_t{trial_idx}"
    log.info("--- Starting Trial [%s]: Path=%s, Competing=%d Mbps (Duration=%ds) ---",
             trial_tag, path, competing_mbps, duration)

    h1, h2, h3, h4 = (net[name] for name in ('h1', 'h2', 'h3', 'h4'))
    h2.cmd('iperf3 -s -p 5201 -D')
    if competing_mbps > 0:
        h4.cmd('iperf3 -s -p 5202 -D')
    time.sleep(1)

    competing_raw_file = f"/tmp/competing_{trial_tag}.json"
    ping_raw_file = f"/tmp/ping_{trial_tag}.txt"
    before, before_ref = capture_switch_snapshot(net, raw_dir, trial_tag, 'before')

    for host_name in ('h1', 'h2'):
        with open(os.path.join(raw_dir, f'{trial_tag}_{host_name}_neigh.txt'), 'w') as f:
            f.write(net[host_name].cmd('ip neigh show'))

    if competing_mbps > 0:
        log.info("Starting competing UDP flow on h3 -> h4 (%d Mbps)...", competing_mbps)
        comp_cmd = (
            f"iperf3 -c 10.0.0.4 -p 5202 -u -b {competing_mbps}M "
            f"-t {duration + 6} -J > {competing_raw_file} &"
        )
        h3.cmd(comp_cmd)
        time.sleep(2)

    if path_evidence:
        ping_text = h1.cmd(f'ping -c 20 10.0.0.2')
    else:
        ping_count = max(1, int(duration / 0.2))
        h1.cmd(f"ping -i 0.2 -c {ping_count} 10.0.0.2 > {ping_raw_file} &")

    # Sample both core-link egress counters around the TCP measurement window.
    counter_start = {}
    for measured_path in ('A', 'B'):
        value, port_info = sample_core_tx_bytes(net, measured_path)
        counter_start[measured_path] = {'tx_bytes': value, **port_info}
    monotonic_start = time.monotonic()
    tcp_json_str = h1.cmd(f"iperf3 -c 10.0.0.2 -p 5201 -t {duration} -J")
    monotonic_end = time.monotonic()
    counter_end = {}
    for measured_path in ('A', 'B'):
        value, port_info = sample_core_tx_bytes(net, measured_path)
        counter_end[measured_path] = {'tx_bytes': value, **port_info}
    if not path_evidence:
        time.sleep(1)
        ping_text = h1.cmd(f"cat {ping_raw_file}")
    competing_json_str = h3.cmd(f"cat {competing_raw_file}") if competing_mbps > 0 else ''
    for host in (h1, h2, h3, h4):
        host.cmd('killall -9 iperf3 ping 2>/dev/null')
    h1.cmd(f"rm -f {ping_raw_file} {competing_raw_file} 2>/dev/null")

    raw_files = {}
    outputs = {
        'iperf3.json': tcp_json_str,
        'ping.txt': ping_text,
    }
    if competing_mbps > 0:
        outputs['competing.json'] = competing_json_str
    for suffix, content in outputs.items():
        filename = f'{trial_tag}_{suffix}'
        with open(os.path.join(raw_dir, filename), 'w') as f:
            f.write(content)
        raw_files[suffix] = filename

    after, after_ref = capture_switch_snapshot(net, raw_dir, trial_tag, 'after')
    counter_delta, delta_ref = write_snapshot_delta(
        before, after, raw_dir, trial_tag, path,
        competing_path=competing_path,
        competing_active=competing_mbps > 0
    )
    counter_report = {
        'monotonic_start_s': monotonic_start,
        'monotonic_end_s': monotonic_end,
        'interval_s': monotonic_end - monotonic_start,
        'counter_start': counter_start,
        'counter_end': counter_end,
        'port_selection': {
            'A': 's2 port 2, egress toward s4',
            'B': 's3 port 2, egress toward s4'
        },
        'port_selection_reason': 'These are the egress ports of the s2-s4 and s3-s4 core links in the h1-to-h2 direction.',
        'utilization_definition': '(delta_tx_bytes * 8) / (delta_t_seconds * configured_link_capacity_bps) * 100'
    }
    counter_filename = f'{trial_tag}_utilization_counters.json'
    with open(os.path.join(raw_dir, counter_filename), 'w') as f:
        json.dump(counter_report, f, indent=2)
    raw_files['utilization_counters.json'] = counter_filename

    tcp_data = {}
    try:
        tcp_data = json.loads(tcp_json_str)
    except (TypeError, json.JSONDecodeError) as exc:
        log.error('Failed to parse TCP iperf3 JSON for %s: %s', trial_tag, exc)
    tcp_end = tcp_data.get('end', {}) if isinstance(tcp_data, dict) else {}
    tcp_received = tcp_end.get('sum_received', {}) if isinstance(tcp_end, dict) else {}
    tcp_sent = tcp_end.get('sum_sent', {}) if isinstance(tcp_end, dict) else {}
    tcp_rate = tcp_received.get('bits_per_second')
    tcp_throughput_mbps = round(tcp_rate / 1e6, 3) if isinstance(tcp_rate, (int, float)) else None
    tcp_retransmits = tcp_sent.get('retransmits')

    ping_metrics = parse_ping_output(ping_text)
    competing_achieved_mbps = None
    competing_loss_pct = None
    comp_reason = None
    if competing_mbps > 0:
        try:
            comp_data = json.loads(competing_json_str)
            comp_received = comp_data.get('end', {}).get('sum_received', {})
            comp_rate = comp_received.get('bits_per_second')
            if isinstance(comp_rate, (int, float)):
                competing_achieved_mbps = round(comp_rate / 1e6, 3)
            else:
                comp_reason = 'iperf3 JSON has no end.sum_received.bits_per_second'
            loss = comp_received.get('lost_percent')
            if isinstance(loss, (int, float)):
                competing_loss_pct = round(loss, 3)
            elif comp_reason is None:
                comp_reason = 'iperf3 JSON has no receiver-side lost_percent'
        except (TypeError, json.JSONDecodeError):
            comp_reason = 'competing iperf3 JSON unavailable or invalid'

    interval_s = monotonic_end - monotonic_start
    utilization = {'A': None, 'B': None}
    utilization_reasons = []
    for measured_path, capacity_mbps in (('A', PATH_A_BW), ('B', PATH_B_BW)):
        start_bytes = counter_start[measured_path]['tx_bytes']
        end_bytes = counter_end[measured_path]['tx_bytes']
        if start_bytes is None or end_bytes is None:
            utilization_reasons.append(f'Path {measured_path} counter unavailable')
        elif end_bytes < start_bytes:
            utilization_reasons.append(f'Path {measured_path} tx_bytes counter wrapped/decreased')
        elif interval_s < 0.5:
            utilization_reasons.append(f'counter interval too short ({interval_s:.6f}s)')
        else:
            utilization[measured_path] = round(
                ((end_bytes - start_bytes) * 8) / (interval_s * capacity_mbps * 1e6) * 100,
                3
            )

    status = 'ok'
    notes = [
        'TCP throughput is receiver-side iperf3 end.sum_received; retransmits are sender-side end.sum_sent.',
        'First received RTT sample discarded as a precaution; it remains in ping transmitted-packet loss denominator.',
        f'RTT p95 uses nearest-rank method over retained RTT samples (n={ping_metrics["samples_count"]}).',
        f'Counter window={interval_s:.6f}s; utilization counts all egress traffic and headers.',
        f'Queue config: {queue_config}'
    ]
    if tcp_throughput_mbps is None:
        status = 'failed'
        notes.append(f'TCP receiver-side throughput unavailable: {tcp_data.get("error", "missing JSON value")}')
    if ping_metrics['ping_loss_pct'] is None:
        status = 'failed'
        notes.append('Ping loss summary unavailable.')
    if 'DUP!' in ping_text:
        status = 'failed'
        notes.append('Duplicate ICMP reply marker DUP! found in ping output.')
    if competing_mbps > 0 and competing_achieved_mbps is None:
        status = 'failed'
        notes.append(f'Competing achieved rate is null: {comp_reason}')
    if counter_delta['unused_path_traffic_detected']:
        status = 'failed'
        notes.append(
            f'UNUSED-PATH GATE FAILED: {counter_delta["unused_path_packet_delta_sum"]} '
            f'packet-count delta observed on {counter_delta["unused_path_switch"]}.'
        )
    if utilization_reasons:
        notes.append('Utilization unavailable: ' + '; '.join(utilization_reasons))
    if competing_mbps == 0:
        notes.append('Competing achieved rate/loss are empty: no competing UDP flow was configured.')
    if not git_dirty and git_dirty is not None:
        notes.append('git status --porcelain was clean at run start.')
    elif git_dirty is None:
        notes.append('git dirty state unavailable; git status --porcelain failed.')

    time.sleep(2)
    raw_files['switch_counters_before.txt'] = before_ref
    raw_files['switch_counters_after.txt'] = after_ref
    raw_files['counter_deltas.json'] = delta_ref
    raw_log_ref = os.path.join('results', 'raw', run_id, f'{trial_tag}_manifest.json')
    manifest = {
        'trial_tag': trial_tag,
        'raw_files': raw_files,
        'queue_config': queue_config,
        'queue_limit_pkts_requested': queue_pkts,
        'counter_interval_s': interval_s,
        'utilization_port_selection': counter_report['port_selection']
    }
    with open(os.path.join(raw_dir, f'{trial_tag}_manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)

    return {
        'run_id': run_id,
        'experiment_id': experiment_id,
        'timestamp_utc': timestamp_utc,
        'algorithm': 'static',
        'scenario': f'primary_{path}_competing_{competing_path}_{competing_mbps}mbps',
        'trial': trial_idx,
        'flow_pair': 'h1-h2',
        'competing_pair': 'h3-h4' if competing_path != 'off' else None,
        'initial_path': path,
        'competing_path': competing_path if competing_path != 'off' else None,
        'offered_load_mbps': competing_mbps,
        'bottleneck_mbps': PATH_A_BW if path == 'A' else PATH_B_BW,
        'delay_a_ms': delay_to_ms(DEFAULT_DELAY_A),
        'delay_b_ms': delay_to_ms(DEFAULT_DELAY_B),
        'queue_limit_pkts': queue_pkts,
        'queue_config': queue_config,
        'tcp_duration_s': duration,
        'tcp_throughput_mbps': tcp_throughput_mbps,
        'tcp_retransmits': tcp_retransmits,
        'rtt_min_ms': ping_metrics['rtt_min_ms'],
        'rtt_avg_ms': ping_metrics['rtt_avg_ms'],
        'rtt_max_ms': ping_metrics['rtt_max_ms'],
        'rtt_mdev_ms': ping_metrics['rtt_mdev_ms'],
        'p95_rtt_ms': ping_metrics['p95_rtt_ms'],
        'ping_loss_pct': ping_metrics['ping_loss_pct'],
        'competing_achieved_mbps': competing_achieved_mbps,
        'competing_loss_pct': competing_loss_pct,
        'measured_path_a_utilization_pct': utilization['A'],
        'measured_path_b_utilization_pct': utilization['B'],
        'final_path': path,
        'path_changes': 0,
        'decision_count': 0,
        'reaction_time_s': None,
        'recovery_time_s': None,
        'controller_poll_interval_ms': None,
        'switching_threshold': None,
        'minimum_dwell_time_ms': None,
        'experiment_status': status,
        'raw_log_ref': raw_log_ref,
        'git_commit': git_commit,
        'git_dirty': git_dirty,
        'notes': ' '.join(notes)
    }


def make_incomplete_row(run_id, experiment_id, path, competing_mbps, trial_idx,
                        duration, queue_pkts, queue_config, git_commit, git_dirty,
                        status, reason, competing_path='off'):
    """Keep an interrupted or failed trial in the CSV with unavailable values empty."""
    return {
        'run_id': run_id,
        'experiment_id': experiment_id,
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'algorithm': 'static',
        'scenario': f'primary_{path}_competing_{competing_path}_{competing_mbps}mbps',
        'trial': trial_idx,
        'flow_pair': 'h1-h2',
        'competing_pair': 'h3-h4' if competing_path != 'off' else None,
        'initial_path': path,
        'competing_path': competing_path if competing_path != 'off' else None,
        'offered_load_mbps': competing_mbps,
        'bottleneck_mbps': PATH_A_BW if path == 'A' else PATH_B_BW,
        'delay_a_ms': delay_to_ms(DEFAULT_DELAY_A),
        'delay_b_ms': delay_to_ms(DEFAULT_DELAY_B),
        'queue_limit_pkts': queue_pkts,
        'queue_config': queue_config,
        'tcp_duration_s': duration,
        'tcp_throughput_mbps': None,
        'tcp_retransmits': None,
        'rtt_min_ms': None,
        'rtt_avg_ms': None,
        'rtt_max_ms': None,
        'rtt_mdev_ms': None,
        'p95_rtt_ms': None,
        'ping_loss_pct': None,
        'competing_achieved_mbps': None,
        'competing_loss_pct': None,
        'measured_path_a_utilization_pct': None,
        'measured_path_b_utilization_pct': None,
        'final_path': path,
        'path_changes': 0,
        'decision_count': 0,
        'reaction_time_s': None,
        'recovery_time_s': None,
        'controller_poll_interval_ms': None,
        'switching_threshold': None,
        'minimum_dwell_time_ms': None,
        'experiment_status': status,
        'raw_log_ref': os.path.join('results', 'raw', run_id),
        'git_commit': git_commit,
        'git_dirty': git_dirty,
        'notes': f'Trial row retained; {status}: {reason}'
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
    parser.add_argument('--path-evidence', action='store_true', default=False,
                        help='Run Part 1.5 path checks: 20 pings, 10s TCP, three trials, and h3-h4 rule checks')
    parser.add_argument('--queue-audit-only', action='store_true', default=False,
                        help='Capture tc qdisc/class state on all inter-switch and access interfaces, without traffic')
    args = parser.parse_args()

    # Create timestamped run identifier
    utc_str = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
    run_id = f"static_baseline_{utc_str}"

    raw_base_dir = os.path.join(PROJECT_ROOT, 'results', 'raw')
    os.makedirs(raw_base_dir, exist_ok=True)

    csv_path = os.path.join(raw_base_dir, f"{run_id}.csv")
    trial_raw_dir = os.path.join(raw_base_dir, run_id)
    os.makedirs(trial_raw_dir, exist_ok=True)

    experiment_id = 'static_baseline_m2'
    git_commit = get_git_commit()
    git_dirty = get_git_dirty()

    # Save environment metadata
    metadata = {
        'run_id': run_id,
        'experiment_id': experiment_id,
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'git_commit': git_commit,
        'git_dirty': git_dirty,
        'cli_args': vars(args),
        'kernel': os.uname().release,
        'python_version': sys.version,
        'bottleneck_bw_a': PATH_A_BW,
        'bottleneck_bw_b': PATH_B_BW,
        'access_bw': ACCESS_BW,
        'delay_access': DEFAULT_DELAY_ACCESS,
        'delay_a': DEFAULT_DELAY_A,
        'delay_b': DEFAULT_DELAY_B,
        'queue_pkts': args.queue,
        'queue_config': f'NOT VERIFIED: requested TCLink max_queue_size={args.queue}; qdisc capture pending',
        'queue_limit_verified': False,
        'queue_observations': [],
        'access_qdisc_observations': [],
        'path_utilization_method': 'OVS tx_bytes counters sampled around TCP window using time.monotonic()',
        'path_utilization_ports': {
            'A': 's2 port 2, egress toward s4',
            'B': 's3 port 2, egress toward s4'
        },
        'path_utilization_port_selection_reason': (
            'Selected the egress port of each core link in the h1-to-h2 flow direction.'
        )
    }
    metadata_path = os.path.join(trial_raw_dir, 'metadata.json')

    def save_metadata():
        with open(metadata_path, 'w') as metadata_file:
            json.dump(metadata, metadata_file, indent=2)

    save_metadata()
    fieldnames = FIELDNAMES

    # Initialize CSV file with headers
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

    log.info("Initialized run: %s", run_id)
    log.info("Output CSV: %s", csv_path)
    log.info("Raw artifacts directory: %s", trial_raw_dir)

    if args.queue_audit_only:
        configurations = [('A', 0, 'off')]
        trials_count = 0
        duration_to_run = 0
        log.info('=== QUEUE AUDIT ONLY (no traffic trials) ===')
    elif args.path_evidence:
        configurations = [('A', 0, 'off'), ('B', 0, 'off'), ('A', 0, 'A')]
        trials_count = 3
        duration_to_run = 10
        log.info('=== PATH EVIDENCE MODE (A/off, B/off, A/A; 3 trials x 10s) ===')
    elif args.smoke_test:
        configurations = [('A', 0, 'off')]
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
        configurations = [
            (path, c_rate, 'A' if c_rate > 0 else 'off')
            for path in paths_to_run for c_rate in competing_rates_to_run
        ]

    results_list = []
    stop_after_gate_failure = False

    # Iterate over the selected experiment configurations.
    for path, c_rate, comp_setting in configurations:
            log.info("============================================================")
            log.info("CONFIGURATION: Primary Path=%s | Competing Path A UDP=%d Mbps", path, c_rate)
            log.info("============================================================")

            # Clean and launch topology once per configuration block
            cleanup_previous()

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
                ipv6_observation = disable_ipv6_interface_noise(
                    net, trial_raw_dir, f'{path}_c{c_rate}'
                )
                metadata.setdefault('ipv6_interface_observations', []).append({
                    'scenario': f'primary_{path}_competing_{comp_setting}_{c_rate}mbps',
                    **ipv6_observation
                })
                save_metadata()
                if not ipv6_observation['verified']:
                    raise RuntimeError(
                        'IPv6 suppression could not be verified on all Mininet interfaces.'
                    )
                time.sleep(2)

                qdisc_observation = capture_queue_config(
                    net, args.queue, trial_raw_dir, f'{path}_c{c_rate}'
                )
                metadata['queue_config'] = qdisc_observation['queue_config']
                metadata['queue_limit_verified'] = qdisc_observation['queue_limit_verified']
                metadata['queue_observations'].append({
                    'scenario': f'primary_{path}_competing_{comp_setting}_{c_rate}mbps',
                    'queue_config': qdisc_observation['queue_config'],
                    'queue_limit_verified': qdisc_observation['queue_limit_verified'],
                    'raw_log_ref': qdisc_observation['raw_log']
                })
                metadata['access_qdisc_observations'].append({
                    'scenario': f'primary_{path}_competing_{comp_setting}_{c_rate}mbps',
                    'description': qdisc_observation['access_qdisc']
                })
                save_metadata()

                # Clear residual flows and install flows
                for sw in ['s1', 's2', 's3', 's4']:
                    net[sw].dpctl('del-flows', '-O', 'OpenFlow13')
                time.sleep(1)

                install_flows(net, path=path, competing=comp_setting)
                time.sleep(1)

                for t in range(1, trials_count + 1):
                    try:
                        row = run_trial(
                            net, path, c_rate, t, duration_to_run, trial_raw_dir,
                            args.queue, run_id, experiment_id, comp_setting,
                            qdisc_observation['queue_config'], git_commit, git_dirty,
                            path_evidence=args.path_evidence
                        )
                    except KeyboardInterrupt:
                        row = make_incomplete_row(
                            run_id, experiment_id, path, c_rate, t, duration_to_run,
                            args.queue, qdisc_observation['queue_config'], git_commit,
                            git_dirty, 'aborted', 'KeyboardInterrupt during trial',
                            competing_path=comp_setting
                        )
                        stop_after_gate_failure = True
                    except Exception as exc:
                        log.exception('Trial %s failed before completion', t)
                        row = make_incomplete_row(
                            run_id, experiment_id, path, c_rate, t, duration_to_run,
                            args.queue, qdisc_observation['queue_config'], git_commit,
                            git_dirty, 'failed', f'{type(exc).__name__}: {exc}',
                            competing_path=comp_setting
                        )

                    # Write to CSV immediately
                    with open(csv_path, 'a', newline='') as f:
                        writer = csv.DictWriter(f, fieldnames=fieldnames)
                        writer.writerow(row)

                    results_list.append(row)
                    log.info(
                        'Result: status=%s, throughput=%s Mbps, RTT_avg=%s ms, loss=%s%%',
                        row['experiment_status'], row['tcp_throughput_mbps'],
                        row['rtt_avg_ms'], row['ping_loss_pct']
                    )
                    if 'UNUSED-PATH GATE FAILED' in row['notes']:
                        log.error('Unused-path traffic detected; stopping matrix for diagnosis.')
                        stop_after_gate_failure = True
                    if stop_after_gate_failure:
                        break
                if args.path_evidence and not args.queue_audit_only and not stop_after_gate_failure:
                    validation = validate_h3_h4(
                        net, comp_setting, trial_raw_dir,
                        f'{path}_competing_{comp_setting}_h3h4'
                    )
                    metadata.setdefault('h3_h4_validation', []).append({
                        'scenario': f'primary_{path}_competing_{comp_setting}',
                        **validation
                    })
                    save_metadata()
                    if not validation['passed']:
                        stop_after_gate_failure = True
                        log.error('h3-h4 validation failed; stop and diagnose.')
            finally:
                log.info("Cleaning up network for configuration...")
                net.stop()
                cleanup_previous()
            if stop_after_gate_failure:
                break

    log.info("============================================================")
    log.info("EXPERIMENT COMPLETE. %d total trials recorded.", len(results_list))
    log.info("CSV output available at: %s", csv_path)
    log.info("============================================================")

    # Keep a reviewable copy of all raw evidence in the requested verification area.
    evidence_dir = os.path.join(PROJECT_ROOT, 'logs', 'm2_verification', run_id)
    os.makedirs(evidence_dir, exist_ok=True)
    metadata['verification_evidence_dir'] = os.path.relpath(evidence_dir, PROJECT_ROOT)
    save_metadata()
    for filename in os.listdir(trial_raw_dir):
        source = os.path.join(trial_raw_dir, filename)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(evidence_dir, filename))
    shutil.copy2(csv_path, os.path.join(evidence_dir, os.path.basename(csv_path)))

    # Print summary table if multiple trials were run
    if not args.smoke_test and results_list:
        print_summary_table(results_list)


def print_summary_table(results):
    """Compute and display mean, standard deviation, and count per configuration."""
    groups = {}
    for r in results:
        key = (r['initial_path'], r['offered_load_mbps'])
        if key not in groups:
            groups[key] = {'tp': [], 'rtt': []}
        if r['tcp_throughput_mbps'] is not None:
            groups[key]['tp'].append(r['tcp_throughput_mbps'])
        if r['rtt_avg_ms'] is not None:
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
