# core/gst_services/bus_handler.py

"""
Attaches to a GstPipeline's bus and routes messages to a logger.
Keeps error/EOS/state-change handling out of tx_pipeline.py / rx_pipeline.py.
"""
import logging
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

log = logging.getLogger(__name__)


class BusHandler:
    def __init__(self, pipeline: Gst.Pipeline, loop: GLib.MainLoop, on_error=None):
        self._pipeline = pipeline
        self._loop = loop
        self._on_error = on_error

        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_message)

    def _on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            log.info("EOS received, stopping pipeline")
            self._loop.quit()
        elif t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            log.error("GStreamer error: %s (%s)", err, debug)
            if self._on_error:
                self._on_error(err, debug)
            self._loop.quit()
        elif t == Gst.MessageType.WARNING:
            warn, debug = message.parse_warning()
            log.warning("GStreamer warning: %s (%s)", warn, debug)
        elif t == Gst.MessageType.STATE_CHANGED:
            if message.src == self._pipeline:
                old, new, pending = message.parse_state_changed()
                log.debug("Pipeline state: %s -> %s", old.value_name, new.value_name)


