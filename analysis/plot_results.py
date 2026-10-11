#!/usr/bin/env python3
"""Create figures from the reproducible SmartTE analysis tables and raw counters."""

import argparse
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analyse_results import ROOT, analyze, resolve_csv

COLORS = {'static': '#52657a', 'b': '#df7a25', 'c': '#197a72'}
LABELS = {'static': 'Static', 'b': 'B', 'c': 'C'}


def save_figure(fig, out_dir, name):
    fig.savefig(out_dir / f'{name}.png', dpi=300, bbox_inches='tight')
    fig.savefig(out_dir / f'{name}.pdf', bbox_inches='tight')
    plt.close(fig)


def shorten_scenario(value):
    value = str(value)
    for prefix in ('E1_', 'E2_', 'E3_', 'E4_'):
        value = value.replace(prefix, '')
    value = value.replace('initial', 'init')
    value = value.replace('no_competition', 'no load')
    value = value.replace('Mbps', ' Mb/s')
    value = value.replace('margin', 'm').replace('_dwell', ' / d')
    value = value.replace('_PathA_down', ' A down')
    return value


def plot_metric_by_scenario(summary, experiment_id, metric, title, ylabel, out_dir, name):
    data = summary[
        summary['experiment_id'].eq(experiment_id)
        & summary['metric'].eq(metric)
        & summary['n'].gt(0)
    ].copy()
    if data.empty:
        return
    data['label'] = data['scenario'].map(shorten_scenario)
    fig, ax = plt.subplots(figsize=(max(9, len(data) * 1.1), 5.7))
    x = np.arange(len(data))
    means = pd.to_numeric(data['mean'], errors='coerce').to_numpy(dtype=float)
    low = pd.to_numeric(data['ci95_low'], errors='coerce').to_numpy(dtype=float)
    high = pd.to_numeric(data['ci95_high'], errors='coerce').to_numpy(dtype=float)
    lower_error = np.where(np.isfinite(low), np.maximum(0, means - low), 0)
    upper_error = np.where(np.isfinite(high), np.maximum(0, high - means), 0)
    colors = [COLORS.get(str(policy).lower(), '#777777') for policy in data['algorithm']]
    bars = ax.bar(x, means, color=colors, edgecolor='white', linewidth=0.5, width=0.72)
    ax.errorbar(x, means, yerr=np.vstack([lower_error, upper_error]), fmt='none',
                ecolor='#222222', capsize=3, linewidth=1)
    for bar, n in zip(bars, data['n']):
        if n:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f'n={int(n)}',
                    ha='center', va='bottom', fontsize=8, rotation=0)
    ax.set_xticks(x, data['label'], rotation=33, ha='right')
    ax.set_title(title)
    ax.set_ylabel(ylabel)
    ax.set_xlabel('Scenario (bar color identifies policy)')
    ax.grid(axis='y', alpha=0.25)
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[k], label=LABELS[k]) for k in ('static', 'b', 'c')]
    shown = set(data['algorithm'].astype(str).str.lower())
    handles = [h for h in handles if h.get_label().lower() in shown or (h.get_label() == 'Static' and 'static' in shown)]
    if handles:
        ax.legend(handles=handles, frameon=False)
    fig.tight_layout()
    save_figure(fig, out_dir, name)


def plot_throughput(summary, out_dir):
    exp_titles = {
        'E1-baseline': 'E1 · no competing load',
        'E2-congestion': 'E2 · sustained congestion',
        'E3-bursty': 'E3 · burst schedule and C sensitivity',
        'E4-link-failure': 'E4 · Path A link failure (diagnostic outcomes)',
    }
    data = summary[summary['metric'].eq('tcp_throughput_mbps')]
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    for ax, (experiment, title) in zip(axes.flat, exp_titles.items()):
        group = data[data['experiment_id'].eq(experiment)].copy()
        group = group[group['n'].gt(0)]
        if group.empty:
            ax.set_visible(False)
            continue
        group['label'] = group['scenario'].map(shorten_scenario)
        x = np.arange(len(group))
        means = pd.to_numeric(group['mean'], errors='coerce').to_numpy(dtype=float)
        low = pd.to_numeric(group['ci95_low'], errors='coerce').to_numpy(dtype=float)
        high = pd.to_numeric(group['ci95_high'], errors='coerce').to_numpy(dtype=float)
        error = np.vstack([
            np.where(np.isfinite(low), np.maximum(0, means - low), 0),
            np.where(np.isfinite(high), np.maximum(0, high - means), 0),
        ])
        colors = [COLORS.get(str(policy).lower(), '#777777') for policy in group['algorithm']]
        ax.bar(x, means, color=colors, width=0.72)
        ax.errorbar(x, means, yerr=error, fmt='none', ecolor='#222222', capsize=3, linewidth=1)
        ax.set_xticks(x, group['label'], rotation=50, ha='right', fontsize=8)
        ax.set_title(title)
        ax.set_ylabel('TCP receiver throughput (Mbps)')
        ax.grid(axis='y', alpha=0.25)
        if experiment == 'E4-link-failure':
            ax.text(
                0.02, 0.97,
                'Static Path A: no TCP result in 5/5 trials; see E4 event audit for route state at failure.',
                transform=ax.transAxes, va='top', ha='left', fontsize=8,
                bbox={'facecolor': 'white', 'edgecolor': '#bbbbbb', 'alpha': 0.9},
            )
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLORS[k], label=LABELS[k]) for k in ('static', 'b', 'c')]
    fig.suptitle('TCP receiver throughput by experiment and policy\nBars show means; whiskers show descriptive 95% Student-t intervals', y=0.995)
    fig.legend(handles=handles, loc='upper center', bbox_to_anchor=(0.5, 0.94), ncol=3, frameon=False)
    fig.tight_layout(rect=[0, 0, 1, 0.90])
    save_figure(fig, out_dir, 'throughput_by_scenario')


def plot_rtt(summary, out_dir):
    for metric, title, filename in (
        ('rtt_avg_ms', 'E2 mean ping RTT by scenario', 'e2_rtt_mean'),
        ('p95_rtt_ms', 'E2 95th-percentile ping RTT by scenario', 'e2_rtt_p95'),
    ):
        plot_metric_by_scenario(
            summary, 'E2-congestion', metric, title,
            'Ping RTT (ms)', out_dir, filename,
        )


def plot_path_changes(raw, out_dir):
    data = raw[raw['experiment_id'].isin(['E1-baseline', 'E2-congestion', 'E3-bursty'])].copy()
    data = data[data['algorithm'].astype(str).str.lower().isin(['b', 'c'])]
    data = data[data['experiment_status'].eq('ok')]
    data['path_changes'] = pd.to_numeric(data['path_changes'], errors='coerce')
    if data.empty:
        return
    fig, ax = plt.subplots(figsize=(10, 6))
    positions = {'b': 0, 'c': 1}
    for algorithm, group in data.groupby(data['algorithm'].astype(str).str.lower()):
        x_base = positions[algorithm]
        jitter = np.linspace(-0.12, 0.12, len(group)) if len(group) > 1 else np.array([0.0])
        ax.scatter(x_base + jitter, group['path_changes'], s=38, alpha=0.7,
                   color=COLORS[algorithm], label=LABELS[algorithm])
        mean = group['path_changes'].mean()
        ax.plot([x_base - 0.23, x_base + 0.23], [mean, mean], color='#222222', linewidth=2)
    ax.set_xticks([0, 1], ['Algorithm B', 'Algorithm C'])
    ax.set_ylabel('Path changes per trial')
    ax.set_title('Observed path changes across E1–E3 trials')
    ax.grid(axis='y', alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()
    save_figure(fig, out_dir, 'path_changes_b_vs_c')


def plot_c_sensitivity(summary, out_dir):
    data = summary[
        summary['experiment_id'].eq('E3-bursty')
        & summary['algorithm'].astype(str).str.lower().eq('c')
        & summary['metric'].isin(['path_changes', 'tcp_throughput_mbps'])
    ].copy()
    if data.empty:
        return
    parts = data['scenario'].str.extract(r'margin(?P<margin>[0-9.]+)_dwell(?P<dwell>[0-9]+)')
    data['margin'] = parts['margin']
    data['dwell'] = pd.to_numeric(parts['dwell'], errors='coerce') / 1000
    data['label'] = data.apply(lambda r: f"{r['margin']} pp / {r['dwell']:g} s", axis=1)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    for ax, metric, ylabel, title in (
        (axes[0], 'path_changes', 'Path changes per 30-second trial', 'C path changes'),
        (axes[1], 'tcp_throughput_mbps', 'TCP receiver throughput (Mbps)', 'C throughput'),
    ):
        group = data[data['metric'].eq(metric)].copy()
        group = group[group['n'].gt(0)]
        if group.empty:
            ax.set_visible(False)
            continue
        x = np.arange(len(group))
        y = pd.to_numeric(group['mean'], errors='coerce').to_numpy(dtype=float)
        low = pd.to_numeric(group['ci95_low'], errors='coerce').to_numpy(dtype=float)
        high = pd.to_numeric(group['ci95_high'], errors='coerce').to_numpy(dtype=float)
        errors = np.vstack([
            np.where(np.isfinite(low), np.maximum(0, y - low), 0),
            np.where(np.isfinite(high), np.maximum(0, high - y), 0),
        ])
        ax.errorbar(x, y, yerr=errors, marker='o', capsize=3, color=COLORS['c'], linewidth=1.5)
        ax.set_xticks(x, group['label'], rotation=35, ha='right')
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.25)
    fig.suptitle('E3 C sensitivity: switching margin and minimum dwell')
    fig.tight_layout()
    save_figure(fig, out_dir, 'c_margin_dwell_sensitivity')


def read_jsonl(path):
    records = []
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return records


def plot_utilization_timeseries(raw, csv_path, out_dir):
    e3 = raw[raw['experiment_id'].eq('E3-bursty')]
    candidates = {}
    for algorithm in ('B', 'C'):
        eligible = e3[e3['algorithm'].astype(str).str.upper().eq(algorithm)]
        if algorithm == 'C':
            eligible = eligible[eligible['scenario'].str.contains('margin15_dwell5000', regex=False)]
        if not eligible.empty:
            candidates[algorithm] = eligible.iloc[0]
    if not candidates:
        return

    fig, axes = plt.subplots(len(candidates), 1, figsize=(11, 4.8 * len(candidates)), sharex=False)
    if len(candidates) == 1:
        axes = [axes]
    raw_root = ROOT / 'results/raw' / csv_path.stem
    for ax, (algorithm, row) in zip(axes, candidates.items()):
        raw_ref = Path(str(row['raw_log_ref']))
        trial_dir = (ROOT / raw_ref).resolve().parent
        stats = read_jsonl(trial_dir / 'controller_port_stats.jsonl')
        switches = read_jsonl(trial_dir / 'controller_events.jsonl')
        selected = [
            item for item in stats
            if item.get('status') == 'ok'
            and (item.get('switch'), item.get('port_no')) in (('s2', 2), ('s3', 2))
            and isinstance(item.get('utilization_pct'), (int, float))
        ]
        if not selected:
            ax.text(0.5, 0.5, f'No valid port-stat series for {algorithm}', ha='center', va='center', transform=ax.transAxes)
            continue
        origin = min(item['time_monotonic_s'] for item in selected)
        for switch, port, path_name, color in (
            ('s2', 2, 'Path A · s2 port 2', '#2667a8'),
            ('s3', 2, 'Path B · s3 port 2', '#d77a22'),
        ):
            series = sorted(
                (item for item in selected if item.get('switch') == switch and int(item.get('port_no', -1)) == port),
                key=lambda item: item['time_monotonic_s'],
            )
            if series:
                ax.plot(
                    [item['time_monotonic_s'] - origin for item in series],
                    [item['utilization_pct'] for item in series],
                    color=color, label=path_name, linewidth=1.2,
                )
        switch_marked = False
        for event in switches:
            timestamp = event.get('flow_mod_timestamp_monotonic_s')
            if event.get('decision') == 'switch' and isinstance(timestamp, (int, float)):
                ax.axvline(timestamp - origin, color='#a33a3a', linestyle='--', alpha=0.65,
                           label='Path-change FlowMod' if not switch_marked else None)
                switch_marked = True
        ax.set_title(f"{algorithm} · {row['scenario']} · trial {row['trial']}")
        ax.set_ylabel('Counter utilization (%)')
        ax.set_xlabel('Seconds from first valid OpenFlow port sample')
        ax.grid(alpha=0.25)
        ax.legend(frameon=False, ncol=3)
    fig.suptitle('E3 Path A/B utilization time series with controller switch events', y=1.01)
    fig.tight_layout()
    save_figure(fig, out_dir, 'e3_utilization_timeseries_switches')


def plot_reaction_time(summary, out_dir):
    plot_metric_by_scenario(
        summary, 'E2-congestion', 'reaction_time_s',
        'E2 time from UDP onset to path-change FlowMod',
        'Reaction time (s)', out_dir, 'e2_reaction_time',
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', help='M5 raw CSV; default is newest completed 110-row campaign.')
    parser.add_argument('--out', help='Processed output directory; defaults to results/processed/<CSV stem>.')
    args = parser.parse_args()
    csv_path = resolve_csv(args.csv)
    raw, summary, _, _, out = analyze(csv_path, args.out)
    plt.rcParams.update({
        'font.family': 'DejaVu Sans',
        'font.size': 9,
        'axes.titlesize': 11,
        'axes.labelsize': 9,
        'legend.fontsize': 8,
        'figure.dpi': 150,
        'pdf.fonttype': 42,
        'ps.fonttype': 42,
    })
    figure_dir = out / 'figures'
    figure_dir.mkdir(parents=True, exist_ok=True)
    plot_throughput(summary, figure_dir)
    plot_rtt(summary, figure_dir)
    plot_path_changes(raw, figure_dir)
    plot_c_sensitivity(summary, figure_dir)
    plot_utilization_timeseries(raw, csv_path, figure_dir)
    plot_reaction_time(summary, figure_dir)
    print(f'Figures written to {figure_dir}')


if __name__ == '__main__':
    main()
