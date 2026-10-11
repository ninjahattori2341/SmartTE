"""Single source of truth for SmartTE host addresses, ports, and paths."""

HOSTS = {
    'h1': {'ip': '10.0.0.1', 'switch': 's1', 'switch_port': 1},
    'h2': {'ip': '10.0.0.2', 'switch': 's4', 'switch_port': 1},
    'h3': {'ip': '10.0.0.3', 'switch': 's1', 'switch_port': 2},
    'h4': {'ip': '10.0.0.4', 'switch': 's4', 'switch_port': 2},
}

FLOW_PAIRS = {
    'primary': ('h1', 'h2'),
    'competing': ('h3', 'h4'),
}

ACCESS_LINKS = (
    ('h1', 's1', 0, 1),
    ('h3', 's1', 0, 2),
    ('h2', 's4', 0, 1),
    ('h4', 's4', 0, 2),
)

PATHS = {
    'A': {
        'middle_switch': 's2',
        's1_path_port': 3,
        'middle_s1_port': 1,
        'middle_s4_port': 2,
        's4_path_port': 3,
        'bw_arg': 'bw_a',
        'capacity_mbps': 10.0,
        'delay_arg': 'delay_a',
        'core_links': (('s1', 3), ('s2', 2)),
        'link_endpoints': (
            ('s1', 's2', 3, 1),
            ('s2', 's4', 2, 3),
        ),
    },
    'B': {
        'middle_switch': 's3',
        's1_path_port': 4,
        'middle_s1_port': 1,
        'middle_s4_port': 2,
        's4_path_port': 4,
        'bw_arg': 'bw_b',
        'capacity_mbps': 10.0,
        'delay_arg': 'delay_b',
        'core_links': (('s1', 4), ('s3', 2)),
        'link_endpoints': (
            ('s1', 's3', 4, 1),
            ('s3', 's4', 2, 4),
        ),
    },
}

SWITCHES = ('s1', 's2', 's3', 's4')
CONTROLLER_IP = '127.0.0.1'
CONTROLLER_PORT = 6653
OPENFLOW_VERSION = 'OpenFlow13'


def flow_rules_for_pair(path_name, pair_name):
    """Return forward/reverse OpenFlow match and output-port specs.

    Each rule is a dict so the static installer and controller use the same
    host, address, switch-port, and path definitions.
    """
    if path_name not in PATHS:
        raise ValueError(f'Invalid path {path_name!r}; expected A or B.')
    if pair_name not in FLOW_PAIRS:
        raise ValueError(f'Invalid flow pair {pair_name!r}.')

    source_name, destination_name = FLOW_PAIRS[pair_name]
    source = HOSTS[source_name]
    destination = HOSTS[destination_name]
    path = PATHS[path_name]
    middle = path['middle_switch']

    def rule(switch, in_port, src, dst, out_port):
        return {
            'switch': switch,
            'in_port': in_port,
            'ipv4_src': src,
            'ipv4_dst': dst,
            'out_port': out_port,
        }

    forward = [
        rule('s1', source['switch_port'], source['ip'], destination['ip'], path['s1_path_port']),
        rule(middle, path['middle_s1_port'], source['ip'], destination['ip'], path['middle_s4_port']),
        rule('s4', path['s4_path_port'], source['ip'], destination['ip'], destination['switch_port']),
    ]
    reverse = [
        rule('s4', destination['switch_port'], destination['ip'], source['ip'], path['s4_path_port']),
        rule(middle, path['middle_s4_port'], destination['ip'], source['ip'], path['middle_s1_port']),
        rule('s1', path['s1_path_port'], destination['ip'], source['ip'], source['switch_port']),
    ]
    return {'forward': forward, 'reverse': reverse}
