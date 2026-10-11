#!/usr/bin/env python3
"""Run reproducible static, B, and C trials through the OpenFlow controller.

The Mininet host Python drives the experiment. OS-Ken runs in its isolated
Python 3.10 environment as a child process. Per-trial raw files are retained
beside the campaign CSV and metadata.
"""

import argparse
import csv
import datetime
import json
import math
import os
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from experiments.run_static_baseline import (  # noqa: E402
    FIELDNAMES,
    capture_queue_config,
    capture_switch_snapshot,
    get_git_commit,
    get_git_dirty,
    parse_ping_output,
    parse_port_counters,
    write_snapshot_delta,
    wait_for_iperf_json,
)
from topology.datacenter_topology import (  # noqa: E402
    ACCESS_BW,
    DEFAULT_DELAY_ACCESS,
    DEFAULT_DELAY_A,
    DEFAULT_DELAY_B,
    PATH_A_BW,
    PATH_B_BW,
    build_topology,
    cleanup_previous,
    disable_ipv6_interface_noise,
)
from controller.congestion_policy import successful_path_change_count  # noqa: E402

CONTROLLER_PYTHON = os.environ.get(
    'SMARTTE_CONTROLLER_PYTHON',
    '/home/andy2341/.local/share/smartte/os-ken-py310/bin/python',
)
CONTROLLER_LAUNCHER = os.path.join(PROJECT_ROOT, 'controller', 'run_osken.py')
POLL_MS = 1000
QUEUE_PKTS = 100
ACCESS_DELAY = '1ms'
PATH_A_DELAY = '5ms'
PATH_B_DELAY = '10ms'


def utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def read_jsonl(path):
    if not os.path.isfile(path):
        return []
    records = []
    with open(path, encoding='utf-8') as source:
        for line in source:
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def write_json(path, value):
    with open(path, 'w', encoding='utf-8') as output:
        json.dump(value, output, indent=2, sort_keys=True)


def write_load_event(path, event_id, state, monotonic_s):
    payload = {
        'event_id': event_id,
        'state': state,
        'time_monotonic_s': monotonic_s,
    }
    temporary = f'{path}.tmp'
    write_json(temporary, payload)
    os.replace(temporary, path)
    return payload


def wait_until(target_monotonic_s):
    while time.monotonic() < target_monotonic_s:
        time.sleep(min(0.1, target_monotonic_s - time.monotonic()))


def controller_counter_window(stats_path, switch, port, window_start, window_end, capacity_mbps):
    """Use OpenFlow stats records bracketing the measured TCP interval."""
    rows = [
        row for row in read_jsonl(stats_path)
        if row.get('status') == 'ok'
        and row.get('switch') == switch
        and int(row.get('port_no', -1)) == port
        and isinstance(row.get('tx_bytes'), int)
        and isinstance(row.get('time_monotonic_s'), (int, float))
    ]
    before = [row for row in rows if row['time_monotonic_s'] <= window_start]
    after = [row for row in rows if row['time_monotonic_s'] >= window_end]
    first = max(before, key=lambda row: row['time_monotonic_s']) if before else None
    last = min(after, key=lambda row: row['time_monotonic_s']) if after else None
    report = {
        'switch': switch,
        'port': port,
        'interface': f'{switch}-eth{port}',
        'capacity_mbps': capacity_mbps,
        'requested_window_start_monotonic_s': window_start,
        'requested_window_end_monotonic_s': window_end,
        'counter_start': first,
        'counter_end': last,
        'utilization_pct': None,
        'status': 'counter sample missing before or after the TCP window',
    }
    if first is None or last is None:
        return report
    interval_s = last['time_monotonic_s'] - first['time_monotonic_s']
    delta_bytes = last['tx_bytes'] - first['tx_bytes']
    report.update({'interval_s': interval_s, 'delta_tx_bytes': delta_bytes})
    if delta_bytes < 0:
        report['status'] = 'counter decreased or wrapped'
    elif interval_s < 0.5:
        report['status'] = f'counter interval too short ({interval_s:.6f}s)'
    else:
        report['utilization_pct'] = round(
            delta_bytes * 8 / (interval_s * capacity_mbps * 1_000_000) * 100,
            3,
        )
        report['status'] = 'ok'
    return report


def compute_path_utilization(stats_path, tcp_start, tcp_end):
    return {
        'A': controller_counter_window(
            stats_path, 's2', 2, tcp_start, tcp_end, PATH_A_BW
        ),
        'B': controller_counter_window(
            stats_path, 's3', 2, tcp_start, tcp_end, PATH_B_BW
        ),
    }


def write_root_flow_dump(raw_dir, switch, phase):
    """Capture OVS flow output from the root namespace, including exit status."""
    result = subprocess.run(
        ['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', switch],
        capture_output=True,
        text=True,
        timeout=10,
    )
    text = result.stdout + result.stderr
    filename = f'{switch}_{phase}_flows.txt'
    with open(os.path.join(raw_dir, filename), 'w', encoding='utf-8') as output:
        output.write(text)
    return {
        'switch': switch,
        'exit_code': result.returncode,
        'raw_file': filename,
        'nonempty': bool(text.strip()),
        'smartte_cookie_entries': sum(
            1 for line in text.lower().splitlines()
            if 'cookie=0x534d4152' in line
        ),
    }


def start_controller(policy, initial_path, competing_path, poll_ms, threshold,
                     dwell_ms, raw_dir):
    controller_logs = {
        'ready': os.path.join(raw_dir, 'controller_ready.json'),
        'events': os.path.join(raw_dir, 'controller_events.jsonl'),
        'stats': os.path.join(raw_dir, 'controller_port_stats.jsonl'),
        'load_event': os.path.join(raw_dir, 'load_event.json'),
        'process': os.path.join(raw_dir, 'controller_process.log'),
    }
    environment = os.environ.copy()
    environment.update({
        'OSKEN_HUB_TYPE': 'eventlet',
        'SMARTTE_POLICY': policy,
        'SMARTTE_INITIAL_PATH': initial_path,
        'SMARTTE_COMPETING_PATH': competing_path,
        'SMARTTE_POLL_INTERVAL_MS': str(poll_ms),
        'SMARTTE_SWITCHING_THRESHOLD': str(threshold),
        'SMARTTE_MINIMUM_DWELL_MS': str(dwell_ms),
        'SMARTTE_READY_FILE': controller_logs['ready'],
        'SMARTTE_EVENT_LOG': controller_logs['events'],
        'SMARTTE_STATS_LOG': controller_logs['stats'],
        'SMARTTE_LOAD_EVENT_FILE': controller_logs['load_event'],
        'SMARTTE_LOG_LEVEL': 'INFO',
    })
    output = open(controller_logs['process'], 'w', encoding='utf-8')
    process = subprocess.Popen(
        [CONTROLLER_PYTHON, CONTROLLER_LAUNCHER],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=output,
        stderr=subprocess.STDOUT,
    )
    return process, output, controller_logs


def wait_controller_ready(process, ready_file, timeout_s=20):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'Controller exited before readiness (code {process.returncode}).')
        if os.path.isfile(ready_file):
            with open(ready_file, encoding='utf-8') as source:
                ready = json.load(source)
            if ready.get('ready') and len(ready.get('connected_switches', [])) == 4:
                return ready
        time.sleep(0.1)
    raise TimeoutError('Controller did not become ready on all four switches within 20 seconds.')


def launch_udp_burst(h3, receiver_ip, rate_mbps, duration_s, raw_path):
    command = (
        f'iperf3 -c {receiver_ip} -p 5202 -u -b {rate_mbps}M '
        f'-t {duration_s:.3f} -J > {raw_path} 2>&1 &'
    )
    h3.cmd(command)


def wait_for_ping_summary(node, path, timeout_s):
    """Wait for ping's summary line, not just the first asynchronously written replies."""
    deadline = time.monotonic() + timeout_s
    latest = ''
    while time.monotonic() < deadline:
        latest = node.cmd(f'cat {path} 2>/dev/null')
        if parse_ping_output(latest)['ping_loss_pct'] is not None:
            return latest
        time.sleep(0.2)
    return latest


def run_load_schedule(net, schedule, tcp_start, event_file, event_prefix, raw_dir):
    """Start the defined UDP on/off schedule and save receiver-side JSON per burst."""
    if not schedule:
        return []
    h3 = net['h3']
    raw_runs = []
    for index, (offset_s, rate_mbps, active_s) in enumerate(schedule, start=1):
        wait_until(tcp_start + offset_s)
        on_time = time.monotonic()
        event_id = f'{event_prefix}-{index}-on'
        write_load_event(event_file, event_id, 'on', on_time)
        json_path = f'/tmp/{event_prefix}_burst_{index}.json'
        json_path_node = os.path.join(raw_dir, f'competing_burst_{index}.json')
        launch_udp_burst(h3, '10.0.0.4', rate_mbps, active_s, json_path)
        wait_until(on_time + active_s)
        off_time = time.monotonic()
        write_load_event(event_file, f'{event_prefix}-{index}-off', 'off', off_time)
        content = wait_for_iperf_json(h3, json_path, 12) or ''
        with open(json_path_node, 'w', encoding='utf-8') as output:
            output.write(content)
        raw_runs.append({
            'index': index,
            'requested_rate_mbps': rate_mbps,
            'active_duration_s': active_s,
            'start_monotonic_s': on_time,
            'end_monotonic_s': off_time,
            'node_json_path': json_path,
            'raw_file': os.path.basename(json_path_node),
            'json': content,
        })
    return raw_runs


def summarize_competing(bursts):
    receiver_bits = 0.0
    active_seconds = 0.0
    total_packets = 0.0
    lost_packets = 0.0
    valid = 0
    for burst in bursts:
        try:
            data = json.loads(burst['json'])
            received = data.get('end', {}).get('sum_received', {})
            bits = received.get('bytes')
            seconds = received.get('seconds')
            if isinstance(bits, (int, float)) and isinstance(seconds, (int, float)):
                receiver_bits += bits * 8
                active_seconds += seconds
            if isinstance(received.get('packets'), (int, float)):
                total_packets += received['packets']
            if isinstance(received.get('lost_packets'), (int, float)):
                lost_packets += received['lost_packets']
            valid += 1
        except (TypeError, json.JSONDecodeError):
            continue
    achieved = round(receiver_bits / active_seconds / 1_000_000, 3) if active_seconds else None
    loss = round(lost_packets / total_packets * 100, 3) if total_packets else None
    return achieved, loss, valid


def load_policy_events(event_path, initial_path):
    events = read_jsonl(event_path)
    decisions = [
        event for event in events
        if event.get('decision') in ('hold', 'switch')
        and event.get('policy') in ('B', 'C')
    ]
    switches = [event for event in events if event.get('decision') == 'switch']
    current_path = initial_path
    for event in events:
        if event.get('path_after') in ('A', 'B'):
            current_path = event['path_after']
        elif event.get('current_path') in ('A', 'B'):
            current_path = event['current_path']
    reaction = next(
        (event.get('reaction_time_s') for event in switches
         if isinstance(event.get('reaction_time_s'), (int, float))),
        None,
    )
    recovery = next(
        (event.get('recovery_time_s') for event in switches
         if isinstance(event.get('recovery_time_s'), (int, float))),
        None,
    )
    return {
        'events': events,
        'decision_count': len(decisions),
        'path_changes': successful_path_change_count(events),
        'final_path': current_path,
        'reaction_time_s': reaction,
        'recovery_time_s': recovery,
    }


def run_one_trial(config, run_id, trial_number, csv_path, metadata, raw_root):
    policy = config['policy']
    initial_path = config['initial_path']
    offered_rate = config.get('offered_rate_mbps', 0)
    schedule = config.get('schedule', [])
    scenario = config['scenario']
    tag = f"{scenario}_t{trial_number:02d}"
    raw_dir = os.path.join(raw_root, tag)
    os.makedirs(raw_dir, exist_ok=True)
    controller = None
    controller_output = None
    net = None
    status = 'ok'
    error_notes = []
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    tcp_json = ''
    ping_text = ''
    bursts = []
    counter_delta = {}
    utilization = {'A': None, 'B': None}
    utilization_records = {}
    queue_observation = {
        'queue_limit_verified': False,
        'queue_limit_pkts': None,
        'queue_config': 'NOT VERIFIED: trial did not inspect qdisc state',
        'raw_log': None,
    }
    cleanup_flows = []
    before_ref = None
    after_ref = None
    delta_ref = None
    controller_logs = {}
    tcp_start = None
    tcp_end = None
    ipv6 = {'verified': False}
    ready = None
    link_failure_time = None
    alternate_path_first_tx_time = None

    try:
        with socket.socket() as listener:
            if listener.connect_ex(('127.0.0.1', 6653)) == 0:
                raise RuntimeError('TCP port 6653 is already occupied.')
        competing_path = 'A' if (offered_rate > 0 or schedule) else 'off'
        controller, controller_output, controller_logs = start_controller(
            policy, initial_path, competing_path,
            config.get('poll_ms', POLL_MS),
            config.get('threshold', 15.0),
            config.get('dwell_ms', 5000),
            raw_dir,
        )
        cleanup_previous()
        topo_args = SimpleNamespace(
            path=initial_path,
            competing=competing_path,
            bw_a=PATH_A_BW,
            bw_b=PATH_B_BW,
            access_bw=ACCESS_BW,
            delay_access=ACCESS_DELAY,
            delay_a=PATH_A_DELAY,
            delay_b=PATH_B_DELAY,
            queue=QUEUE_PKTS,
            controller='remote',
            no_cli=True,
        )
        net = build_topology(topo_args)
        net.start()
        ipv6 = disable_ipv6_interface_noise(net, raw_dir, tag)
        ready = wait_controller_ready(controller, controller_logs['ready'])
        time.sleep(1)
        queue_observation = capture_queue_config(net, QUEUE_PKTS, raw_dir, tag)
        if not ipv6.get('verified'):
            raise RuntimeError('IPv6 suppression was not verified on all Mininet interfaces.')
        if not queue_observation['queue_limit_verified']:
            status = 'excluded'
            error_notes.append('Queue limit was not visible on every inter-switch interface.')
        before, before_ref = capture_switch_snapshot(net, raw_dir, tag, 'before')
        for host in ('h1', 'h2'):
            with open(os.path.join(raw_dir, f'{host}_neighbors.txt'), 'w', encoding='utf-8') as output:
                output.write(net[host].cmd('ip neigh show'))

        h1, h2, h3, h4 = (net[name] for name in ('h1', 'h2', 'h3', 'h4'))
        h2.cmd('iperf3 -s -p 5201 > /tmp/smartte_iperf_h2.log 2>&1 &')
        if competing_path == 'A':
            h4.cmd('iperf3 -s -p 5202 > /tmp/smartte_iperf_h4.log 2>&1 &')
        time.sleep(0.5)
        tcp_file_host = f'/tmp/{tag}_tcp.json'
        ping_file_host = f'/tmp/{tag}_ping.txt'
        tcp_json_file = os.path.join(raw_dir, 'primary_tcp_iperf3.json')
        ping_file = os.path.join(raw_dir, 'primary_ping.txt')
        ping_count = max(1, int(math.ceil(config['duration_s'] / 0.2)))
        h1.cmd(f'ping -i 0.2 -c {ping_count} 10.0.0.2 > {ping_file_host} 2>&1 &')
        if config.get('fail_path_a_at_s') is not None:
            fail_at = float(config['fail_path_a_at_s'])
        else:
            fail_at = None

        tcp_start = time.monotonic()
        h1.cmd(
            f'iperf3 -c 10.0.0.2 -p 5201 -t {config["duration_s"]} '
            f'-J > {tcp_file_host} 2>&1 &'
        )

        schedule_thread_error = None
        if schedule:
            bursts = run_load_schedule(
                net, schedule, tcp_start, controller_logs['load_event'], tag, raw_dir
            )
        elif offered_rate > 0:
            start_after_s = float(config.get('load_start_s', 0))
            wait_until(tcp_start + start_after_s)
            active_s = max(1.0, config['duration_s'] - start_after_s)
            burst_result = run_load_schedule(
                net,
                [(start_after_s, offered_rate, active_s)],
                tcp_start,
                controller_logs['load_event'],
                tag,
                raw_dir,
            )
            bursts.extend(burst_result)

        if fail_at is not None:
            wait_until(tcp_start + fail_at)
            link_failure_time = time.monotonic()
            link_event = {
                'event': 'path_a_link_down',
                'time_monotonic_s': link_failure_time,
                'link': 's2-s4',
            }
            write_json(os.path.join(raw_dir, 'link_failure_event.json'), link_event)
            net.configLinkStatus('s2', 's4', 'down')

        tcp_json = wait_for_iperf_json(h1, tcp_file_host, config['duration_s'] + 20) or ''
        tcp_end = time.monotonic()
        ping_text = wait_for_ping_summary(
            h1, ping_file_host, config['duration_s'] + 10
        )
        with open(tcp_json_file, 'w', encoding='utf-8') as output:
            output.write(tcp_json)
        with open(ping_file, 'w', encoding='utf-8') as output:
            output.write(ping_text)
        h1.cmd(f'rm -f {tcp_file_host} {ping_file_host}')

        after, after_ref = capture_switch_snapshot(net, raw_dir, tag, 'after_traffic')
        counter_delta, delta_ref = write_snapshot_delta(
            before, after, raw_dir, tag, initial_path,
            competing_path=competing_path,
            competing_active=bool(bursts),
        )

        # Allow one OpenFlow poll after the measured window to be written.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if any(
                row.get('status') == 'ok'
                and row.get('switch') in ('s2', 's3')
                and row.get('time_monotonic_s', 0) >= tcp_end
                for row in read_jsonl(controller_logs['stats'])
            ):
                break
            time.sleep(0.1)
        utilization_records = compute_path_utilization(
            controller_logs['stats'], tcp_start, tcp_end
        )
        utilization = {
            path: record['utilization_pct']
            for path, record in utilization_records.items()
        }
        write_json(os.path.join(raw_dir, 'openflow_utilization_counters.json'), {
            'counter_source': 'OS-Ken OFPPortStatsReply tx_bytes',
            'counter_window_definition': 'latest sample at/before TCP start through earliest sample at/after TCP end',
            'tcp_start_monotonic_s': tcp_start,
            'tcp_end_monotonic_s': tcp_end,
            'interval_note': 'Actual OpenFlow sample timestamps are recorded per path; the poll interval is not substituted for elapsed time.',
            'paths': utilization_records,
        })

        # Give the next async stats cycle time to observe any first packet on
        # the alternative path after a link failure.
        if link_failure_time is not None:
            start_rows = read_jsonl(controller_logs['stats'])
            alternative = 'B'
            prior = [
                row for row in start_rows
                if row.get('switch') == 's3' and row.get('port_no') == 2
                and row.get('time_monotonic_s', 0) <= link_failure_time
            ]
            baseline_bytes = prior[-1]['tx_bytes'] if prior else None
            for row in start_rows:
                if (row.get('switch') == 's3' and row.get('port_no') == 2
                        and row.get('time_monotonic_s', 0) >= link_failure_time
                        and isinstance(baseline_bytes, int)
                        and row.get('tx_bytes', 0) > baseline_bytes):
                    alternate_path_first_tx_time = row['time_monotonic_s']
                    break

        h1h2_metrics = parse_ping_output(ping_text)
        tcp_data = {}
        try:
            tcp_data = json.loads(tcp_json)
        except (TypeError, json.JSONDecodeError):
            pass
        tcp_end_json = tcp_data.get('end', {}) if isinstance(tcp_data, dict) else {}
        tcp_received = tcp_end_json.get('sum_received', {})
        tcp_sent = tcp_end_json.get('sum_sent', {})
        tcp_rate = tcp_received.get('bits_per_second')
        tcp_throughput = round(tcp_rate / 1e6, 3) if isinstance(tcp_rate, (int, float)) else None
        tcp_retransmits = tcp_sent.get('retransmits')

        comp_rate, comp_loss, valid_comp_runs = summarize_competing(bursts)
        policy_metrics = load_policy_events(controller_logs['events'], initial_path)
        if fail_at is not None and alternate_path_first_tx_time is not None:
            recovery_time = round(alternate_path_first_tx_time - link_failure_time, 3)
        elif fail_at is not None:
            recovery_time = None
        else:
            recovery_time = policy_metrics['recovery_time_s']

        notes = [
            'TCP throughput is receiver-side iperf3 end.sum_received; retransmits are sender-side end.sum_sent.',
            'First received RTT sample discarded as a precaution; ping loss uses all transmitted echo requests.',
            'RTT p95 is nearest-rank over retained RTT samples.',
            'Queue limit was read from tc on all eight directed core interfaces.',
            'Utilization uses OS-Ken OFPPortStatsReply tx_bytes on s2 port 2 (A) and s3 port 2 (B), each egressing toward s4.',
            'Controller score is the maximum measured utilization among that path’s two core egress links; the controlled flow is included in those counters.',
        ]
        if not bursts:
            notes.append('Competing achieved rate/loss are empty because no UDP workload was configured.')
        elif valid_comp_runs != len(bursts):
            status = 'failed'
            notes.append(f'Only {valid_comp_runs}/{len(bursts)} receiver-side UDP JSON results were valid.')
        if tcp_throughput is None:
            status = 'failed'
            notes.append('Receiver-side TCP throughput JSON was unavailable or invalid.')
        if h1h2_metrics['ping_loss_pct'] is None:
            status = 'failed'
            notes.append('Primary ping summary was unavailable.')
        if 'DUP!' in ping_text:
            status = 'failed'
            notes.append('DUP! marker appeared in the primary ping log.')
        if status == 'ok' and not queue_observation['queue_limit_verified']:
            status = 'excluded'
        if policy == 'STATIC':
            policy_metrics.update({
                'path_changes': 0,
                'decision_count': 0,
                'final_path': initial_path,
                'reaction_time_s': None,
                'recovery_time_s': recovery_time,
            })
        else:
            policy_metrics['recovery_time_s'] = recovery_time
        if fail_at is not None:
            if alternate_path_first_tx_time is None and policy != 'STATIC':
                notes.append('No alternative-path tx_bytes increase was observed after the Path A link-down event.')
            elif policy == 'STATIC':
                notes.append('Static Path A intentionally does not reroute after the failed link.')

        row = {
            'run_id': run_id,
            'experiment_id': config['experiment_id'],
            'timestamp_utc': now_utc,
            'algorithm': policy.lower(),
            'scenario': scenario,
            'trial': trial_number,
            'flow_pair': 'h1-h2',
            'competing_pair': 'h3-h4' if (offered_rate or schedule) else '',
            'initial_path': initial_path,
            'competing_path': 'A' if (offered_rate or schedule) else '',
            'offered_load_mbps': offered_rate,
            'bottleneck_mbps': PATH_A_BW if initial_path == 'A' else PATH_B_BW,
            'delay_a_ms': 5.0,
            'delay_b_ms': 10.0,
            'queue_limit_pkts': queue_observation['queue_limit_pkts'],
            'queue_config': queue_observation['queue_config'],
            'tcp_duration_s': config['duration_s'],
            'tcp_throughput_mbps': tcp_throughput,
            'tcp_retransmits': tcp_retransmits,
            'rtt_min_ms': h1h2_metrics['rtt_min_ms'],
            'rtt_avg_ms': h1h2_metrics['rtt_avg_ms'],
            'rtt_max_ms': h1h2_metrics['rtt_max_ms'],
            'rtt_mdev_ms': h1h2_metrics['rtt_mdev_ms'],
            'p95_rtt_ms': h1h2_metrics['p95_rtt_ms'],
            'ping_loss_pct': h1h2_metrics['ping_loss_pct'],
            'competing_achieved_mbps': comp_rate,
            'competing_loss_pct': comp_loss,
            'measured_path_a_utilization_pct': utilization['A'],
            'measured_path_b_utilization_pct': utilization['B'],
            'final_path': policy_metrics['final_path'],
            'path_changes': policy_metrics['path_changes'],
            'decision_count': policy_metrics['decision_count'],
            'reaction_time_s': policy_metrics['reaction_time_s'],
            'recovery_time_s': recovery_time,
            'controller_poll_interval_ms': config.get('poll_ms', POLL_MS),
            'switching_threshold': config.get('threshold') if policy == 'C' else '',
            'minimum_dwell_time_ms': config.get('dwell_ms') if policy == 'C' else '',
            'experiment_status': status,
            'raw_log_ref': os.path.relpath(os.path.join(raw_dir, 'manifest.json'), PROJECT_ROOT),
            'git_commit': metadata['git_commit'],
            'git_dirty': metadata['git_dirty'],
            'notes': ' '.join(notes + error_notes),
        }

        path_active = {initial_path}
        if bursts and competing_path in ('A', 'B'):
            path_active.add(competing_path)
        expected_unused = {'A', 'B'} - path_active
        path_switch = {'A': 's2', 'B': 's3'}
        unexpected_unused = [
            switch for switch in path_switch.values()
            if any(
                counter_delta.get('port_counter_deltas', {}).get(f'{switch}:{port}:tx_packets', 0) > 0
                for port in ('LOCAL', f'{switch}-eth1', f'{switch}-eth2')
            ) and switch in {path_switch[path] for path in expected_unused}
        ]
        if unexpected_unused and policy == 'STATIC':
            row['experiment_status'] = 'failed'
            row['notes'] += f' Unexpected unused-path packet delta on {unexpected_unused}.'

        write_json(os.path.join(raw_dir, 'openflow_controller_summary.json'), {
            'ready_record': ready,
            'controller_policy_events': policy_metrics['events'],
            'path_utilization_samples': utilization_records,
            'path_counter_deltas': counter_delta,
            'udp_bursts': [
                {key: value for key, value in burst.items() if key != 'json'}
                for burst in bursts
            ],
            'link_failure_time_monotonic_s': link_failure_time,
            'alternative_path_first_tx_time_monotonic_s': alternate_path_first_tx_time,
            'queue_limit_verified': queue_observation['queue_limit_verified'],
            'ipv6_suppression_verified': ipv6.get('verified'),
        })

        # The controller owns these cookie values and should remove them during
        # its graceful close. Verify from root namespace dumps before stopping OVS.
        if controller and controller.poll() is None:
            controller.terminate()
            try:
                controller.wait(timeout=15)
            except subprocess.TimeoutExpired:
                controller.kill()
                controller.wait(timeout=5)
                row['experiment_status'] = 'failed'
                row['notes'] += ' Controller did not exit after SIGTERM within 15 s.'
        time.sleep(0.2)
        cleanup_flows = [
            write_root_flow_dump(raw_dir, switch, 'after_controller_exit')
            for switch in ('s1', 's2', 's3', 's4')
        ]
        write_json(os.path.join(raw_dir, 'controller_cookie_cleanup.json'), {
            'switches': cleanup_flows,
            'all_dumps_nonempty': all(item['nonempty'] for item in cleanup_flows),
            'remaining_smartte_cookie_entries': sum(
                item['smartte_cookie_entries'] for item in cleanup_flows
            ),
        })
        if not all(item['nonempty'] for item in cleanup_flows):
            row['experiment_status'] = 'failed'
            row['notes'] += ' Final flow dump missing on one or more switches.'
        elif sum(item['smartte_cookie_entries'] for item in cleanup_flows):
            row['experiment_status'] = 'failed'
            row['notes'] += ' SmartTE cookie-owned flows remained after controller exit.'

        stats_events = read_jsonl(controller_logs.get('events', ''))
        stats_rows = read_jsonl(controller_logs.get('stats', ''))
        poll_overhead = [
            {
                'cycle_id': event.get('cycle_id'),
                'poll_round_trip_s': event.get('poll_round_trip_s'),
                'controller_process_cpu_s': event.get('controller_process_cpu_s'),
                'decision_cpu_time_s': event.get('decision_cpu_time_s'),
            }
            for event in stats_events
        ]
        write_json(os.path.join(raw_dir, 'controller_overhead.json'), {
            'measurement_method': 'per-cycle process_time delta and OpenFlow request-to-last-reply monotonic interval logged by the controller',
            'poll_cycles': poll_overhead,
            'openflow_port_stat_record_count': len(stats_rows),
            'flow_mod_count_final': stats_events[-1].get('flow_mod_count_after') if stats_events else None,
        })
        with open(os.path.join(raw_dir, 'controller_overhead.csv'), 'w', newline='', encoding='utf-8') as output:
            overhead_fields = (
                'cycle_id', 'poll_round_trip_s', 'controller_process_cpu_s',
                'decision_cpu_time_s', 'flow_mod_count_after',
            )
            writer = csv.DictWriter(output, fieldnames=overhead_fields)
            writer.writeheader()
            for event in stats_events:
                writer.writerow({name: event.get(name, '') for name in overhead_fields})
        write_json(os.path.join(raw_dir, 'manifest.json'), {
            'scenario': scenario,
            'trial': trial_number,
            'raw_files': sorted(os.listdir(raw_dir)),
            'queue_config': queue_observation['queue_config'],
            'queue_limit_pkts': queue_observation['queue_limit_pkts'],
            'queue_limit_verified': queue_observation['queue_limit_verified'],
            'controller': 'OS-Ken 4.2.2 / Python 3.10.22 / OpenFlow 1.3',
            'policy_parameters': config,
            'path_utilization_definition': '(delta_tx_bytes * 8) / (actual OpenFlow counter interval * configured capacity) * 100',
            'utilization_counters_file': 'openflow_utilization_counters.json',
            'raw_log_ref': os.path.relpath(os.path.join(raw_dir, 'manifest.json'), PROJECT_ROOT),
        })

        with open(csv_path, 'a', newline='', encoding='utf-8') as output:
            csv.DictWriter(output, fieldnames=FIELDNAMES).writerow(row)
        return row
    except Exception as exc:
        status = 'failed'
        error_notes.append(f'{type(exc).__name__}: {exc}')
        row = make_failure_row(
            config, run_id, trial_number, metadata, raw_dir, status,
            ' '.join(error_notes), queue_observation,
        )
        with open(csv_path, 'a', newline='', encoding='utf-8') as output:
            csv.DictWriter(output, fieldnames=FIELDNAMES).writerow(row)
        write_json(os.path.join(raw_dir, 'failure.json'), {
            'error_type': type(exc).__name__,
            'error': str(exc),
            'queue_observation': queue_observation,
            'controller_logs': controller_logs,
        })
        return row
    finally:
        if net is not None:
            for host_name in ('h1', 'h2', 'h3', 'h4'):
                try:
                    net[host_name].cmd('killall -9 iperf3 ping 2>/dev/null')
                except Exception:
                    pass
            try:
                net.stop()
            except Exception:
                pass
        if controller is not None and controller.poll() is None:
            controller.terminate()
            try:
                controller.wait(timeout=15)
            except subprocess.TimeoutExpired:
                controller.kill()
                controller.wait(timeout=5)
        if controller_output is not None:
            controller_output.close()
        cleanup_previous()


def make_failure_row(config, run_id, trial, metadata, raw_dir, status, notes, queue):
    row = {name: '' for name in FIELDNAMES}
    row.update({
        'run_id': run_id,
        'experiment_id': config['experiment_id'],
        'timestamp_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'algorithm': config['policy'].lower(),
        'scenario': config['scenario'],
        'trial': trial,
        'flow_pair': 'h1-h2',
        'competing_pair': 'h3-h4' if (config.get('offered_rate_mbps', 0) or config.get('schedule')) else '',
        'initial_path': config['initial_path'],
        'competing_path': 'A' if (config.get('offered_rate_mbps', 0) or config.get('schedule')) else '',
        'offered_load_mbps': config.get('offered_rate_mbps', 0),
        'bottleneck_mbps': PATH_A_BW if config['initial_path'] == 'A' else PATH_B_BW,
        'delay_a_ms': 5.0,
        'delay_b_ms': 10.0,
        'queue_limit_pkts': queue.get('queue_limit_pkts'),
        'queue_config': queue.get('queue_config', 'NOT VERIFIED'),
        'tcp_duration_s': config.get('duration_s', ''),
        'final_path': config['initial_path'],
        'path_changes': 0 if config['policy'] == 'STATIC' else '',
        'decision_count': 0 if config['policy'] == 'STATIC' else '',
        'controller_poll_interval_ms': config.get('poll_ms', POLL_MS),
        'switching_threshold': config.get('threshold') if config['policy'] == 'C' else '',
        'minimum_dwell_time_ms': config.get('dwell_ms') if config['policy'] == 'C' else '',
        'experiment_status': status,
        'raw_log_ref': os.path.relpath(os.path.join(raw_dir, 'manifest.json'), PROJECT_ROOT),
        'git_commit': metadata['git_commit'],
        'git_dirty': metadata['git_dirty'],
        'notes': notes,
    })
    return row


def make_configs(mode, trials):
    configs = []
    if mode == 'static':
        for path in ('A', 'B'):
            for trial in range(1, trials + 1):
                configs.append(({
                    'experiment_id': 'M3-static-reproduction',
                    'scenario': f'primary_{path}_no_competition',
                    'policy': 'STATIC',
                    'initial_path': path,
                    'duration_s': 15,
                    'offered_rate_mbps': 0,
                    'poll_ms': POLL_MS,
                    'threshold': 15.0,
                    'dwell_ms': 5000,
                }, trial))
    elif mode == 'pilot':
        variants = [
            ('B', 1000, 15.0, 5000),
            ('C', 500, 15.0, 5000),
            ('C', 1000, 10.0, 2000),
            ('C', 1000, 15.0, 5000),
            ('C', 1000, 30.0, 10000),
        ]
        for policy, poll_ms, threshold, dwell in variants:
            configs.append(({
                'experiment_id': 'M4-short-pilot',
                'scenario': f'pilot_{policy}_poll{poll_ms}_margin{threshold:g}_dwell{dwell}',
                'policy': policy,
                'initial_path': 'A',
                'duration_s': 12,
                'offered_rate_mbps': 9,
                'load_start_s': 3,
                'poll_ms': poll_ms,
                'threshold': threshold,
                'dwell_ms': dwell,
            }, 1))
    elif mode == 'm5':
        # E1: no UDP competitor; same 15-second TCP window for all policies.
        for policy in ('STATIC', 'B', 'C'):
            configs.extend(({
                'experiment_id': 'E1-baseline',
                'scenario': f'E1_{policy}_no_competition',
                'policy': policy,
                'initial_path': 'A',
                'duration_s': 15,
                'offered_rate_mbps': 0,
                'poll_ms': POLL_MS,
                'threshold': 15.0,
                'dwell_ms': 5000,
            }, trial) for trial in range(1, trials + 1))

        # E2: static A/B references and controllers starting on A. UDP begins
        # five seconds into the TCP test, at either 5 or 9 Mbps.
        for rate in (5, 9):
            for policy, initial in (('STATIC', 'A'), ('STATIC', 'B'), ('B', 'A'), ('C', 'A')):
                configs.extend(({
                    'experiment_id': 'E2-congestion',
                    'scenario': f'E2_{policy}_initial{initial}_{rate}Mbps',
                    'policy': policy,
                    'initial_path': initial,
                    'duration_s': 20,
                    'offered_rate_mbps': rate,
                    'load_start_s': 5,
                    'poll_ms': POLL_MS,
                    'threshold': 15.0,
                    'dwell_ms': 5000,
                }, trial) for trial in range(1, trials + 1))

        # E3: three five-second Path A UDP bursts at 9 Mbps; test B and a
        # predeclared C sensitivity grid around the pilot default.
        e3_schedule = [(5, 9, 5), (15, 9, 5), (25, 9, 5)]
        e3_variants = [
            ('STATIC', 'A', 15.0, 5000),
            ('STATIC', 'B', 15.0, 5000),
            ('B', 'A', 15.0, 5000),
            ('C', 'A', 10.0, 5000),
            ('C', 'A', 15.0, 2000),
            ('C', 'A', 15.0, 5000),
            ('C', 'A', 15.0, 10000),
            ('C', 'A', 30.0, 5000),
        ]
        for policy, initial_path, threshold, dwell in e3_variants:
            configs.extend(({
                'experiment_id': 'E3-bursty',
                'scenario': f'E3_{policy}_initial{initial_path}_margin{threshold:g}_dwell{dwell}',
                'policy': policy,
                'initial_path': initial_path,
                'duration_s': 30,
                'offered_rate_mbps': 9,
                'schedule': e3_schedule,
                'poll_ms': POLL_MS,
                'threshold': threshold,
                'dwell_ms': dwell,
            }, trial) for trial in range(1, trials + 1))

        # E4: the Path A link is disabled one second after the shared TCP test
        # starts. Static remains pinned; B/C receive the same OpenFlow event.
        for policy in ('STATIC', 'B', 'C'):
            configs.extend(({
                'experiment_id': 'E4-link-failure',
                'scenario': f'E4_{policy}_PathA_down',
                'policy': policy,
                'initial_path': 'A',
                'duration_s': 15,
                'offered_rate_mbps': 0,
                'fail_path_a_at_s': 1,
                'poll_ms': POLL_MS,
                'threshold': 15.0,
                'dwell_ms': 5000,
            }, trial) for trial in range(1, trials + 1))
    else:
        raise ValueError(f'Unknown mode: {mode}')
    return configs


def interleave_trials(configs):
    """Run each scenario once per round, rotating order to reduce time drift."""
    grouped = {}
    experiment_order = []
    for config, trial in configs:
        experiment_id = config['experiment_id']
        if experiment_id not in grouped:
            grouped[experiment_id] = {}
            experiment_order.append(experiment_id)
        grouped[experiment_id].setdefault(trial, []).append((config, trial))

    result = []
    for experiment_id in experiment_order:
        rounds = grouped[experiment_id]
        for trial in sorted(rounds):
            scenarios = rounds[trial]
            offset = (trial - 1) % len(scenarios)
            result.extend(scenarios[offset:] + scenarios[:offset])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('static', 'pilot', 'm5'), required=True)
    parser.add_argument('--trials', type=int, default=5,
                        help='M3 static and M5 repetitions; pilot is one trial per pre-set variant.')
    args = parser.parse_args()
    if not os.path.isfile(CONTROLLER_PYTHON):
        raise SystemExit(
            f'Isolated controller interpreter not found: {CONTROLLER_PYTHON}. '
            'Set SMARTTE_CONTROLLER_PYTHON to its absolute path.'
        )
    timestamp = utc_stamp()
    run_id = f'{args.mode}_{timestamp}'
    experiment_name = {
        'static': 'm3_controller_static',
        'pilot': 'm4_pilot',
        'm5': 'm5_campaign',
    }[args.mode]
    raw_root = os.path.join(PROJECT_ROOT, 'results', 'raw', f'{experiment_name}_{timestamp}')
    os.makedirs(raw_root, exist_ok=True)
    csv_path = os.path.join(PROJECT_ROOT, 'results', 'raw', f'{experiment_name}_{timestamp}.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as output:
        csv.DictWriter(output, fieldnames=FIELDNAMES).writeheader()
    metadata = {
        'run_id': run_id,
        'experiment_mode': args.mode,
        'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'git_commit': get_git_commit(),
        'git_dirty': get_git_dirty(),
        'host_python': sys.version,
        'controller_python': CONTROLLER_PYTHON,
        'controller': 'OS-Ken 4.2.2 using Eventlet hub',
        'controller_openflow': '1.3',
        'topology': {
            'path_a_mbps': PATH_A_BW,
            'path_b_mbps': PATH_B_BW,
            'access_mbps': ACCESS_BW,
            'delay_access': ACCESS_DELAY,
            'delay_a': PATH_A_DELAY,
            'delay_b': PATH_B_DELAY,
            'queue_request_pkts': QUEUE_PKTS,
            'queue_method': 'Mininet max_queue_size; verified with tc on all 8 directed core interfaces',
            'static_arp': True,
            'ipv6_control_frames_disabled': True,
        },
        'telemetry': {
            'method': 'OS-Ken OpenFlow OFPPortStatsReply tx_bytes counter deltas',
            'poll_interval_ms': POLL_MS,
            'utilization_ports': {
                'A': 's2 port 2, egress toward s4',
                'B': 's3 port 2, egress toward s4',
            },
            'objective': 'maximum utilization among the two core egress links per path; controlled h1-h2 traffic is included',
        },
        'controller_parameters': {
            'poll_interval_ms': POLL_MS,
            'C_switching_threshold_pct_points': 15.0,
            'C_minimum_dwell_time_ms': 5000,
        },
        'csv_file': os.path.relpath(csv_path, PROJECT_ROOT),
        'raw_trial_directory': os.path.relpath(raw_root, PROJECT_ROOT),
    }
    write_json(os.path.join(raw_root, 'metadata.json'), metadata)
    configs = make_configs(args.mode, args.trials)
    if args.mode == 'm5':
        configs = interleave_trials(configs)
    summary_rows = []
    for index, (config, trial) in enumerate(configs, start=1):
        print(
            f'[{index}/{len(configs)}] {config["scenario"]} '
            f'trial={trial} policy={config["policy"]} path={config["initial_path"]}',
            flush=True,
        )
        row = run_one_trial(config, run_id, trial, csv_path, metadata, raw_root)
        summary_rows.append(row)
        print(
            f'  status={row["experiment_status"]} throughput={row["tcp_throughput_mbps"]} '
            f'rtt_avg={row["rtt_avg_ms"]} final_path={row["final_path"]} '
            f'changes={row["path_changes"]}',
            flush=True,
        )
    metadata['completed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata['row_count'] = len(summary_rows)
    metadata['status_counts'] = {
        status: sum(1 for row in summary_rows if row['experiment_status'] == status)
        for status in ('ok', 'failed', 'aborted', 'excluded')
    }
    write_json(os.path.join(raw_root, 'metadata.json'), metadata)
    print(json.dumps({
        'run_id': run_id,
        'csv': os.path.relpath(csv_path, PROJECT_ROOT),
        'raw_dir': os.path.relpath(raw_root, PROJECT_ROOT),
        'rows': len(summary_rows),
        'status_counts': metadata['status_counts'],
    }, indent=2))


if __name__ == '__main__':
    main()
