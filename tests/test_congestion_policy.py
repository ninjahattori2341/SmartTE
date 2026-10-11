import unittest

from controller.congestion_policy import (
    best_path,
    evaluate_policy_b,
    evaluate_policy_c,
    mask_unavailable_paths,
    score_paths,
    successful_path_change_count,
    utilization_from_counters,
)
from controller.static_policy import choose_static_path


class PathScoringTests(unittest.TestCase):
    def test_path_score_is_maximum_core_link_utilization(self):
        self.assertEqual(
            score_paths({'A': [62.0, 84.0], 'B': [48.0, 54.0]}),
            {'A': 84.0, 'B': 54.0},
        )

    def test_deterministic_tie_break_prefers_path_a(self):
        scores = {'A': 50.0, 'B': 50.0}
        self.assertEqual(best_path(scores), 'A')
        self.assertFalse(evaluate_policy_b('B', scores)['switch'])
        self.assertEqual(choose_static_path('B', scores), 'B')

    def test_policy_b_switches_to_a_lower_score(self):
        decision = evaluate_policy_b('A', {'A': 82.0, 'B': 57.0})
        self.assertTrue(decision['switch'])
        self.assertEqual(decision['selected_path'], 'B')

    def test_unavailable_path_is_excluded_from_path_scores(self):
        self.assertEqual(
            mask_unavailable_paths({'A': 0.0, 'B': 98.0}, {'A'}),
            {'A': None, 'B': 98.0},
        )

    def test_successful_path_count_ignores_rejected_switch_attempts(self):
        events = [
            {'decision': 'switch', 'path_changes_total': 1, 'flow_mod_install_succeeded': True},
            {'decision': 'switch', 'path_changes_total': 1, 'flow_mod_install_succeeded': False},
            {'decision': 'switch', 'path_changes_total': 1, 'flow_mod_install_succeeded': False},
        ]
        self.assertEqual(successful_path_change_count(events), 1)

    def test_invalid_path_and_missing_scores_are_rejected(self):
        with self.assertRaises(ValueError):
            choose_static_path('C')
        with self.assertRaises(ValueError):
            evaluate_policy_b('C', {'A': 30.0, 'B': 40.0})
        with self.assertRaises(ValueError):
            best_path({'A': 30.0, 'B': None})


class HysteresisAndDwellTests(unittest.TestCase):
    def test_margin_boundary_switches_and_below_boundary_holds(self):
        at_margin = evaluate_policy_c(
            'A', {'A': 60.0, 'B': 45.0}, switching_threshold=15.0,
            minimum_dwell_time_ms=0, elapsed_since_switch_ms=1000,
        )
        below_margin = evaluate_policy_c(
            'A', {'A': 60.0, 'B': 45.01}, switching_threshold=15.0,
            minimum_dwell_time_ms=0, elapsed_since_switch_ms=1000,
        )
        self.assertTrue(at_margin['switch'])
        self.assertFalse(below_margin['switch'])

    def test_dwell_blocks_then_allows_a_qualified_switch(self):
        blocked = evaluate_policy_c(
            'A', {'A': 80.0, 'B': 50.0}, switching_threshold=15.0,
            minimum_dwell_time_ms=5000, elapsed_since_switch_ms=4999,
        )
        allowed = evaluate_policy_c(
            'A', {'A': 80.0, 'B': 50.0}, switching_threshold=15.0,
            minimum_dwell_time_ms=5000, elapsed_since_switch_ms=5000,
        )
        self.assertFalse(blocked['switch'])
        self.assertIn('dwell', blocked['reason'])
        self.assertTrue(allowed['switch'])


class PortCounterTests(unittest.TestCase):
    def test_utilization_uses_byte_delta_interval_and_capacity(self):
        value, status = utilization_from_counters(1000, 1_001_000, 1.0, 10)
        self.assertEqual(status, 'ok')
        self.assertAlmostEqual(value, 80.0)

    def test_counter_wrap_and_short_interval_are_not_measurements(self):
        wrapped, wrap_status = utilization_from_counters(900, 100, 1.0, 10)
        short, short_status = utilization_from_counters(100, 200, 0.1, 10)
        self.assertIsNone(wrapped)
        self.assertEqual(wrap_status, 'counter_wrap_or_reset')
        self.assertIsNone(short)
        self.assertEqual(short_status, 'interval_too_short')


if __name__ == '__main__':
    unittest.main()
