# apps/run_rx.py

#!/usr/bin/env python3
"""
Run on the Pi 4. Receives RTP/RTCP from the Pi 3B, decodes, and displays.
Also sends RTCP receiver reports back so the tx side's adaptive policy
has real loss/jitter data to react to.
"""
import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

from core.config import NETWORK
from core.gst_services.rx_pipeline import RxPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("run_rx")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-display", action="store_true",
        help="Run headless (fakesink) — useful over SSH without X forwarding",
    )
    args = parser.parse_args()

    Gst.init(None)
    loop = GLib.MainLoop()

    rx = RxPipeline(NETWORK, loop, display=not args.no_display)

    log.info(
        "Starting rx pipeline: listening on RTP:%d RTCP:%d, sending RR to %s:%d",
        NETWORK.rtp_port, NETWORK.rtcp_send_port,
        NETWORK.tx_host, NETWORK.rtcp_recv_port,
    )
    rx.start()

    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down")
    finally:
        rx.stop()


if __name__ == "__main__":
    main()


