# core/gst_services/pipeline_builder.py

"""
Low-level element creation helpers. This module knows GStreamer syntax;
it should NOT know anything about adaptive policy or network monitoring —
tx_pipeline.py / rx_pipeline.py own the wiring, adaptive/ owns the decisions.
"""
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst


def make(factory_name: str, name: str = None) -> Gst.Element:
    elem = Gst.ElementFactory.make(factory_name, name)
    if elem is None:
        raise RuntimeError(
            f"Failed to create element '{factory_name}'. "
            f"Is the relevant GStreamer plugin package installed?"
        )
    return elem


def link_many(*elements: Gst.Element) -> None:
    for a, b in zip(elements, elements[1:]):
        if not a.link(b):
            raise RuntimeError(f"Failed to link {a.get_name()} -> {b.get_name()}")


