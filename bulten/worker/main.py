"""Worker giriş noktası: `bulten worker` veya `python -m bulten.worker.main`."""
from __future__ import annotations

import logging
import signal

from ..config import load_config
from .scheduler import Scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_config()
    sched = Scheduler()

    def _stop(*_):
        logging.getLogger(__name__).info("Durduruluyor…")
        sched.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    sched.run_forever()


if __name__ == "__main__":
    main()
