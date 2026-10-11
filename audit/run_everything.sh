#!/usr/bin/env bash
cd ~/smartte
echo "##### A. OWNERSHIP + CLEANUP #####"
sudo chown -R "$USER":"$USER" . && echo "ownership fixed"
sudo mn -c >/dev/null 2>&1; echo "mn -c done"
sudo ovs-vsctl show | head -8
ps aux | grep -E "iperf|osken|os-ken|ryu" | grep -v grep || echo "no stray processes"

echo; echo "##### B. COMMITS (local only, no push) #####"
git config user.name; git config user.email
git diff --stat | tail -1
git add controller experiments tests README.md docs results/DATA_DICTIONARY.md requirements analysis 2>&1 | tail -2
git commit -qm "feat: M3-M5 controller, algorithms, analysis scripts" && echo "commit 1 ok"
git add results/raw results/processed logs/m3_verification logs/m4_pilot_run.txt logs/m5_campaign_*.txt logs/m5_campaign_interruption.md 2>&1 | tail -2
git commit -qm "data: raw campaign CSVs, M3/M4/M5 logs and processed outputs" && echo "commit 2 ok"
git add report 2>&1 | tail -2
git commit -qm "docs: report drafts" && echo "commit 3 ok"
git add logs/m2_verification 2>&1 | tail -2
git commit -qm "data: M2 verification evidence (refreshed re-runs)" && echo "commit 4 ok"
git log --oneline -n 6; git remote -v; echo "left uncommitted:"; git status --short | grep -v '^??' | head -5; git status --short | grep '^??' | head -10

echo; echo "##### C. PANDAS VENV + CSV AUDIT #####"
[ -d ~/audit-venv ] || python3 -m venv ~/audit-venv || echo "VENV FAILED: need 'sudo apt install python3-venv'"
~/audit-venv/bin/pip install -q pandas 2>&1 | tail -2
~/audit-venv/bin/python audit/audit_m5.py

echo; echo "##### D. UNIT TESTS #####"
python3 -m unittest discover tests 2>&1 | tail -15

echo; echo "##### E. E4 EVIDENCE (stdlib parser) #####"
python3 - << 'PY'
import json, csv, glob, collections, os
base = "results/raw/m5_campaign_20261011T115819Z"
rows = list(csv.DictReader(open(base + ".csv")))
print("E4 rows from raw CSV (algorithm, trial, status, path_changes, decision_count, throughput, loss):")
for r in rows:
    if str(r.get("experiment_id","")).startswith("E4") or "E4" in str(r.get("scenario","")):
        print(" ", r.get("algorithm"), r.get("trial"), r.get("experiment_status"), r.get("path_changes"),
              r.get("decision_count"), r.get("tcp_throughput_mbps"), r.get("ping_loss_pct"), r.get("reaction_time_s"), r.get("recovery_time_s"))
print("\nPer-trial controller_events summary (B and C):")
for d in sorted(glob.glob(base + "/E4_[BC]_PathA_down_t*")):
    ev = [json.loads(l) for l in open(d + "/controller_events.jsonl") if l.strip()]
    dec = collections.Counter(e.get("decision") for e in ev)
    reasons = collections.Counter(str(e.get("reason"))[:40] for e in ev)
    keys = collections.Counter(k for e in ev for k in e)
    fl = json.load(open(d + "/link_failure_event.json"))
    log = open(d + "/controller_process.log", errors="ignore").read()
    print(os.path.basename(d), "decisions:", dict(dec), "| link event:", fl)
    print("   reasons:", dict(reasons.most_common(4)))
    print("   process.log flow/fail/error lines:", sum(1 for l in log.splitlines() if any(w in l.lower() for w in ("fail","error","exception"))))
    if d.endswith("t01"):
        print("   event keys:", sorted(keys))
        sw = [e for e in ev if e.get("decision") != "hold"][:2]
        print("   first non-hold events:", json.dumps(sw)[:700])
        s = json.load(open(d + "/openflow_controller_summary.json"))
        print("   summary keys:", list(s.keys()))
PY

echo; echo "##### F. DOCS #####"
grep -c "" report/references.md; ls screenshots/ 2>/dev/null | head
echo "DONE"
