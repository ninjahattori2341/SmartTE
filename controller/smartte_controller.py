"""SmartTE OpenFlow 1.3 controller application for static, B, and C policies."""

import datetime
import json
import logging
import os
import time

from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.lib import hub
from os_ken.ofproto import ofproto_v1_3

from topology.spec import PATHS, SWITCHES, flow_rules_for_pair
from controller.congestion_policy import (
    evaluate_policy_b,
    evaluate_policy_c,
    mask_unavailable_paths,
    score_paths,
    utilization_from_counters,
)
from controller.static_policy import choose_static_path

LOG = logging.getLogger('smartte.controller')
PRIMARY_COOKIE = {'A': 0x534D41520000000A, 'B': 0x534D41520000000B}
COMPETING_COOKIE = 0x534D41520000000C
COOKIE_MASK = 0xFFFFFFFFFFFFFFFF
DPID_TO_SWITCH = {int(name[1:]): name for name in SWITCHES}
COUNTER_PORTS = {
    path: tuple(PATHS[path]['core_links'])
    for path in ('A', 'B')
}


def _environment_path(name):
    return os.environ.get(name) or None


def _write_jsonl(path, record):
    if not path:
        return
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as output:
        output.write(json.dumps(record, sort_keys=True) + '\n')


def _timestamp_utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class SmartTEController(app_manager.OSKenApp):
    """Install pinned/static forwarding and optionally make periodic decisions."""

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = os.environ.get('SMARTTE_POLICY', 'static').upper()
        if self.policy not in ('STATIC', 'B', 'C'):
            raise ValueError('SMARTTE_POLICY must be static, B, or C.')
        self.initial_path = os.environ.get('SMARTTE_INITIAL_PATH', 'A').upper()
        if self.initial_path not in ('A', 'B'):
            raise ValueError('SMARTTE_INITIAL_PATH must be A or B.')
        self.competing_path = os.environ.get('SMARTTE_COMPETING_PATH', 'off').upper()
        if self.competing_path not in ('A', 'B', 'OFF'):
            raise ValueError('SMARTTE_COMPETING_PATH must be A, B, or off.')
        self.poll_interval_ms = int(os.environ.get('SMARTTE_POLL_INTERVAL_MS', '1000'))
        self.switching_threshold = float(os.environ.get('SMARTTE_SWITCHING_THRESHOLD', '15'))
        self.minimum_dwell_time_ms = int(os.environ.get('SMARTTE_MINIMUM_DWELL_MS', '5000'))
        self.event_log_path = _environment_path('SMARTTE_EVENT_LOG')
        self.stats_log_path = _environment_path('SMARTTE_STATS_LOG')
        self.ready_file = _environment_path('SMARTTE_READY_FILE')
        self.load_event_file = _environment_path('SMARTTE_LOAD_EVENT_FILE')

        self.datapaths = {}
        self.current_path = self.initial_path
        self.path_changes = 0
        self.decision_count = 0
        self.flow_mod_count = 0
        self.last_switch_mono = time.monotonic()
        self.port_history = {}
        self.latest_link_utilization = {}
        self.stats_request_cycles = {}
        self.pending_stats = {}
        self.stats_cycle_id = 0
        self.stats_cycle_started = {}
        self.stats_thread = None
        self.installed = False
        self.unavailable_paths = set()
        self.congestion_onset_mono = None
        self.recovery_onset_mono = None
        self.last_load_event_id = None

        LOG.info(
            'SmartTE controller starting: policy=%s initial_path=%s '
            'competing_path=%s poll_interval_ms=%d threshold=%.3f dwell_ms=%d',
            self.policy, self.initial_path, self.competing_path,
            self.poll_interval_ms, self.switching_threshold,
            self.minimum_dwell_time_ms,
        )

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, event):
        datapath = event.msg.datapath
        switch_name = DPID_TO_SWITCH.get(datapath.id)
        if switch_name is None:
            LOG.error('Ignoring unexpected switch datapath id=%s', datapath.id)
            return
        self.datapaths[switch_name] = datapath
        LOG.info('OpenFlow 1.3 switch connected: %s dpid=%s', switch_name, datapath.id)
        self._install_when_ready()

    def _install_when_ready(self):
        if self.installed or set(self.datapaths) != set(SWITCHES):
            return

        # All switches are connected before any forwarding rule is installed.
        self._install_primary_path(self.initial_path)
        if self.competing_path in ('A', 'B'):
            self._install_pair(self.competing_path, 'competing', COMPETING_COOKIE)
        self.installed = True
        self._write_ready_record()
        self.stats_thread = hub.spawn(self._poll_stats_loop)
        LOG.info(
            'Initial OpenFlow rules installed: primary=%s competing=%s; '
            'datapaths=%s',
            self.current_path, self.competing_path, sorted(self.datapaths),
        )

    def _write_ready_record(self):
        if not self.ready_file:
            return
        os.makedirs(os.path.dirname(self.ready_file), exist_ok=True)
        with open(self.ready_file, 'w', encoding='utf-8') as output:
            json.dump({
                'ready': True,
                'timestamp_utc': _timestamp_utc(),
                'time_monotonic_s': time.monotonic(),
                'policy': self.policy,
                'initial_path': self.initial_path,
                'competing_path': self.competing_path,
                'connected_switches': sorted(self.datapaths),
                'openflow_version': '1.3',
            }, output, indent=2)

    def _install_pair(self, path, pair_name, cookie):
        rules_by_direction = flow_rules_for_pair(path, pair_name)
        # For each direction, install at the destination side and work back to
        # the source ingress so the first packet never outruns a downstream rule.
        for direction in ('forward', 'reverse'):
            for rule in reversed(rules_by_direction[direction]):
                datapath = self.datapaths[rule['switch']]
                parser = datapath.ofproto_parser
                ofproto = datapath.ofproto
                match = parser.OFPMatch(
                    in_port=rule['in_port'],
                    eth_type=0x0800,
                    ipv4_src=rule['ipv4_src'],
                    ipv4_dst=rule['ipv4_dst'],
                )
                actions = [parser.OFPActionOutput(rule['out_port'])]
                instructions = [parser.OFPInstructionActions(
                    ofproto.OFPIT_APPLY_ACTIONS, actions
                )]
                message = parser.OFPFlowMod(
                    datapath=datapath,
                    cookie=cookie,
                    table_id=0,
                    command=ofproto.OFPFC_ADD,
                    idle_timeout=0,
                    hard_timeout=0,
                    priority=100,
                    match=match,
                    instructions=instructions,
                )
                datapath.send_msg(message)
                self.flow_mod_count += 1
                LOG.debug(
                    'FlowMod add cookie=0x%x pair=%s path=%s switch=%s '
                    'in=%d src=%s dst=%s out=%d',
                    cookie, pair_name, path, rule['switch'], rule['in_port'],
                    rule['ipv4_src'], rule['ipv4_dst'], rule['out_port'],
                )

    def _install_primary_path(self, new_path):
        if new_path not in ('A', 'B'):
            LOG.error('Refusing invalid primary path %r', new_path)
            return False
        if new_path in self.unavailable_paths:
            LOG.warning('Refusing unavailable primary path %s', new_path)
            return False

        old_path = self.current_path
        if old_path == new_path and self.installed:
            return True

        self._install_pair(new_path, 'primary', PRIMARY_COOKIE[new_path])
        if old_path != new_path:
            self._delete_cookie(PRIMARY_COOKIE[old_path])
            self.current_path = new_path
            self.path_changes += 1
            self.last_switch_mono = time.monotonic()
        return True

    def _delete_cookie(self, cookie):
        for datapath in self.datapaths.values():
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto
            message = parser.OFPFlowMod(
                datapath=datapath,
                cookie=cookie,
                cookie_mask=COOKIE_MASK,
                table_id=ofproto.OFPTT_ALL,
                command=ofproto.OFPFC_DELETE,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY,
                match=parser.OFPMatch(),
            )
            datapath.send_msg(message)
            self.flow_mod_count += 1

    def _poll_stats_loop(self):
        while True:
            self._request_port_stats()
            hub.sleep(self.poll_interval_ms / 1000.0)

    def _request_port_stats(self):
        if not self.installed:
            return
        required_switches = ('s1', 's2', 's3')
        self.stats_cycle_id += 1
        cycle_id = self.stats_cycle_id
        self.pending_stats[cycle_id] = set(required_switches)
        self.stats_cycle_started[cycle_id] = {
            'monotonic_s': time.monotonic(),
            'process_cpu_s': time.process_time(),
        }
        for switch_name in required_switches:
            datapath = self.datapaths.get(switch_name)
            if datapath is None:
                self.pending_stats[cycle_id].discard(switch_name)
                continue
            request = datapath.ofproto_parser.OFPPortStatsRequest(
                datapath, 0, datapath.ofproto.OFPP_ANY
            )
            xid = datapath.set_xid(request)
            self.stats_request_cycles[(datapath.id, xid)] = cycle_id
            datapath.send_msg(request)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, event):
        message = event.msg
        datapath = message.datapath
        switch_name = DPID_TO_SWITCH.get(datapath.id)
        if switch_name is None:
            return
        cycle_id = self.stats_request_cycles.pop((datapath.id, message.xid), None)
        if cycle_id is None:
            LOG.debug('Ignoring unmatched port-stats reply dpid=%s xid=%s', datapath.id, message.xid)
            return

        now = time.monotonic()
        for stat in message.body:
            for path_name, link_ports in COUNTER_PORTS.items():
                for required_switch, port_no in link_ports:
                    if required_switch != switch_name or port_no != stat.port_no:
                        continue
                    key = (switch_name, port_no)
                    previous = self.port_history.get(key)
                    capacity_mbps = float(os.environ.get(
                        f'SMARTTE_PATH_{path_name}_CAPACITY_MBPS',
                        PATHS[path_name]['capacity_mbps'],
                    ))
                    if previous is None:
                        utilization, status = None, 'first_sample'
                        elapsed_s = None
                    else:
                        elapsed_s = now - previous['time_monotonic_s']
                        utilization, status = utilization_from_counters(
                            previous['tx_bytes'], stat.tx_bytes,
                            elapsed_s, capacity_mbps,
                        )
                    self.port_history[key] = {
                        'tx_bytes': stat.tx_bytes,
                        'time_monotonic_s': now,
                    }
                    if status == 'ok':
                        self.latest_link_utilization[(path_name, switch_name, port_no)] = utilization
                    else:
                        self.latest_link_utilization[(path_name, switch_name, port_no)] = None
                    _write_jsonl(self.stats_log_path, {
                        'timestamp_utc': _timestamp_utc(),
                        'time_monotonic_s': now,
                        'cycle_id': cycle_id,
                        'switch': switch_name,
                        'port_no': port_no,
                        'tx_bytes': stat.tx_bytes,
                        'elapsed_s': elapsed_s,
                        'configured_capacity_mbps': capacity_mbps,
                        'utilization_pct': utilization,
                        'status': status,
                    })

        pending = self.pending_stats.get(cycle_id)
        if pending is not None:
            pending.discard(switch_name)
            if not pending:
                self.pending_stats.pop(cycle_id, None)
                self._complete_stats_cycle(cycle_id)

    def _complete_stats_cycle(self, cycle_id):
        cycle_start = self.stats_cycle_started.pop(cycle_id, None)
        cycle_end_mono = time.monotonic()
        cycle_end_cpu = time.process_time()
        link_values = {
            path_name: [
                self.latest_link_utilization.get((path_name, switch_name, port_no))
                for switch_name, port_no in COUNTER_PORTS[path_name]
            ]
            for path_name in ('A', 'B')
        }
        scores = mask_unavailable_paths(
            score_paths(link_values), self.unavailable_paths
        )
        self._read_load_event()
        record = {
            'timestamp_utc': _timestamp_utc(),
            'time_monotonic_s': time.monotonic(),
            'cycle_id': cycle_id,
            'path_link_utilization_pct': link_values,
            'path_scores_pct': scores,
            'current_path': self.current_path,
            'policy': self.policy,
            'poll_interval_ms': self.poll_interval_ms,
            'poll_round_trip_s': (
                cycle_end_mono - cycle_start['monotonic_s']
                if cycle_start else None
            ),
            'controller_process_cpu_s': (
                cycle_end_cpu - cycle_start['process_cpu_s']
                if cycle_start else None
            ),
        }

        if self.policy == 'STATIC' or any(value is None for value in scores.values()):
            record.update({
                'decision': 'hold',
                'reason': (
                    'static policy' if self.policy == 'STATIC'
                    else 'hold: path unavailable' if self.unavailable_paths
                    else 'hold: path score unavailable'
                ),
                'candidate_path': None,
                'switching_threshold': self.switching_threshold if self.policy == 'C' else None,
                'elapsed_since_last_switch_ms': round(
                    (time.monotonic() - self.last_switch_mono) * 1000, 3
                ),
            })
            _write_jsonl(self.event_log_path, record)
            return

        decision_started_cpu = time.process_time()
        elapsed_since_switch_ms = (time.monotonic() - self.last_switch_mono) * 1000
        if self.policy == 'B':
            result = evaluate_policy_b(self.current_path, scores)
            threshold = None
        else:
            result = evaluate_policy_c(
                self.current_path, scores,
                switching_threshold=self.switching_threshold,
                minimum_dwell_time_ms=self.minimum_dwell_time_ms,
                elapsed_since_switch_ms=elapsed_since_switch_ms,
            )
            threshold = self.switching_threshold

        decision_cpu_s = time.process_time() - decision_started_cpu
        self.decision_count += 1
        record.update({
            'candidate_path': result['candidate_path'],
            'decision': 'switch' if result['switch'] else 'hold',
            'reason': result['reason'],
            'improvement_pct_points': result['improvement_pct_points'],
            'switching_threshold': threshold,
            'minimum_dwell_time_ms': self.minimum_dwell_time_ms if self.policy == 'C' else None,
            'elapsed_since_last_switch_ms': round(elapsed_since_switch_ms, 3),
            'decision_cpu_time_s': decision_cpu_s,
            'flow_mod_count_before': self.flow_mod_count,
        })

        if result['switch']:
            from_path = self.current_path
            switch_send_mono = time.monotonic()
            installed = self._install_primary_path(result['selected_path'])
            record['path_before'] = from_path
            record['path_after'] = self.current_path
            record['flow_mod_timestamp_monotonic_s'] = switch_send_mono
            record['reaction_time_s'] = (
                switch_send_mono - self.congestion_onset_mono
                if self.congestion_onset_mono is not None else None
            )
            record['recovery_time_s'] = (
                switch_send_mono - self.recovery_onset_mono
                if self.recovery_onset_mono is not None else None
            )
            if record['recovery_time_s'] is not None:
                self.recovery_onset_mono = None
            record['flow_mod_install_succeeded'] = installed
        else:
            record['path_before'] = self.current_path
            record['path_after'] = self.current_path
            record['reaction_time_s'] = None

        record['flow_mod_count_after'] = self.flow_mod_count
        record['path_changes_total'] = self.path_changes
        _write_jsonl(self.event_log_path, record)

    def _read_load_event(self):
        if not self.load_event_file or not os.path.isfile(self.load_event_file):
            return
        try:
            with open(self.load_event_file, encoding='utf-8') as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError):
            return
        event_id = payload.get('event_id')
        if event_id == self.last_load_event_id:
            return
        self.last_load_event_id = event_id
        if payload.get('state') == 'on':
            self.congestion_onset_mono = float(payload['time_monotonic_s'])
            self.recovery_onset_mono = None
        elif payload.get('state') == 'off':
            self.congestion_onset_mono = None
            self.recovery_onset_mono = float(payload['time_monotonic_s'])

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port_status_handler(self, event):
        message = event.msg
        switch_name = DPID_TO_SWITCH.get(message.datapath.id)
        if switch_name is None:
            return
        port_no = message.desc.port_no
        is_down = bool(message.desc.state & message.datapath.ofproto.OFPPS_LINK_DOWN)
        for path_name, links in COUNTER_PORTS.items():
            if (switch_name, port_no) not in links:
                continue
            if is_down:
                self.unavailable_paths.add(path_name)
            else:
                self.unavailable_paths.discard(path_name)
            LOG.warning(
                'Core port status: switch=%s port=%d path=%s down=%s',
                switch_name, port_no, path_name, is_down,
            )
        if self.current_path in self.unavailable_paths and self.policy != 'STATIC':
            alternative = 'B' if self.current_path == 'A' else 'A'
            if alternative not in self.unavailable_paths:
                self._install_primary_path(alternative)
                _write_jsonl(self.event_log_path, {
                    'timestamp_utc': _timestamp_utc(),
                    'time_monotonic_s': time.monotonic(),
                    'decision': 'switch',
                    'reason': 'switch: current path became unavailable',
                    'path_before': 'A' if alternative == 'B' else 'B',
                    'path_after': alternative,
                    'recovery_time_s': None,
                    'path_changes_total': self.path_changes,
                })

    def close(self):
        """Remove only SmartTE-owned entries before the controller exits."""
        for cookie in (*PRIMARY_COOKIE.values(), COMPETING_COOKIE):
            try:
                self._delete_cookie(cookie)
            except Exception as exc:  # The switch may already have disconnected.
                LOG.warning('Could not remove cookie 0x%x during close: %s', cookie, exc)
        super().close()
