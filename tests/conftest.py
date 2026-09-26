import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from bulten.sources import reddit_api  # noqa: E402
from bulten.timeutil import set_clock  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_global_state():
    yield
    set_clock(None)
    reddit_api.reset_state()
