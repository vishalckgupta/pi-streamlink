# core/gst_services/tx_pipeline.py

"""
Builds and controls the transmit-side pipeline (Pi 3B):

  libcamerasrc ->  [videoconvert|v4l2convert] -> [x264enc|v4l2h264enc] 
    -> h264parse -> rtph264pay -> rtpbin -> udpsink (RTP)
    Encoder backend controlled by EncodeConfig.backend ("sw"/"hw") — see
  core/config.py for why "sw" is the current default on the Pi 3B.
  rtpbin -> udpsink (RTCP SR, our outgoing reports)
  udpsrc (RTCP RR, receiver's loss/jitter feedback) -> rtpbin

Exposes:
  - set_bitrate(kbps): live-adjust encoder bitrate (called by adaptive/policy.py)
  - get_rtcp_stats(): last-known loss fraction / jitter from receiver reports
"""
import logging
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from core.gst_services.pipeline_builder import make, link_many
from core.gst_services.bus_handler import BusHandler
from core.config import NetworkConfig, CaptureConfig, EncodeConfig

log = logging.getLogger(__name__)


class TxPipeline:
    def __init__(self, net: NetworkConfig, cap: CaptureConfig, enc: EncodeConfig, loop):
        self._net = net
        self._enc = enc
        self._latest_stats = {"loss_fraction": 0.0, "jitter": 0}

        self.pipeline = Gst.Pipeline.new("tx-pipeline")

        # --- capture + encode chain ---
        src = make("libcamerasrc", "cam-src")
        caps_filter = make("capsfilter", "cam-caps")
        caps_filter.set_property(
            "caps",
            Gst.Caps.from_string(
                f"video/x-raw,width={cap.width},height={cap.height},"
                f"framerate={cap.framerate}/1"
            ),
        )
        self._backend = enc.backend
        if self._backend == "hw":
            convert = make("v4l2convert", "convert")
            self._encoder = make("v4l2h264enc", "enc")
        else:
            convert = make("videoconvert", "convert")
            self._encoder = make("x264enc", "enc")
            self._encoder.set_property("tune", "zerolatency")
            self._encoder.set_property("speed-preset", "ultrafast")
            self._encoder.set_property("key-int-max", enc.keyframe_interval_s * cap.framerate)
        self._apply_bitrate(enc.initial_bitrate_kbps)
        parse = make("h264parse", "parse")
        payload = make("rtph264pay", "pay")
        payload.set_property("config-interval", 1)
        payload.set_property("pt", 96)

        # --- rtpbin: handles RTP send + RTCP send/recv in one element ---
        self._rtpbin = make("rtpbin", "rtpbin")
        self._rtpbin.set_property("do-retransmission", False)
        #self._rtpbin.connect("on-app-rtcp", self._on_app_rtcp)

        rtp_sink = make("udpsink", "rtp-sink")
        rtp_sink.set_property("host", net.rx_host)
        rtp_sink.set_property("port", net.rtp_port)
        rtp_sink.set_property("sync", False)
        rtp_sink.set_property("async", False)

        rtcp_sink = make("udpsink", "rtcp-sink")
        rtcp_sink.set_property("host", net.rx_host)
        rtcp_sink.set_property("port", net.rtcp_send_port)
        rtcp_sink.set_property("sync", False)
        rtcp_sink.set_property("async", False)

        rtcp_src = make("udpsrc", "rtcp-src")
        rtcp_src.set_property("port", net.rtcp_recv_port)

        for e in (src, caps_filter, convert, self._encoder, parse, payload,
                  self._rtpbin, rtp_sink, rtcp_sink, rtcp_src):
            self.pipeline.add(e)

        link_many(src, caps_filter, convert, self._encoder, parse, payload)

        # payload -> rtpbin.send_rtp_sink_0 -> rtp_sink
        payload.get_static_pad("src").link(
            self._rtpbin.get_request_pad("send_rtp_sink_0")
        )
        self._rtpbin.connect(
            "pad-added", self._on_rtpbin_pad_added, rtp_sink, rtcp_sink
        )

        # rtpbin RTCP send -> rtcp_sink handled in pad-added above
        # incoming RTCP (receiver reports) -> rtpbin
        rtcp_src.get_static_pad("src").link(
            self._rtpbin.get_request_pad("recv_rtcp_sink_0")
        )

        self._loop = loop
        self._bus_handler = BusHandler(self.pipeline, loop)

        # poll RTCP stats periodically instead of relying only on signals
        from gi.repository import GLib
        GLib.timeout_add_seconds(1, self._poll_rtcp_stats)

    def _on_rtpbin_pad_added(self, rtpbin, pad, rtp_sink, rtcp_sink):
        name = pad.get_name()
        if name.startswith("send_rtp_src"):
            pad.link(rtp_sink.get_static_pad("sink"))
        elif name.startswith("send_rtcp_src"):
            pad.link(rtcp_sink.get_static_pad("sink"))

    def _poll_rtcp_stats(self):
        """
        Pull loss fraction / jitter from the RTP source stats that rtpbin
        maintains for the receiver report it gets back from the Pi 4.
        """
        try:
            session = self._rtpbin.emit("get-internal-session", 0)
            if session is None:
                return True
            # session has a 'sources' property listing RTPSource objects
            sources = session.get_property("sources")
            for src in sources:
                stats = src.get_property("stats")
                if stats and stats.get_value("is-sender") is False:
                    # this is a remote source giving us receiver-report data
                    self._latest_stats["jitter"] = stats.get_value("jitter") or 0
                    # 'octets-received' etc. are also available if needed
        except Exception as exc:
            log.debug("RTCP stats poll skipped: %s", exc)
        return True  # keep the GLib timeout running

    def get_rtcp_stats(self) -> dict:
        return dict(self._latest_stats)

    def _apply_bitrate(self, kbps: int):
        # v4l2h264enc exposes bitrate via extra-controls (v4l2 control interface)
        self._encoder.set_property(
            "extra-controls",
            Gst.Structure.new_from_string(
                f"controls,video_bitrate={kbps * 1000}"
            ),
        )

    def set_bitrate(self, kbps: int):
        kbps = max(self._enc.min_bitrate_kbps, min(self._enc.max_bitrate_kbps, kbps))
        log.info("Adjusting encoder bitrate -> %d kbps", kbps)
        self._apply_bitrate(kbps)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)

