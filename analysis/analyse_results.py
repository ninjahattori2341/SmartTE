#!/usr/bin/env python3
"""Summarize a SmartTE M5 CSV and its per-trial raw evidence."""

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[1]
SUMMARY_GROUPS = ['experiment_id', 'scenario', 'algorithm']
METRICS = [
    'tcp_throughput_mbps', 'rtt_avg_ms', 'p95_rtt_ms', 'ping_loss_pct',
    'competing_achieved_mbps', 'competing_loss_pct',
    'measured_path_a_utilization_pct', 'measured_path_b_utilization_pct',
    'path_changes', 'decision_count', 'reaction_time_s', 'recovery_time_s',
]


def latest_complete_csv():
    candidates = sorted(
        (ROOT / 'results/raw').glob('m5_campaign_*.csv'),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        metadata_path = path.parent / path.stem / 'metadata.json'
        if not metadata_path.exists():
            continue
        try:
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        if metadata.get('row_count') == 110:
            return path
    raise FileNotFoundError(
        'No completed 110-row M5 campaign found. Supply --csv to analyze a partial run.'
    )


def resolve_csv(value):
    path = Path(value).resolve() if value else latest_complete_csv()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def confidence_interval(values):
    clean = pd.to_numeric(values, errors='coerce').dropna().to_numpy(dtype=float)
    n = len(clean)
    if not n:
        return {'mean': np.nan, 'sd': np.nan, 'n': 0, 'ci95_low': np.nan, 'ci95_high': np.nan}
    mean = float(np.mean(clean))
    sd = float(np.std(clean, ddof=1)) if n > 1 else np.nan
    if n > 1:
        margin = float(student_t.ppf(0.975, df=n - 1) * sd / math.sqrt(n))
        low, high = mean - margin, mean + margin
    else:
        low, high = np.nan, np.nan
    return {'mean': mean, 'sd': sd, 'n': n, 'ci95_low': low, 'ci95_high': high}


def read_jsonl(path):
    try:
        records = []
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records
    except OSError:
        return []


def build_path_change_audit(df):
    """Compare raw path-change cells with successful changes in event logs."""
    records = []
    for _, row in df.iterrows():
        trial_dir = resolve_trial_dir(row.get('raw_log_ref'))
        events = read_jsonl(trial_dir / 'controller_events.jsonl') if trial_dir else []
        counts = [
            int(event['path_changes_total'])
            for event in events
            if isinstance(event.get('path_changes_total'), (int, float))
        ]
        event_count = max(counts) if counts else None
        raw_count = pd.to_numeric(pd.Series([row.get('path_changes')]), errors='coerce').iloc[0]
        actual_count = event_count if event_count is not None else raw_count
        attempts = [event for event in events if event.get('decision') == 'switch']
        rejected = [
            event for event in attempts
            if event.get('flow_mod_install_succeeded') is False
        ]

        failure = read_json(trial_dir / 'link_failure_event.json') if trial_dir else None
        failure_time = failure.get('time_monotonic_s') if failure else None
        timed_events = sorted(
            (event for event in events if isinstance(event.get('time_monotonic_s'), (int, float))),
            key=lambda event: event['time_monotonic_s'],
        )
        first_event_time = timed_events[0]['time_monotonic_s'] if timed_events else None
        first_change = next((
            event for event in timed_events
            if event.get('path_before') in ('A', 'B')
            and event.get('path_after') in ('A', 'B')
            and event.get('path_before') != event.get('path_after')
            and int(event.get('path_changes_total') or 0) > 0
        ), None)
        at_failure = [
            event for event in timed_events
            if failure_time is not None
            and event['time_monotonic_s'] <= failure_time
            and event.get('path_after') in ('A', 'B')
        ]
        path_at_failure = at_failure[-1].get('path_after') if at_failure else (
            row.get('initial_path') if failure_time is not None else ''
        )
        mismatch = (
            event_count is not None and pd.notna(raw_count)
            and int(event_count) != int(raw_count)
        )
        records.append({
            'run_id': row.get('run_id'),
            'experiment_id': row.get('experiment_id'),
            'scenario': row.get('scenario'),
            'algorithm': row.get('algorithm'),
            'trial': row.get('trial'),
            'experiment_status': row.get('experiment_status'),
            'raw_csv_path_changes': raw_count,
            'successful_path_changes': actual_count,
            'successful_path_changes_from_event_log': event_count is not None,
            'switch_decision_attempts': len(attempts),
            'rejected_switch_attempts': len(rejected),
            'raw_count_matches_event_counter': not mismatch if event_count is not None else '',
            'link_failure_time_monotonic_s': failure_time if failure_time is not None else '',
            'first_event_time_monotonic_s': first_event_time if first_event_time is not None else '',
            'path_at_link_failure': path_at_failure,
            'first_successful_change_before_link_failure': (
                first_change['time_monotonic_s'] < failure_time
                if first_change and failure_time is not None else ''
            ),
            'raw_log_ref': row.get('raw_log_ref'),
        })
    return pd.DataFrame(records)


def summarize(df, path_change_audit=None):
    successful_changes = {}
    if path_change_audit is not None and not path_change_audit.empty:
        successful_changes = dict(zip(
            path_change_audit['raw_log_ref'],
            path_change_audit['successful_path_changes'],
        ))
    rows = []
    for keys, group in df.groupby(SUMMARY_GROUPS, dropna=False, sort=False):
        # A row is in the metric summary only when the runner marked the trial ok.
        # Expected static outage rows in E4 remain visible in e4_outcomes.csv.
        valid = group[group['experiment_status'].eq('ok')].copy()
        for metric in METRICS:
            if metric not in valid:
                continue
            if metric == 'path_changes' and successful_changes:
                event_values = valid['raw_log_ref'].map(successful_changes)
                valid[metric] = pd.to_numeric(event_values, errors='coerce').fillna(
                    pd.to_numeric(valid[metric], errors='coerce')
                )
            stats = confidence_interval(valid[metric])
            rows.append({
                **dict(zip(SUMMARY_GROUPS, keys)),
                'metric': metric,
                **stats,
            })
    return pd.DataFrame(rows)


def resolve_trial_dir(raw_ref):
    if not isinstance(raw_ref, str) or not raw_ref:
        return None
    path = (ROOT / raw_ref).resolve()
    return path.parent if path.suffix.lower() == '.json' else path


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def build_quality_table(df):
    records = []
    overhead_frames = []
    for _, row in df.iterrows():
        trial_dir = resolve_trial_dir(row.get('raw_log_ref'))
        manifest = read_json(trial_dir / 'manifest.json') if trial_dir else None
        cleanup = read_json(trial_dir / 'controller_cookie_cleanup.json') if trial_dir else None
        ping_path = trial_dir / 'primary_ping.txt' if trial_dir else None
        duplicate = bool(
            ping_path and ping_path.exists()
            and 'DUP!' in ping_path.read_text(encoding='utf-8', errors='replace')
        )
        notes = str(row.get('notes', ''))
        queue_verified = bool(manifest and manifest.get('queue_limit_verified'))
        cleanup_verified = bool(
            cleanup and cleanup.get('all_dumps_nonempty')
            and cleanup.get('remaining_smartte_cookie_entries') == 0
        ) if str(row.get('algorithm', '')).lower() != 'static' or (trial_dir and (trial_dir / 'controller_cookie_cleanup.json').exists()) else None
        missing = []
        if pd.isna(row.get('tcp_throughput_mbps')) and not ('E4' in str(row.get('experiment_id')) and str(row.get('algorithm')).lower() == 'static'):
            missing.append('tcp_throughput_mbps')
        if pd.isna(row.get('ping_loss_pct')):
            missing.append('ping_loss_pct')
        quality = {
            'run_id': row.get('run_id'),
            'experiment_id': row.get('experiment_id'),
            'scenario': row.get('scenario'),
            'algorithm': row.get('algorithm'),
            'trial': row.get('trial'),
            'experiment_status': row.get('experiment_status'),
            'queue_verified': queue_verified,
            'queue_limit_pkts_observed': manifest.get('queue_limit_pkts') if manifest else '',
            'duplicate_ping_reply': duplicate,
            'controller_cookie_cleanup_verified': cleanup_verified,
            'missing_core_measurements': ';'.join(missing),
            'notes': notes,
            'raw_log_ref': row.get('raw_log_ref'),
        }
        records.append(quality)
        overhead_path = trial_dir / 'controller_overhead.csv' if trial_dir else None
        if overhead_path and overhead_path.exists():
            try:
                overhead = pd.read_csv(overhead_path)
                if not overhead.empty:
                    overhead['experiment_id'] = row.get('experiment_id')
                    overhead['scenario'] = row.get('scenario')
                    overhead['algorithm'] = row.get('algorithm')
                    overhead['trial'] = row.get('trial')
                    overhead_frames.append(overhead)
            except (OSError, pd.errors.ParserError):
                pass
    quality_df = pd.DataFrame(records)
    overhead_df = pd.concat(overhead_frames, ignore_index=True) if overhead_frames else pd.DataFrame()
    return quality_df, overhead_df


def build_matrix(df):
    rows = []
    for keys, group in df.groupby(SUMMARY_GROUPS, dropna=False, sort=False):
        first = group.iloc[0]
        rows.append({
            **dict(zip(SUMMARY_GROUPS, keys)),
            'initial_path': first.get('initial_path'),
            'competing_path': first.get('competing_path'),
            'offered_load_mbps': first.get('offered_load_mbps'),
            'tcp_duration_s': first.get('tcp_duration_s'),
            'switching_threshold': first.get('switching_threshold'),
            'minimum_dwell_time_ms': first.get('minimum_dwell_time_ms'),
            'attempted_rows': len(group),
            'ok_rows': int(group['experiment_status'].eq('ok').sum()),
            'failed_rows': int(group['experiment_status'].eq('failed').sum()),
            'excluded_rows': int(group['experiment_status'].eq('excluded').sum()),
            'aborted_rows': int(group['experiment_status'].eq('aborted').sum()),
        })
    return pd.DataFrame(rows)


def build_e4_outcomes(df, path_change_audit=None):
    e4 = df[df['experiment_id'].astype(str).str.startswith('E4')]
    audit = path_change_audit[
        path_change_audit['experiment_id'].astype(str).str.startswith('E4')
    ] if path_change_audit is not None and not path_change_audit.empty else pd.DataFrame()
    rows = []
    for algorithm, group in e4.groupby('algorithm', dropna=False, sort=False):
        throughput = pd.to_numeric(group['tcp_throughput_mbps'], errors='coerce')
        ping_loss = pd.to_numeric(group['ping_loss_pct'], errors='coerce')
        group_refs = set(group['raw_log_ref'].astype(str))
        audit_group = audit[audit['raw_log_ref'].astype(str).isin(group_refs)] if not audit.empty else pd.DataFrame()
        changes = pd.to_numeric(
            audit_group['successful_path_changes'] if not audit_group.empty else group['path_changes'],
            errors='coerce',
        ).fillna(0)
        recovery = pd.to_numeric(group['recovery_time_s'], errors='coerce')
        rows.append({
            'algorithm': algorithm,
            'trials': len(group),
            'ok_rows': int(group['experiment_status'].eq('ok').sum()),
            'failed_rows': int(group['experiment_status'].eq('failed').sum()),
            'throughput_measurements': int(throughput.notna().sum()),
            'ping_loss_mean_pct': float(ping_loss.mean()) if ping_loss.notna().any() else np.nan,
            'path_changes_mean': float(changes.mean()),
            'trials_with_reroute': int((changes > 0).sum()),
            'raw_csv_path_changes_mean': float(pd.to_numeric(group['path_changes'], errors='coerce').mean()),
            'switch_decision_attempts_mean': float(pd.to_numeric(audit_group['switch_decision_attempts'], errors='coerce').mean()) if not audit_group.empty else np.nan,
            'rejected_switch_attempts_mean': float(pd.to_numeric(audit_group['rejected_switch_attempts'], errors='coerce').mean()) if not audit_group.empty else np.nan,
            'trials_on_path_b_at_link_failure': int(audit_group['path_at_link_failure'].eq('B').sum()) if not audit_group.empty else 0,
            'trials_changed_before_link_failure': int(audit_group['first_successful_change_before_link_failure'].eq(True).sum()) if not audit_group.empty else 0,
            'recovery_measurements': int(recovery.notna().sum()),
            'recovery_mean_s': float(recovery.mean()) if recovery.notna().any() else np.nan,
        })
    return pd.DataFrame(rows)


def analyze(csv_path, output_dir=None):
    df = pd.read_csv(csv_path)
    out = Path(output_dir).resolve() if output_dir else ROOT / 'results/processed' / csv_path.stem
    out.mkdir(parents=True, exist_ok=True)
    path_change_audit = build_path_change_audit(df)
    metrics = summarize(df, path_change_audit)
    quality, overhead = build_quality_table(df)
    matrix = build_matrix(df)
    e4 = build_e4_outcomes(df, path_change_audit)
    metrics.to_csv(out / 'metrics_summary.csv', index=False)
    quality.to_csv(out / 'data_quality.csv', index=False)
    matrix.to_csv(out / 'experiment_matrix.csv', index=False)
    e4.to_csv(out / 'e4_outcomes.csv', index=False)
    path_change_audit.to_csv(out / 'path_change_audit.csv', index=False)
    if not overhead.empty:
        overhead.to_csv(out / 'controller_overhead_samples.csv', index=False)
        overhead_summary = []
        for keys, group in overhead.groupby(['experiment_id', 'scenario', 'algorithm'], dropna=False, sort=False):
            record = dict(zip(['experiment_id', 'scenario', 'algorithm'], keys))
            record['poll_cycles'] = len(group)
            for column in ('poll_round_trip_s', 'controller_process_cpu_s', 'decision_cpu_time_s'):
                record[f'{column}_mean'] = pd.to_numeric(group[column], errors='coerce').mean()
                record[f'{column}_p95'] = pd.to_numeric(group[column], errors='coerce').quantile(0.95)
            overhead_summary.append(record)
        pd.DataFrame(overhead_summary).to_csv(out / 'controller_overhead_summary.csv', index=False)
    status_counts = df['experiment_status'].value_counts(dropna=False).to_dict()
    expected_rows = {'E1-baseline': 15, 'E2-congestion': 40, 'E3-bursty': 40, 'E4-link-failure': 15}
    observed_rows = df['experiment_id'].value_counts(dropna=False).to_dict()
    metadata = {
        'input_csv': str(csv_path.relative_to(ROOT)) if csv_path.is_relative_to(ROOT) else str(csv_path),
        'input_sha256': hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'row_count': len(df),
        'status_counts': {str(k): int(v) for k, v in status_counts.items()},
        'observed_rows_by_experiment': {str(k): int(v) for k, v in observed_rows.items()},
        'expected_rows_by_experiment': expected_rows,
        'complete_expected_matrix': len(df) == 110 and all(observed_rows.get(k, 0) == v for k, v in expected_rows.items()),
        'confidence_interval': 'two-sided 95% Student t interval: mean +/- t(0.975, n-1) * sample_sd/sqrt(n); descriptive, no hypothesis significance test',
        'metric_aggregation': 'Only experiment_status=ok rows enter the generic metric summaries; E4 outcomes retain all rows separately. Path-change summaries use successful controller event path_changes_total counters where available; raw CSV decision counts remain in path_change_audit.csv.',
        'path_change_provenance': 'Raw CSV path_changes can count switch decisions rejected because a path is unavailable. Processed path_changes uses controller event path_changes_total when present and preserves raw values in path_change_audit.csv.',
        'output_dir': str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else str(out),
    }
    (out / 'analysis_metadata.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return df, metrics, quality, matrix, out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', help='M5 raw CSV; default is the newest complete 110-row campaign.')
    parser.add_argument('--out', help='Output directory; default results/processed/<CSV stem>.')
    args = parser.parse_args()
    csv_path = resolve_csv(args.csv)
    _, metrics, quality, matrix, out = analyze(csv_path, args.out)
    print(f'Input: {csv_path.relative_to(ROOT) if csv_path.is_relative_to(ROOT) else csv_path}')
    print(f'Rows: {len(pd.read_csv(csv_path))}; output: {out}')
    print(f'Experiment matrix rows: {len(matrix)}; metric summary rows: {len(metrics)}; data-quality rows: {len(quality)}')
    print((out / 'analysis_metadata.json').read_text(encoding='utf-8'))


if __name__ == '__main__':
    main()
