#!/usr/bin/env bash
cd ~/smartte

echo "##### 1. VENV + CSV AUDIT #####"
sudo apt install -y python3.12-venv >/dev/null 2>&1 && echo "python3.12-venv installed"
rm -rf ~/audit-venv
python3 -m venv ~/audit-venv && ~/audit-venv/bin/pip install -q pandas && echo "pandas ok"
~/audit-venv/bin/python audit/audit_m5.py 2>&1 | tee audit/audit_m5_output.txt

echo; echo "##### 2. E4 SUCCESSFUL VS FAILED SWITCHES #####"
python3 - << 'PY' | tee audit/e4_derived.txt
import json, glob, os, csv
b = "results/raw/m5_campaign_20261011T115819Z"
out = []
print("trial | switch_decisions | installs_succeeded | installs_failed | max path_changes_total | first_switch_after_linkdown_s")
for d in sorted(glob.glob(b + "/E4_[BC]_PathA_down_t*")):
    ev = [json.loads(l) for l in open(d + "/controller_events.jsonl") if l.strip()]
    fl = json.load(open(d + "/link_failure_event.json"))["time_monotonic_s"]
    sw = [e for e in ev if e.get("decision") == "switch"]
    ok = [e for e in sw if e.get("flow_mod_install_succeeded") is not False]
    bad = [e for e in sw if e.get("flow_mod_install_succeeded") is False]
    last = max((e.get("path_changes_total") or 0) for e in ev)
    after = [e.get("time_monotonic_s", 0) - fl for e in ok if e.get("time_monotonic_s", 0) >= fl]
    first = round(min(after), 3) if after else "n/a"
    print(os.path.basename(d), "|", len(sw), "|", len(ok), "|", len(bad), "|", last, "|", first)
    out.append([os.path.basename(d), len(sw), len(ok), len(bad), last, first])
with open("audit/e4_derived.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["trial", "switch_decisions", "installs_succeeded", "installs_failed", "max_path_changes_total", "first_ok_switch_after_linkdown_s"])
    w.writerows(out)
PY

echo; echo "##### 3. COMMIT AUDIT FILES #####"
git add audit
git commit -qm "docs: audit scripts and outputs" && echo "audit commit ok"
git log --oneline -n 3

echo; echo "##### 4. REMOVE TEMP SUDO #####"
sudo rm -f /etc/sudoers.d/smartte-temp && echo "temp sudo rule removed"
sudo -n true 2>/dev/null && echo "WARNING: passwordless sudo still active" || echo "passwordless sudo is off"
echo DONE
