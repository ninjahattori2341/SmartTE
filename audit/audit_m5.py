#!/usr/bin/env python3
"""Read-only audit of the M5 campaign CSV. Writes only to audit/."""
import re, math
from pathlib import Path
import pandas as pd

CSV = Path("results/raw/m5_campaign_20261011T115819Z.csv")
df = pd.read_csv(CSV)
pd.set_option("display.width", 220, "display.max_columns", 60, "display.max_rows", 200)

def col(*names):
    return next((n for n in names if n in df.columns), None)

exp, status, alg, scn = col("experiment_id"), col("experiment_status"), col("algorithm"), col("scenario")
print("COLUMNS:", list(df.columns))
print("ROWS:", len(df), "(expect 110)")
if exp:
    e = df[exp].astype(str).str.extract(r"^(E\d)")[0]
    print("\nPER EXPERIMENT (expect E1 15, E2 40, E3 40, E4 15):\n", e.value_counts().sort_index())
if status:
    print("\nSTATUS:\n", df[status].value_counts())
    print("\nNON-OK ROWS:\n", df[df[status] != "ok"][[c for c in [exp, alg, scn, "trial", status, "notes", "raw_log_ref"] if c]])
    if exp and alg:
        print("\nEXPERIMENT x ALGORITHM x STATUS:\n", df.groupby([e, alg, status]).size())
print("\nDUPLICATE run_id:", df["run_id"].duplicated().sum() if "run_id" in df else "n/a")

if "raw_log_ref" in df:
    miss = [r for r in df["raw_log_ref"].dropna() if not Path(str(r)).exists()]
    print("raw_log_ref missing on disk:", len(miss), miss[:5])

for c, lo, hi in [("tcp_throughput_mbps", 0, 11), ("ping_loss_pct", 0, 100), ("measured_path_a_utilization_pct", 0, 110)]:
    if c in df:
        print(f"{c} outside [{lo},{hi}]:", int(((df[c] < lo) | (df[c] > hi)).sum()))

if "git_commit" in df:
    print("\ngit_commit values:", df["git_commit"].value_counts().to_dict())
if "git_dirty" in df:
    print("git_dirty values:", df["git_dirty"].value_counts().to_dict())

# fairness: config columns should be constant within an experiment across algorithms
cfg = [c for c in ["queue_limit_pkts", "bottleneck_mbps", "delay_a_ms", "delay_b_ms", "tcp_duration_s", "offered_load_mbps", "controller_poll_interval_ms"] if c in df]
if exp and cfg:
    print("\nCONFIG VALUES PER EXPERIMENT x ALGORITHM:")
    print(df.groupby([e, alg])[cfg].agg(lambda s: sorted(set(s.dropna().astype(str)))))

# frozen parameters on C rows
if alg:
    C = df[df[alg].astype(str).str.upper() == "C"]
    for c in ["controller_poll_interval_ms", "switching_threshold", "minimum_dwell_time_ms"]:
        if c in C:
            print(f"C rows {c}:", C[c].value_counts(dropna=False).to_dict())

metrics = [c for c in ["tcp_throughput_mbps", "rtt_avg_ms", "p95_rtt_ms", "ping_loss_pct", "path_changes", "decision_count", "reaction_time_s", "recovery_time_s"] if c in df]
ok = df[df[status] == "ok"] if status else df
if exp and alg and scn:
    g = ok.groupby([ok[exp], ok[scn], ok[alg]])[metrics].agg(["count", "mean", "std"]).round(3)
    g.to_csv("audit/summary_by_group.csv")
    print("\nSUMMARY (full table in audit/summary_by_group.csv):\n", g)

def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (max(0, c-h)*100, min(1, c+h)*100)

rows = []
for _, r in ok.iterrows():
    ref = r.get("raw_log_ref")
    if pd.isna(ref):
        continue
    p = Path(str(ref))
    files = [p] if p.is_file() else (sorted(p.glob("*ping*")) if p.exists() else [])
    for f in files:
        m = re.search(r"(\d+) packets transmitted, (\d+) (?:packets )?received", f.read_text(errors="ignore"))
        if m:
            tx, rx = int(m[1]), int(m[2])
            rows.append(dict(group=f"{r.get(exp)}|{r.get(scn)}|{r.get(alg)}", tx=tx, lost=tx-rx))
            break
if rows:
    w = pd.DataFrame(rows).groupby("group")[["tx", "lost"]].sum()
    w["loss_pct"] = 100 * w["lost"] / w["tx"]
    w[["wilson_lo", "wilson_hi"]] = [wilson(k, n) for k, n in zip(w["lost"], w["tx"])]
    w.round(3).to_csv("audit/loss_wilson_pooled.csv")
    print("\nPOOLED LOSS + WILSON 95% CI (pings treated as independent: optimistic):\n", w.round(3))
else:
    print("\nNo ping files parsed from raw_log_ref; paste one raw_log_ref value so I can adapt this.")
