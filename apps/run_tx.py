# apps/run_tx.py

"""
Run on the Pi 3B. Captures from the camera, encodes H264, streams RTP/RTCP
to the Pi 4, and adapts bitrate based on RTCP loss feedback.
"""
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

from core.config import NETWORK, CAPTURE, ENCODE, ADAPTIVE
from core.gst_services.tx_pipeline import TxPipeline
from core.adaptive.policy import BitratePolicy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("run_tx")


def adaptive_tick(tx: TxPipeline, policy: BitratePolicy):
    stats = tx.get_rtcp_stats()
    loss_fraction = stats.get("loss_fraction", 0.0)
    log.info(
        "RTCP stats: loss=%.1f%% jitter=%s rtt=%s | current bitrate=%d kbps",
        loss_fraction * 100, stats.get("jitter"), stats.get("rtt"),
        policy.current_kbps,
    )
    new_bitrate = policy.decide(loss_fraction)
    tx.set_bitrate(new_bitrate)
    return True  # keep GLib timeout running


def main():
    Gst.init(None)
    loop = GLib.MainLoop()

    tx = TxPipeline(NETWORK, CAPTURE, ENCODE, loop)
    policy = BitratePolicy(ADAPTIVE, ENCODE)

    GLib.timeout_add_seconds(
        int(ADAPTIVE.eval_interval_s), adaptive_tick, tx, policy
    )

    log.info("Starting tx pipeline -> %s:%d", NETWORK.rx_host, NETWORK.rtp_port)
    tx.start()

    try:
        loop.run()
    except KeyboardInterrupt:
        log.info("Interrupted, shutting down")
    finally:
        tx.stop()


if __name__ == "__main__":
    main()

