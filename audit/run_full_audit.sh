#!/usr/bin/env bash
cd ~/smartte
echo "##### STEP 1: GIT #####"
git status --short; git log --oneline -n 15; git remote -v; git branch -vv
cat .gitignore; echo "tracked pyc:"; git ls-files | grep -E '\.pyc$|__pycache__'
echo "results tracked?:"; git ls-files results | head -5

echo; echo "##### STEP 2: CSV AUDIT #####"
python3 audit/audit_m5.py

echo; echo "##### STEP 3: E4 EVIDENCE #####"
ls results/raw | head -40
RUNDIR=$(ls -d results/raw/m5_campaign_20261011T115819Z 2>/dev/null)
echo "run dir: $RUNDIR"
ls "$RUNDIR" 2>/dev/null | grep -i E4 | head -40
for d in $(ls -d "$RUNDIR"/*E4_STATIC* 2>/dev/null | head -2); do
  echo "--- $d"; ls -la "$d"; for f in "$d"/*manifest* "$d"/*ping*; do [ -f "$f" ] && { echo "== $f"; head -40 "$f"; }; done
done
for d in $(ls -d "$RUNDIR"/*E4_B* 2>/dev/null | head -1) $(ls -d "$RUNDIR"/*E4_C* 2>/dev/null | head -1); do
  echo "--- $d"; ls -la "$d"
done
echo "controller log lines mentioning failure/switch (first 40):"
grep -rIiE "flowmod|failed|switch|path_change|reroute" logs results/raw/m5_campaign_20261011T115819Z 2>/dev/null | grep -iE "E4|link" | head -40
echo "static ARP / flood grep:"; grep -rniE "flood" topology controller | head; grep -rn "autoStaticArp" topology | head -3

echo; echo "##### STEP 4: CLEANUP AND TESTS #####"
sudo -n true 2>/dev/null && { sudo mn -c >/dev/null 2>&1; echo "mn -c done"; sudo ovs-vsctl show | head -20; } || echo "sudo needs password: run 'sudo mn -c; sudo ovs-vsctl show' yourself"
ip -o link show | head -20
ps aux | grep -E "iperf|osken|os-ken|ryu|ping" | grep -v grep
ls tests/ 2>/dev/null
python3 -m pytest tests -q 2>&1 | tail -20 || python3 -m unittest discover tests 2>&1 | tail -20
echo "queue evidence (limit values):"
grep -rhoE "limit [0-9]+" logs/m2_verification 2>/dev/null | sort | uniq -c | head

echo; echo "##### STEP 5: FILES FOR REVIEW #####"
wc -w report/*.md README.md docs/*.md 2>/dev/null
grep -c "" report/references.md 2>/dev/null
ls screenshots/ 2>/dev/null
