"""Static path policy shared by the SmartTE controller."""


def choose_static_path(initial_path, _scores=None):
    """Keep the configured path; static policy never reacts to telemetry."""
    if initial_path not in ('A', 'B'):
        raise ValueError(f'Invalid path {initial_path!r}; expected A or B.')
    return initial_path
