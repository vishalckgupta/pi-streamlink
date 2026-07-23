# core/gst_services/rx_pipeline.py

"""
Builds and controls the receive-side pipeline (Pi 4):

  udpsrc (RTP)  -> rtpbin.recv_rtp_sink_0
  udpsrc (RTCP SR from tx) -> rtpbin.recv_rtcp_sink_0
  rtpbin.recv_rtp_src_* (created dynamically on first packet)
      -> rtph264depay -> h264parse -> avdec_h264 -> videoconvert -> sink
  rtpbin.send_rtcp_src_0 (created dynamically) -> udpsink -> back to tx
      (this is what lets tx_pipeline.py's RTCP polling see real loss/jitter)

IMPORTANT: unlike the tx side, recv_rtp_src_* does NOT exist until rtpbin
actually receives a valid RTP packet — it's a "sometimes" pad, not created
synchronously on pad request. The pad-added signal MUST be connected before
any pad is requested, or you can miss it entirely (see tx_pipeline.py history).
"""
import logging
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

from core.gst_services.pipeline_builder import make
from core.gst_services.bus_handler import BusHandler
from core.config import NetworkConfig

log = logging.getLogger(__name__)


class RxPipeline:
    def __init__(self, net: NetworkConfig, loop, display: bool = True):
        self._net = net
        self.pipeline = Gst.Pipeline.new("rx-pipeline")

        # --- receive-side elements ---
        rtp_src = make("udpsrc", "rtp-src")
        rtp_src.set_property("port", net.rtp_port)
        rtp_caps = Gst.Caps.from_string(
            "application/x-rtp,media=video,clock-rate=90000,"
            "encoding-name=H264,payload=96"
        )
        rtp_src.set_property("caps", rtp_caps)

        rtcp_src = make("udpsrc", "rtcp-src")   # incoming RTCP SR from tx
        rtcp_src.set_property("port", net.rtcp_send_port)

        rtcp_sink = make("udpsink", "rtcp-sink")  # outgoing RTCP RR back to tx
        rtcp_sink.set_property("host", net.tx_host)
        rtcp_sink.set_property("port", net.rtcp_recv_port)
        rtcp_sink.set_property("sync", False)
        rtcp_sink.set_property("async", False)

        self._rtpbin = make("rtpbin", "rtpbin")

        depay = make("rtph264depay", "depay")
        parse = make("h264parse", "parse")
        decoder = make("avdec_h264", "decoder")
        convert = make("videoconvert", "convert")
        sink = make("autovideosink" if display else "fakesink", "sink")
        if display:
            sink.set_property("sync", False)

        for e in (rtp_src, rtcp_src, rtcp_sink, self._rtpbin,
                  depay, parse, decoder, convert, sink):
            self.pipeline.add(e)

        # depay -> parse -> decoder -> convert -> sink (static chain, safe to link now)
        depay.link(parse)
        parse.link(decoder)
        decoder.link(convert)
        convert.link(sink)

        # Connect pad-added BEFORE requesting any pads — recv_rtp_src_* and
        # send_rtcp_src_0 are both created dynamically by rtpbin and we must
        # not miss those signals.
        self._rtpbin.connect("pad-added", self._on_rtpbin_pad_added, depay, rtcp_sink)

        # RTP in -> rtpbin
        rtp_src.get_static_pad("src").link(
            self._rtpbin.get_request_pad("recv_rtp_sink_0")
        )
        # RTCP SR in (from tx) -> rtpbin
        rtcp_src.get_static_pad("src").link(
            self._rtpbin.get_request_pad("recv_rtcp_sink_0")
        )

        self._loop = loop
        self._bus_handler = BusHandler(self.pipeline, loop)

    def _on_rtpbin_pad_added(self, rtpbin, pad, depay, rtcp_sink):
        name = pad.get_name()
        if name.startswith("recv_rtp_src"):
            log.info("rtpbin created %s, linking to depayloader", name)
            pad.link(depay.get_static_pad("sink"))
        elif name.startswith("send_rtcp_src"):
            log.info("rtpbin created %s, linking RTCP RR back to tx", name)
            pad.link(rtcp_sink.get_static_pad("sink"))

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)

