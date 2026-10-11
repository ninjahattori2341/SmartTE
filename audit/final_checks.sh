#!/usr/bin/env bash
cd ~/smartte
echo "### sudo check"; sudo -k; sudo -n true 2>/dev/null && echo "STILL ON" || echo "passwordless sudo OFF"
ls /etc/sudoers.d; sudo grep -rn NOPASSWD /etc/sudoers /etc/sudoers.d 2>/dev/null || echo "no NOPASSWD entries"
echo; echo "### code changed since the commit recorded in the CSV"
git diff 58acacd 20d3985 --stat -- controller experiments analysis tests topology | tail -15
git diff 58acacd 20d3985 -- controller/congestion_policy.py | head -80
echo; echo "### switch decisions vs successful installs, all B and C trials"
python3 - << 'PY'
import csv, glob, json, os, collections
b = "results/raw/m5_campaign_20261011T115819Z"
raw = {(r["scenario"], int(r["trial"])): r for r in csv.DictReader(open(b + ".csv"))}
agg = collections.defaultdict(list)
for (scn, t), r in raw.items():
    if r["algorithm"] == "static":
        continue
    p = f"{b}/{scn}_t{t:02d}/controller_events.jsonl"
    if not os.path.exists(p):
        continue
    ev = [json.loads(l) for l in open(p) if l.strip()]
    sw = [e for e in ev if e.get("decision") == "switch"]
    bad = [e for e in sw if e.get("flow_mod_install_succeeded") is False]
    agg[scn].append((len(sw), len(sw) - len(bad), len(bad), r["path_changes"]))
for scn, v in sorted(agg.items()):
    print(scn, "| (decisions, ok, failed, raw_path_changes) per trial:", v)
PY
echo; echo "### E1 C trial 1: every switch event"
grep '"decision": "switch"' results/raw/m5_campaign_20261011T115819Z/E1_C_no_competition_t01/controller_events.jsonl | cut -c1-420
echo; echo "### loss with Wilson 95% CI (pings treated as independent: optimistic)"
python3 - << 'PY'
import csv, re, math, os, collections
b = "results/raw/m5_campaign_20261011T115819Z"
def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z*z/n; c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return max(0, c-h)*100, min(1, c+h)*100
agg = collections.defaultdict(lambda: [0, 0])
for r in csv.DictReader(open(b + ".csv")):
    if r["experiment_status"] != "ok":
        continue
    d = r["raw_log_ref"]; d = d if os.path.isdir(d) else os.path.dirname(d)
    f = os.path.join(d, "primary_ping.txt")
    if os.path.exists(f):
        m = re.search(r"(\d+) packets transmitted, (\d+) received", open(f).read())
        if m:
            k = r["scenario"]; agg[k][0] += int(m[1]); agg[k][1] += int(m[1]) - int(m[2])
with open("audit/loss_wilson_pooled.csv", "w") as o:
    o.write("scenario,tx,lost,loss_pct,wilson_lo,wilson_hi\n")
    for k, (n, lost) in sorted(agg.items()):
        lo, hi = wilson(lost, n)
        line = f"{k},{n},{lost},{100*lost/n:.2f},{lo:.2f},{hi:.2f}"
        print(line); o.write(line + "\n")
PY
git add audit; git commit -qm "docs: final audit outputs" && echo committed
