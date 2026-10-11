#!/usr/bin/env python3
"""Launch SmartTE through the OS-Ken application API.

OS-Ken 4.x removed the old osken-manager command-line tools, so this short
entry point invokes the supported AppManager API directly.
"""

import logging
import os
import signal
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=os.environ.get('SMARTTE_LOG_LEVEL', 'INFO').upper(),
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
)

# OS-Ken defaults to native threads, but its AppManager shutdown path calls
# ``kill()`` on service threads, which native HubThread does not implement.
# Use the supported Eventlet hub so SIGTERM can close the app and stop services.
os.environ.setdefault('OSKEN_HUB_TYPE', 'eventlet')
from os_ken.lib import hub  # noqa: E402

hub.patch()


def _stop_controller(_signal, _frame):
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _stop_controller)
signal.signal(signal.SIGINT, _stop_controller)

from os_ken.base.app_manager import AppManager  # noqa: E402


if __name__ == '__main__':
    AppManager.run_apps(['controller.smartte_controller'])
