import sys
import os
import subprocess
import time

sys.path.insert(0, '/home/andy2341/smartte')
from topology.datacenter_topology import (
    build_topology,
    install_flows_path_a,
    install_flows_path_b,
    cleanup_previous
)

def run_mode_audit(mode):
    output_file = f'/home/andy2341/smartte/logs/audit/phase2_mode_{mode}.txt'
    with open(output_file, 'w') as out:
        def log(msg):
            print(msg)
            out.write(msg + chr(10))
            out.flush()

        log('============================================================')
        log(f'STARTING AUDIT FOR MODE: {mode}')
        log('============================================================')

        log('--- Pre-run cleanup: mn -c ---')
        res = subprocess.run(['mn', '-c'], capture_output=True, text=True)
        log(res.stdout + res.stderr)

        log('--- Pre-run ovs-vsctl show ---')
        res = subprocess.run(['ovs-vsctl', 'show'], capture_output=True, text=True)
        log(res.stdout + res.stderr)

        log('--- Pre-run ip link (checking for leftover mininet interfaces) ---')
        res = subprocess.run(['ip', 'link'], capture_output=True, text=True)
        leftovers = [l for l in res.stdout.splitlines() if any(k in l for k in ['s1-', 's2-', 's3-', 's4-', 'h1-', 'h2-', 'h3-', 'h4-'])]
        log(f'Leftover interfaces count: {len(leftovers)}')
        for l in leftovers:
            log(f'  {l}')

        class Args:
            path = mode
            bw_a = 10
            bw_b = 10
            access_bw = 100
            no_cli = True

        args = Args()
        log(f'Building topology with path={args.path}, bw_a={args.bw_a}, bw_b={args.bw_b}, access_bw={args.access_bw}')
        net = build_topology(args)
        log('Starting network...')
        net.start()
        time.sleep(2)

        log('Clearing default flows on all switches...')
        for sw in ['s1', 's2', 's3', 's4']:
            net[sw].dpctl('del-flows', '-O', 'OpenFlow13')
        time.sleep(1)

        log(f'Installing flows for mode {mode}...')
        if mode == 'A':
            install_flows_path_a(net)
        elif mode == 'B':
            install_flows_path_b(net)
        elif mode == 'both':
            log('Executing mode both exactly as in datacenter_topology.py (calls install_flows_path_a)...')
            install_flows_path_a(net)

        time.sleep(1)

        log(chr(10) + '--- Step 2: OpenFlow 1.3 Flow Dumps ---')
        for sw in ['s1', 's2', 's3', 's4']:
            log(f'>>> ovs-ofctl -O OpenFlow13 dump-flows {sw}')
            res = subprocess.run(['ovs-ofctl', '-O', 'OpenFlow13', 'dump-flows', sw], capture_output=True, text=True)
            log(res.stdout.strip())

        log(chr(10) + '--- Step 3a: h1 -> h2 ping -c 10 ---')
        ping_out = net['h1'].cmd('ping -c 10 10.0.0.2')
        log(ping_out.strip())

        log(chr(10) + '--- Step 3b: h1 -> h2 manual iperf test ---')
        log('Starting iperf server on h2: iperf -s &')
        net['h2'].cmd('iperf -s &')
        time.sleep(1)
        log('Running iperf client on h1: iperf -c 10.0.0.2 -t 10')
        iperf_out = net['h1'].cmd('iperf -c 10.0.0.2 -t 10')
        log(iperf_out.strip())
        log('Stopping iperf server on h2...')
        net['h2'].cmd('killall -9 iperf')
        time.sleep(1)

        log(chr(10) + '--- Step 4: h3 -> h4 ping -c 3 ---')
        h3_ping_out = net['h3'].cmd('ping -c 3 10.0.0.4')
        log(h3_ping_out.strip())

        log(chr(10) + '--- Stopping network ---')
        net.stop()
        time.sleep(1)

        log(chr(10) + '--- Post-run cleanup: mn -c ---')
        res = subprocess.run(['mn', '-c'], capture_output=True, text=True)
        log(res.stdout + res.stderr)

        log(chr(10) + '--- Post-run ovs-vsctl show ---')
        res = subprocess.run(['ovs-vsctl', 'show'], capture_output=True, text=True)
        log(res.stdout + res.stderr)

        log(chr(10) + '--- Post-run ip link check ---')
        res = subprocess.run(['ip', 'link'], capture_output=True, text=True)
        leftovers = [l for l in res.stdout.splitlines() if any(k in l for k in ['s1-', 's2-', 's3-', 's4-', 'h1-', 'h2-', 'h3-', 'h4-'])]
        log(f'Post-run leftover interfaces count: {len(leftovers)}')
        for l in leftovers:
            log(f'  {l}')

        log(f'AUDIT FOR MODE {mode} COMPLETED CLEANLY.')

if __name__ == '__main__':
    modes = ['A', 'B', 'both'] if len(sys.argv) <= 1 else [sys.argv[1]]
    for m in modes:
        run_mode_audit(m)