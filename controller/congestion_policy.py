"""Pure path-choice and port-counter helpers, independent of Mininet/OS-Ken."""

VALID_PATHS = ('A', 'B')
DEFAULT_EPSILON = 0.01  # utilisation percentage points; avoids float flapping.


def mask_unavailable_paths(scores, unavailable_paths):
    """Make a failed path ineligible for best-path selection."""
    unavailable = set(unavailable_paths)
    return {
        path: None if path in unavailable else scores.get(path)
        for path in VALID_PATHS
    }


def successful_path_change_count(events):
    """Count committed route transitions, not rejected switch decisions."""
    totals = [
        int(event['path_changes_total'])
        for event in events
        if isinstance(event.get('path_changes_total'), (int, float))
    ]
    if totals:
        return max(totals)
    return sum(event.get('decision') == 'switch' for event in events)


def score_paths(link_utilization):
    """Return each path's worst core-link utilisation, or None if incomplete."""
    result = {}
    for path in VALID_PATHS:
        samples = link_utilization.get(path)
        if not samples or any(value is None for value in samples):
            result[path] = None
        else:
            result[path] = max(float(value) for value in samples)
    return result


def best_path(scores, tie_break='A', epsilon=DEFAULT_EPSILON):
    """Choose the lower score; ties within epsilon deterministically prefer A."""
    if tie_break not in VALID_PATHS:
        raise ValueError(f'Invalid tie-break path {tie_break!r}.')
    if any(scores.get(path) is None for path in VALID_PATHS):
        raise ValueError('Both Path A and Path B need valid scores.')
    difference = float(scores['A']) - float(scores['B'])
    if abs(difference) <= epsilon:
        return tie_break
    return 'A' if difference < 0 else 'B'


def utilization_from_counters(previous_bytes, current_bytes, elapsed_s, capacity_mbps,
                              minimum_interval_s=0.5):
    """Convert tx-byte deltas to percent; reject wrap and too-short windows."""
    if previous_bytes is None or current_bytes is None:
        return None, 'counter_unavailable'
    if current_bytes < previous_bytes:
        return None, 'counter_wrap_or_reset'
    if elapsed_s < minimum_interval_s:
        return None, 'interval_too_short'
    if capacity_mbps <= 0:
        return None, 'invalid_capacity'
    value = ((current_bytes - previous_bytes) * 8) / (elapsed_s * capacity_mbps * 1_000_000) * 100
    return value, 'ok'


def evaluate_policy_b(current_path, scores, epsilon=DEFAULT_EPSILON):
    """Switch to the best path whenever its score is measurably lower."""
    if current_path not in VALID_PATHS:
        raise ValueError(f'Invalid current path {current_path!r}; expected A or B.')
    candidate = best_path(scores, epsilon=epsilon)
    current_score = float(scores[current_path])
    candidate_score = float(scores[candidate])
    improvement = current_score - candidate_score
    should_switch = candidate != current_path and improvement > epsilon
    return {
        'candidate_path': candidate,
        'selected_path': candidate if should_switch else current_path,
        'switch': should_switch,
        'improvement_pct_points': improvement,
        'reason': 'switch: lower congestion score' if should_switch else 'hold: current path is best or tied',
    }


def evaluate_policy_c(current_path, scores, switching_threshold=15.0,
                      minimum_dwell_time_ms=5000, elapsed_since_switch_ms=0,
                      epsilon=DEFAULT_EPSILON):
    """Apply B's best-path rule plus a switching margin and a dwell timer."""
    if current_path not in VALID_PATHS:
        raise ValueError(f'Invalid current path {current_path!r}; expected A or B.')
    if switching_threshold < 0 or minimum_dwell_time_ms < 0:
        raise ValueError('Threshold and dwell time must be non-negative.')
    candidate = best_path(scores, epsilon=epsilon)
    current_score = float(scores[current_path])
    candidate_score = float(scores[candidate])
    improvement = current_score - candidate_score

    if candidate == current_path:
        should_switch = False
        reason = 'hold: current path is best or tied'
    elif elapsed_since_switch_ms < minimum_dwell_time_ms:
        should_switch = False
        reason = f'held: dwell {elapsed_since_switch_ms:.0f} < {minimum_dwell_time_ms:.0f} ms'
    elif improvement < switching_threshold:
        should_switch = False
        reason = (
            f'held: improvement {improvement:.2f} < margin '
            f'{switching_threshold:.2f} percentage points'
        )
    else:
        should_switch = True
        reason = (
            f'switch: improvement {improvement:.2f} >= margin '
            f'{switching_threshold:.2f} percentage points'
        )

    return {
        'candidate_path': candidate,
        'selected_path': candidate if should_switch else current_path,
        'switch': should_switch,
        'improvement_pct_points': improvement,
        'reason': reason,
    }
