import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from bulten.timeutil import set_clock  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_clock():
    yield
    set_clock(None)
