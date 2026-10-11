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

try:
    from topology.spec import (
        ACCESS_LINKS,
        CONTROLLER_IP,
        CONTROLLER_PORT,
        FLOW_PAIRS,
        HOSTS,
        OPENFLOW_VERSION,
        PATHS,
        SWITCHES,
        flow_rules_for_pair,
    )
except ModuleNotFoundError:  # Direct `python topology/datacenter_topology.py` use.
    from spec import (
        ACCESS_LINKS,
        CONTROLLER_IP,
        CONTROLLER_PORT,
        FLOW_PAIRS,
        HOSTS,
        OPENFLOW_VERSION,
        PATHS,
        SWITCHES,
        flow_rules_for_pair,
    )

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
    parser.add_argument(
        '--controller', choices=['none', 'remote'], default='none',
        help='Use no controller (static dpctl rules) or a remote OpenFlow controller at 127.0.0.1:6653'
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
    from mininet.node import OVSSwitch, RemoteController
    from mininet.link import TCLink
    from mininet.log import setLogLevel

    setLogLevel('info')

    delay_access = getattr(args, 'delay_access', DEFAULT_DELAY_ACCESS)
    delay_a = getattr(args, 'delay_a', DEFAULT_DELAY_A)
    delay_b = getattr(args, 'delay_b', DEFAULT_DELAY_B)
    queue_pkts = getattr(args, 'queue', DEFAULT_QUEUE)
    controller_mode = getattr(args, 'controller', 'none')
    q_param = queue_pkts if (queue_pkts is not None and queue_pkts > 0) else None

    controller_cls = RemoteController if controller_mode == 'remote' else None
    net = Mininet(
        controller=controller_cls,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,      # Deterministic MAC addresses (e.g. 00:00:00:00:00:01 for h1)
        autoStaticArp=True,    # Pre-populate kernel ARP tables on hosts. This is required because OpenFlow switches run in failMode='secure' without a controller and flow rules only match IP traffic; without static ARP, ARP requests would be dropped. Flooding ARP would cause broadcast storms in this looped diamond topology.
    )
    if controller_mode == 'remote':
        net.addController(
            'c0', controller=RemoteController,
            ip=CONTROLLER_IP, port=CONTROLLER_PORT
        )

    log.info('Creating switches (OpenFlow 1.3, failMode=secure)...')
    switches = {
        name: net.addSwitch(name, protocols=OPENFLOW_VERSION, failMode='secure')
        for name in SWITCHES
    }

    log.info('Creating hosts...')
    hosts = {
        name: net.addHost(name, ip=f"{details['ip']}/24")
        for name, details in HOSTS.items()
    }
    nodes = {**hosts, **switches}

    # ------------------------------------------------------------------
    # Links - port numbers are explicitly assigned
    # ------------------------------------------------------------------
    log.info('Creating access links (%d Mbps, %s)...', args.access_bw, delay_access)
    for host_name, switch_name, host_port, switch_port in ACCESS_LINKS:
        net.addLink(
            nodes[host_name], nodes[switch_name],
            port1=host_port, port2=switch_port,
            bw=args.access_bw, delay=delay_access
        )

    for path_name, path in PATHS.items():
        bw = getattr(args, path['bw_arg'])
        delay = getattr(args, path['delay_arg'])
        log.info(
            'Creating Path %s links (%s, %d Mbps, %s, queue=%s pkts)...',
            path_name, path['middle_switch'], bw, delay, q_param
        )
        for left, right, left_port, right_port in path['link_endpoints']:
            net.addLink(
                nodes[left], nodes[right],
                port1=left_port, port2=right_port,
                bw=bw, delay=delay, max_queue_size=q_param
            )

    return net


def _install_static_pair(net, path_name, pair_name):
    """Install a bidirectional IPv4 pair using the shared topology spec."""
    rules = flow_rules_for_pair(path_name, pair_name)
    for direction in ('forward', 'reverse'):
        for rule in rules[direction]:
            flow = (
                f"in_port={rule['in_port']},ip,"
                f"nw_src={rule['ipv4_src']},nw_dst={rule['ipv4_dst']},"
                f"actions=output:{rule['out_port']}"
            )
            net[rule['switch']].dpctl('add-flow', flow, '-O', OPENFLOW_VERSION)


def install_flows_path_a(net):
    """Install the h1-h2 primary flow pair over Path A."""
    log.info('Installing Path A flows for h1 <-> h2...')
    _install_static_pair(net, 'A', 'primary')
    log.info('Path A flows installed.')


def install_flows_path_b(net):
    """Install the h1-h2 primary flow pair over Path B."""
    log.info('Installing Path B flows for h1 <-> h2...')
    _install_static_pair(net, 'B', 'primary')
    log.info('Path B flows installed.')


def install_competing_flows_path_a(net):
    """Pin the h3-h4 competing pair to Path A."""
    log.info('Installing competing Path A flows for h3 <-> h4...')
    _install_static_pair(net, 'A', 'competing')
    log.info('Competing Path A flows installed.')


def install_competing_flows_path_b(net):
    """Pin the h3-h4 competing pair to Path B."""
    log.info('Installing competing Path B flows for h3 <-> h4...')
    _install_static_pair(net, 'B', 'competing')
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

    controller_mode = getattr(args, 'controller', 'none')
    if controller_mode == 'none':
        # Clear any default flows (OVS may have residual rules).
        log.info('Clearing default flows on all switches...')
        for sw_name in SWITCHES:
            net[sw_name].dpctl('del-flows', '-O', OPENFLOW_VERSION)
        time.sleep(1)

        # Static mode installs the predetermined primary path locally.
        if args.path == 'A':
            install_flows_path_a(net)
        elif args.path == 'B':
            install_flows_path_b(net)
        if args.competing == 'A':
            install_competing_flows_path_a(net)
        elif args.competing == 'B':
            install_competing_flows_path_b(net)
    else:
        log.info(
            'Remote controller selected at %s:%s; no dpctl flows will be installed.',
            CONTROLLER_IP, CONTROLLER_PORT
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            flow_dump = net['s1'].cmd('ovs-ofctl -O OpenFlow13 dump-flows s1')
            if 'nw_src=10.0.0.1' in flow_dump:
                break
            time.sleep(0.25)
        else:
            log.warning('No controller-installed h1-h2 flow appeared within 10 seconds.')

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
    if args.competing == 'off':
        log.info('  h3, h4: NO forwarding rules (isolated)')
    else:
        log.info('  h3 <-> h4 competing flow path: %s', args.competing)
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
