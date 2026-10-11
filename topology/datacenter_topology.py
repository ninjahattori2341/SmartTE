#!/usr/bin/env python3
r"""
SmartTE - Diamond Topology with Static Path Selection
=====================================================

Topology diagram (4 switches, 4 hosts):

        h1 (10.0.0.1)          h3 (10.0.0.3)
             |                      |
         s1:port1               s1:port2
             |                      |
            [s1]
           /    \
     s1:p3      s1:p4
       |          |
     s2:p1      s3:p1        Path A: s1 -- s2 -- s4  (5 ms links)
       |          |           Path B: s1 -- s3 -- s4  (10 ms links)
     s2:p2      s3:p2
       \          /
            [s4]
             |                      |
         s4:port1               s4:port2
             |                      |
        h2 (10.0.0.2)          h4 (10.0.0.4)

Port assignments:
    s1: port1=h1, port2=h3, port3=s2, port4=s3
    s2: port1=s1, port2=s4
    s3: port1=s1, port2=s4
    s4: port1=h2, port2=h4, port3=s2, port4=s3

Access links:  100 Mbps, 1 ms delay
Path A links:  configurable (default 10 Mbps), 5 ms delay
Path B links:  configurable (default 10 Mbps), 10 ms delay

Usage:
    sudo python3 datacenter_topology.py                          # default Path A, competing off
    sudo python3 datacenter_topology.py --path B                  # use Path B for h1<->h2
    sudo python3 datacenter_topology.py --competing A             # pin h3<->h4 to Path A
    sudo python3 datacenter_topology.py --path A --competing A    # both flows on Path A
"""

import argparse
import logging
import sys
import time

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------
DEFAULT_PATH         = 'A'
DEFAULT_COMPETING    = 'off'
ACCESS_BW            = 100    # Mbps
DEFAULT_DELAY_ACCESS = '1ms'
PATH_A_BW            = 10     # Mbps  (s1-s2, s2-s4)
DEFAULT_DELAY_A      = '5ms'
PATH_B_BW            = 10     # Mbps  (s1-s3, s3-s4)
DEFAULT_DELAY_B      = '10ms'
DEFAULT_QUEUE        = 100    # max_queue_size packets on inter-switch links

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
log = logging.getLogger('smartte-topo')


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='SmartTE diamond topology with static path selection'
    )
    parser.add_argument(
        '--path', choices=['A', 'B'], default=DEFAULT_PATH,
        help='Active forwarding path for h1<->h2 (default: A)'
    )
    parser.add_argument(
        '--competing', choices=['off', 'A', 'B'], default=DEFAULT_COMPETING,
        help='Forwarding path for competing traffic h3<->h4 (default: off)'
    )
    parser.add_argument(
        '--bw-a', type=int, default=PATH_A_BW,
        help='Bandwidth for Path A inter-switch links in Mbps (default: %(default)s)'
    )
    parser.add_argument(
        '--bw-b', type=int, default=PATH_B_BW,
        help='Bandwidth for Path B inter-switch links in Mbps (default: %(default)s)'
    )
    parser.add_argument(
        '--access-bw', type=int, default=ACCESS_BW,
        help='Bandwidth for host access links in Mbps (default: %(default)s)'
    )
    parser.add_argument(
        '--delay-access', type=str, default=DEFAULT_DELAY_ACCESS,
        help='Propagation delay for access links (default: %(default)s)'
    )
    parser.add_argument(
        '--delay-a', type=str, default=DEFAULT_DELAY_A,
        help='Propagation delay for Path A links (default: %(default)s)'
    )
    parser.add_argument(
        '--delay-b', type=str, default=DEFAULT_DELAY_B,
        help='Propagation delay for Path B links (default: %(default)s)'
    )
    parser.add_argument(
        '--queue', type=int, default=DEFAULT_QUEUE,
        help='Queue limit (max_queue_size in packets) on bottleneck links (default: %(default)s)'
    )
    parser.add_argument(
        '--no-cli', action='store_true', default=False,
        help='Run automated ping test and exit (no interactive CLI)'
    )
    return parser.parse_args()


def cleanup_previous():
    """Clean up stale Mininet state and OVS bridges."""
    import subprocess
    log.info('Cleaning up previous Mininet state...')
    subprocess.run(['mn', '-c'], capture_output=True, timeout=30)
    log.info('Cleanup complete.')


def disable_ipv6_interface_noise(net, raw_dir=None, label='topology'):
    """Disable IPv6 on Mininet interfaces for the IPv4-only experiment workload."""
    import os

    interfaces = {
        's1': ('s1-eth1', 's1-eth2', 's1-eth3', 's1-eth4'),
        's2': ('s2-eth1', 's2-eth2'),
        's3': ('s3-eth1', 's3-eth2'),
        's4': ('s4-eth1', 's4-eth2', 's4-eth3', 's4-eth4'),
        'h1': ('h1-eth0',),
        'h2': ('h2-eth0',),
        'h3': ('h3-eth0',),
        'h4': ('h4-eth0',),
    }
    observations = []
    for node_name, device_names in interfaces.items():
        for device in device_names:
            proc_path = f'/proc/sys/net/ipv6/conf/{device}/disable_ipv6'
            output = net[node_name].cmd(
                f'if [ -w {proc_path} ]; then '
                f'echo 1 > {proc_path} && cat {proc_path}; '
                'else echo unavailable; fi'
            ).strip()
            observations.append({
                'node': node_name,
                'interface': device,
                'observed_disable_ipv6': output,
                'verified': output == '1',
            })

    verified = all(item['verified'] for item in observations)
    raw_log = None
    if raw_dir:
        raw_log = f'{label}_ipv6_config.txt'
        with open(os.path.join(raw_dir, raw_log), 'w') as output_file:
            output_file.write('IPv6 suppression for the IPv4-only Mininet experiment.\n')
            for item in observations:
                output_file.write(
                    f"{item['node']}/{item['interface']}: "
                    f"disable_ipv6={item['observed_disable_ipv6']} "
                    f"verified={item['verified']}\n"
                )
    return {
        'verified': verified,
        'interfaces': observations,
        'raw_log': raw_log,
    }


def build_topology(args):
    """Build and return the Mininet network with the diamond topology."""
    from mininet.net import Mininet
    from mininet.node import OVSSwitch
    from mininet.link import TCLink
    from mininet.log import setLogLevel

    setLogLevel('info')

    delay_access = getattr(args, 'delay_access', DEFAULT_DELAY_ACCESS)
    delay_a = getattr(args, 'delay_a', DEFAULT_DELAY_A)
    delay_b = getattr(args, 'delay_b', DEFAULT_DELAY_B)
    queue_pkts = getattr(args, 'queue', DEFAULT_QUEUE)
    q_param = queue_pkts if (queue_pkts is not None and queue_pkts > 0) else None

    # Use no controller - we install flows manually for static baseline
    net = Mininet(
        controller=None,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,      # Deterministic MAC addresses (e.g. 00:00:00:00:00:01 for h1)
        autoStaticArp=True,    # Pre-populate kernel ARP tables on hosts. This is required because OpenFlow switches run in failMode='secure' without a controller and flow rules only match IP traffic; without static ARP, ARP requests would be dropped. Flooding ARP would cause broadcast storms in this looped diamond topology.
    )

    log.info('Creating switches (OpenFlow 1.3, failMode=secure)...')
    s1 = net.addSwitch('s1', protocols='OpenFlow13', failMode='secure')
    s2 = net.addSwitch('s2', protocols='OpenFlow13', failMode='secure')
    s3 = net.addSwitch('s3', protocols='OpenFlow13', failMode='secure')
    s4 = net.addSwitch('s4', protocols='OpenFlow13', failMode='secure')

    log.info('Creating hosts...')
    h1 = net.addHost('h1', ip='10.0.0.1/24')
    h2 = net.addHost('h2', ip='10.0.0.2/24')
    h3 = net.addHost('h3', ip='10.0.0.3/24')
    h4 = net.addHost('h4', ip='10.0.0.4/24')

    # ------------------------------------------------------------------
    # Links - port numbers are explicitly assigned
    # ------------------------------------------------------------------
    log.info('Creating access links (%d Mbps, %s)...', args.access_bw, delay_access)
    # s1 access links
    net.addLink(h1, s1, port1=0, port2=1, bw=args.access_bw, delay=delay_access)
    net.addLink(h3, s1, port1=0, port2=2, bw=args.access_bw, delay=delay_access)
    # s4 access links
    net.addLink(h2, s4, port1=0, port2=1, bw=args.access_bw, delay=delay_access)
    net.addLink(h4, s4, port1=0, port2=2, bw=args.access_bw, delay=delay_access)

    log.info('Creating Path A links (s1-s2-s4, %d Mbps, %s, queue=%s pkts)...',
             args.bw_a, delay_a, q_param)
    net.addLink(s1, s2, port1=3, port2=1, bw=args.bw_a, delay=delay_a, max_queue_size=q_param)
    net.addLink(s2, s4, port1=2, port2=3, bw=args.bw_a, delay=delay_a, max_queue_size=q_param)

    log.info('Creating Path B links (s1-s3-s4, %d Mbps, %s, queue=%s pkts)...',
             args.bw_b, delay_b, q_param)
    net.addLink(s1, s3, port1=4, port2=1, bw=args.bw_b, delay=delay_b, max_queue_size=q_param)
    net.addLink(s3, s4, port1=2, port2=4, bw=args.bw_b, delay=delay_b, max_queue_size=q_param)

    return net


def install_flows_path_a(net):
    """
    Install OpenFlow rules for h1 <-> h2 via Path A (s1 -> s2 -> s4).

    Forward direction:  h1 -> s1:p1 -> s1:p3 -> s2:p1 -> s2:p2 -> s4:p3 -> s4:p1 -> h2
    Reverse direction:  h2 -> s4:p1 -> s4:p3 -> s2:p2 -> s2:p1 -> s1:p3 -> s1:p1 -> h1
    """
    log.info('Installing Path A flows (s1 -> s2 -> s4) for h1 <-> h2...')

    # s1: h1(port1) -> s2(port3) and s2(port3) -> h1(port1)
    net['s1'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.2,actions=output:3', '-O', 'OpenFlow13')
    net['s1'].dpctl('add-flow', 'in_port=3,ip,nw_dst=10.0.0.1,actions=output:1', '-O', 'OpenFlow13')

    # s2: s1(port1) -> s4(port2) and s4(port2) -> s1(port1)
    net['s2'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.2,actions=output:2', '-O', 'OpenFlow13')
    net['s2'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.1,actions=output:1', '-O', 'OpenFlow13')

    # s4: s2(port3) -> h2(port1) and h2(port1) -> s2(port3)
    net['s4'].dpctl('add-flow', 'in_port=3,ip,nw_dst=10.0.0.2,actions=output:1', '-O', 'OpenFlow13')
    net['s4'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.1,actions=output:3', '-O', 'OpenFlow13')

    log.info('Path A flows installed.')


def install_flows_path_b(net):
    """
    Install OpenFlow rules for h1 <-> h2 via Path B (s1 -> s3 -> s4).

    Forward direction:  h1 -> s1:p1 -> s1:p4 -> s3:p1 -> s3:p2 -> s4:p4 -> s4:p1 -> h2
    Reverse direction:  h2 -> s4:p1 -> s4:p4 -> s3:p2 -> s3:p1 -> s1:p4 -> s1:p1 -> h1
    """
    log.info('Installing Path B flows (s1 -> s3 -> s4) for h1 <-> h2...')

    # s1: h1(port1) -> s3(port4) and s3(port4) -> h1(port1)
    net['s1'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.2,actions=output:4', '-O', 'OpenFlow13')
    net['s1'].dpctl('add-flow', 'in_port=4,ip,nw_dst=10.0.0.1,actions=output:1', '-O', 'OpenFlow13')

    # s3: s1(port1) -> s4(port2) and s4(port2) -> s1(port1)
    net['s3'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.2,actions=output:2', '-O', 'OpenFlow13')
    net['s3'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.1,actions=output:1', '-O', 'OpenFlow13')

    # s4: s3(port4) -> h2(port1) and h2(port1) -> s3(port4)
    net['s4'].dpctl('add-flow', 'in_port=4,ip,nw_dst=10.0.0.2,actions=output:1', '-O', 'OpenFlow13')
    net['s4'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.1,actions=output:4', '-O', 'OpenFlow13')

    log.info('Path B flows installed.')


def install_competing_flows_path_a(net):
    """
    Install OpenFlow rules for competing traffic h3 <-> h4 via Path A (s1 -> s2 -> s4).

    Forward direction:  h3 -> s1:p2 -> s1:p3 -> s2:p1 -> s2:p2 -> s4:p3 -> s4:p2 -> h4
    Reverse direction:  h4 -> s4:p2 -> s4:p3 -> s2:p2 -> s2:p1 -> s1:p3 -> s1:p2 -> h3
    """
    log.info('Installing competing Path A flows (s1 -> s2 -> s4) for h3 <-> h4...')

    # s1: h3(port2) -> s2(port3) and s2(port3) -> h3(port2)
    net['s1'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.4,actions=output:3', '-O', 'OpenFlow13')
    net['s1'].dpctl('add-flow', 'in_port=3,ip,nw_dst=10.0.0.3,actions=output:2', '-O', 'OpenFlow13')

    # s2: s1(port1) -> s4(port2) and s4(port2) -> s1(port1)
    net['s2'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.4,actions=output:2', '-O', 'OpenFlow13')
    net['s2'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.3,actions=output:1', '-O', 'OpenFlow13')

    # s4: s2(port3) -> h4(port2) and h4(port2) -> s2(port3)
    net['s4'].dpctl('add-flow', 'in_port=3,ip,nw_dst=10.0.0.4,actions=output:2', '-O', 'OpenFlow13')
    net['s4'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.3,actions=output:3', '-O', 'OpenFlow13')

    log.info('Competing Path A flows installed.')


def install_competing_flows_path_b(net):
    """
    Install OpenFlow rules for competing traffic h3 <-> h4 via Path B (s1 -> s3 -> s4).

    Forward direction:  h3 -> s1:p2 -> s1:p4 -> s3:p1 -> s3:p2 -> s4:p4 -> s4:p2 -> h4
    Reverse direction:  h4 -> s4:p2 -> s4:p4 -> s3:p2 -> s3:p1 -> s1:p4 -> s1:p2 -> h3
    """
    log.info('Installing competing Path B flows (s1 -> s3 -> s4) for h3 <-> h4...')

    # s1: h3(port2) -> s3(port4) and s3(port4) -> h3(port2)
    net['s1'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.4,actions=output:4', '-O', 'OpenFlow13')
    net['s1'].dpctl('add-flow', 'in_port=4,ip,nw_dst=10.0.0.3,actions=output:2', '-O', 'OpenFlow13')

    # s3: s1(port1) -> s4(port2) and s4(port2) -> s1(port1)
    net['s3'].dpctl('add-flow', 'in_port=1,ip,nw_dst=10.0.0.4,actions=output:2', '-O', 'OpenFlow13')
    net['s3'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.3,actions=output:1', '-O', 'OpenFlow13')

    # s4: s3(port4) -> h4(port2) and h4(port2) -> s3(port4)
    net['s4'].dpctl('add-flow', 'in_port=4,ip,nw_dst=10.0.0.4,actions=output:2', '-O', 'OpenFlow13')
    net['s4'].dpctl('add-flow', 'in_port=2,ip,nw_dst=10.0.0.3,actions=output:4', '-O', 'OpenFlow13')

    log.info('Competing Path B flows installed.')


def install_flows(net, path='A', competing='off'):
    """Unified entry point to install primary and competing flows."""
    if path == 'A':
        install_flows_path_a(net)
    elif path == 'B':
        install_flows_path_b(net)
    else:
        raise ValueError(f"Invalid path '{path}'. Must be 'A' or 'B'.")

    if competing == 'A':
        install_competing_flows_path_a(net)
    elif competing == 'B':
        install_competing_flows_path_b(net)
    elif competing == 'off':
        log.info('Competing traffic: off (h3, h4 isolated)')
    else:
        raise ValueError(f"Invalid competing mode '{competing}'. Must be 'off', 'A', or 'B'.")



def verify_port_mappings(net):
    """Log actual port mappings for debugging."""
    log.info('--- Switch Port Mappings ---')
    for sw_name in ['s1', 's2', 's3', 's4']:
        sw = net[sw_name]
        result = sw.cmd('ovs-ofctl dump-ports-desc %s -O OpenFlow13' % sw_name)
        log.info('%s port descriptions:\n%s', sw_name, result.strip())


def verify_flows(net):
    """Log installed OpenFlow rules for debugging."""
    log.info('--- Installed OpenFlow Rules ---')
    for sw_name in ['s1', 's2', 's3', 's4']:
        sw = net[sw_name]
        result = sw.cmd('ovs-ofctl dump-flows %s -O OpenFlow13' % sw_name)
        log.info('%s flows:\n%s', sw_name, result.strip())


def run_network(args):
    """Main function: build topology, install flows, run CLI or tests."""
    from mininet.cli import CLI

    cleanup_previous()

    log.info('Building diamond topology...')
    net = build_topology(args)

    log.info('Starting network...')
    net.start()

    # Brief pause for OVS to initialise
    time.sleep(2)

    # Clear any default flows (OVS may have residual rules)
    log.info('Clearing default flows on all switches...')
    for sw_name in ['s1', 's2', 's3', 's4']:
        net[sw_name].dpctl('del-flows', '-O', 'OpenFlow13')
    time.sleep(1)

    # Install forwarding rules based on path selection
    if args.path == 'A':
        install_flows_path_a(net)
    elif args.path == 'B':
        install_flows_path_b(net)
    elif args.path == 'both':
        # 'both' mode: install Path A as default
        log.info('Installing Path A as default in "both" mode...')
        install_flows_path_a(net)

    # Verify setup
    verify_port_mappings(net)
    verify_flows(net)

    # Log active path
    log.info('=' * 60)
    log.info('Active path for h1 <-> h2: Path %s', args.path.upper())
    if args.path == 'A':
        log.info('  Route: h1 -> s1 -> s2 -> s4 -> h2  (5 ms per hop)')
    elif args.path == 'B':
        log.info('  Route: h1 -> s1 -> s3 -> s4 -> h2  (10 ms per hop)')
    else:
        log.info('  Route: Path A installed as default')
    log.info('  h3, h4: NO forwarding rules (isolated)')
    log.info('=' * 60)

    if args.no_cli:
        # Scripted mode: run basic connectivity test and exit
        log.info('Running automated ping test h1 -> h2...')
        result = net['h1'].cmd('ping -c 4 10.0.0.2')
        log.info('Ping result:\n%s', result)
        if '0% packet loss' in result or '0.0% packet loss' in result:
            log.info('PASS: h1 -> h2 connectivity OK')
        else:
            log.warning('FAIL: h1 -> h2 connectivity issue')
    else:
        log.info('Dropping into Mininet CLI. Type "exit" or Ctrl-D to stop.')
        log.info('Quick test commands:')
        log.info('  h1 ping -c 4 h2          # test connectivity')
        log.info('  h1 ping -c 4 h3          # should fail (no rules)')
        log.info('  h2 iperf3 -s -D          # start iperf3 server on h2')
        log.info('  h1 iperf3 -c 10.0.0.2    # run iperf3 client from h1')
        try:
            CLI(net)
        except Exception as e:
            log.error('CLI error: %s', e)

    log.info('Stopping network...')
    net.stop()
    log.info('Network stopped cleanly.')


def main():
    """Entry point."""
    args = parse_args()
    log.info('SmartTE Diamond Topology - Path: %s, Competing: %s',
             args.path, args.competing)
    log.info('Path A bandwidth: %d Mbps, Path B bandwidth: %d Mbps',
             args.bw_a, args.bw_b)

    try:
        run_network(args)
    except KeyboardInterrupt:
        log.info('Interrupted by user.')
    except Exception as e:
        log.error('Fatal error: %s', e)
        sys.exit(1)
    finally:
        log.info('Performing post-execution cleanup...')
        try:
            cleanup_previous()
        except Exception:
            pass


if __name__ == '__main__':
    main()
