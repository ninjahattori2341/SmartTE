import unittest

from experiments.run_static_baseline import (
    evaluate_h3_h4_validation,
    packet_delta_sum,
    parse_port_counters,
    wait_for_iperf_json,
)


class PortCounterParserTests(unittest.TestCase):
    def test_parses_named_ports_with_rx_and_tx_on_separate_lines(self):
        output = '''\
OFPST_PORT reply (OF1.3): 1 ports
  port  "s2-eth2": rx pkts=17, bytes=1700, drop=0
           tx pkts=19, bytes=1900, drop=0
           duration=5.000s
'''
        self.assertEqual(
            parse_port_counters(output),
            {
                's2-eth2': {
                    'rx_packets': 17,
                    'rx_bytes': 1700,
                    'tx_packets': 19,
                    'tx_bytes': 1900,
                }
            },
        )

    def test_parses_numeric_port_id_and_same_line_counters(self):
        output = ' port 2: rx pkts=3, bytes=300, drop=0, tx pkts=4, bytes=400\n'
        self.assertEqual(
            parse_port_counters(output),
            {'2': {'rx_packets': 3, 'rx_bytes': 300, 'tx_packets': 4, 'tx_bytes': 400}},
        )


class PathEvidenceTests(unittest.TestCase):
    def test_packet_delta_sum_uses_colon_delimited_counter_keys(self):
        deltas = {
            's2:s2-eth1:rx_packets': 10,
            's2:s2-eth2:tx_packets': 11,
            's3:s3-eth1:tx_packets': 0,
            's2:s2-eth2:rx_bytes': 1000,
        }
        self.assertEqual(packet_delta_sum(deltas, 's2'), 21)
        self.assertEqual(packet_delta_sum(deltas, 's3'), 0)

    def test_h3_h4_path_a_passes_when_only_path_a_carries_packets(self):
        ping = '64 bytes from 10.0.0.4: icmp_seq=2 time=1.0 ms\n20 packets transmitted, 20 received, 0% packet loss'
        deltas = {
            's2:s2-eth1:rx_packets': 20,
            's2:s2-eth2:tx_packets': 20,
            's3:s3-eth1:rx_packets': 0,
            's3:s3-eth2:tx_packets': 0,
        }
        result = evaluate_h3_h4_validation(ping, deltas, 'A')
        self.assertTrue(result['passed'])
        self.assertEqual(result['path_a_packet_delta_sum'], 40)
        self.assertEqual(result['path_b_packet_delta_sum'], 0)
        self.assertFalse(result['duplicate_reply_detected'])

    def test_h3_h4_duplicate_reply_fails_path_validation(self):
        ping = '64 bytes from 10.0.0.4: icmp_seq=2 DUP! time=1.0 ms\n20 packets transmitted, 20 received, 0% packet loss'
        result = evaluate_h3_h4_validation(
            ping, {'s2:s2-eth1:rx_packets': 1}, 'A'
        )
        self.assertFalse(result['passed'])
        self.assertTrue(result['duplicate_reply_detected'])

    def test_h3_h4_without_rules_passes_only_when_both_paths_are_idle(self):
        ping = '20 packets transmitted, 0 received, 100% packet loss'
        result = evaluate_h3_h4_validation(ping, {}, 'off')
        self.assertTrue(result['passed'])


class BackgroundIperfOutputTests(unittest.TestCase):
    def test_waits_until_background_iperf_json_is_complete(self):
        class FakeNode:
            def __init__(self):
                self.responses = iter((
                    '',
                    '{"start": {}}',
                    '{"end": {"sum_received": {"bits_per_second": 5000000}}}',
                ))

            def cmd(self, command):
                return next(self.responses)

        output = wait_for_iperf_json(FakeNode(), '/tmp/competing.json', 2)
        self.assertIn('sum_received', output)


if __name__ == '__main__':
    unittest.main()
