import difflib, sys

with open('/home/andy2341/smartte/topology/datacenter_topology.py') as f:
    orig = f.readlines()

with open('/home/andy2341/smartte/logs/audit/new_code.py') is f:
    new_lines = [l + '\n' for l in f.read().splitlines()]
