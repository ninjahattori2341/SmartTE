#!/usr/bin/env bash
cd ~/smartte
echo "### controller + runner diffs vs campaign commit"
git diff 58acacd 20d3985 -- controller/smartte_controller.py experiments/run_controller_campaign.py
echo; echo "### does analysis use the new helpers?"
grep -n "successful_path_change_count\|mask_unavailable\|flow_mod_install_succeeded" analysis/*.py controller/*.py experiments/*.py | head -20
echo; echo "### file modification times vs campaign window"
ls -l --time-style=full-iso controller/*.py experiments/run_controller_campaign.py results/raw/m5_campaign_20261011T115819Z.csv | awk '{print $6,$7,$9}'
echo; echo "### does the margin ever bind? (C trials)"
python3 - << 'PY'
import csv, json, os, collections, re
b = "results/raw/m5_campaign_20261011T115819Z"
st = collections.defaultdict(lambda: collections.Counter()); imp = collections.defaultdict(list)
for r in csv.DictReader(open(b + ".csv")):
    if r["algorithm"] != "c" or not r["scenario"].startswith(("E1","E2","E3")): continue
    p = f'{b}/{r["scenario"]}_t{int(r["trial"]):02d}/controller_events.jsonl'
    for l in open(p):
        e = json.loads(l); rs = str(e.get("reason"))
        if rs.startswith("held: improvement"): st[r["scenario"]]["held_by_margin"] += 1
        elif rs.startswith("held: dwell"): st[r["scenario"]]["held_by_dwell"] += 1
        elif e.get("decision") == "switch" and e.get("improvement_pct_points") is not None:
            st[r["scenario"]]["switches"] += 1; imp[r["scenario"]].append(e["improvement_pct_points"])
for s in sorted(st):
    v = imp[s]
    print(s, dict(st[s]), "| improvement at switch min/max:", (round(min(v),1), round(max(v),1)) if v else None)
PY
git add audit; git commit -qm "docs: margin and provenance checks" && echo committed
