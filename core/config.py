# core/config.py

"""
Central configuration. Keep all tunables here so apps/ and core/ never
hardcode ports, caps, or defaults.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkConfig:
    rx_host: str = "192.168.1.50"   # Pi 4 IP — set to your actual receiver address
    rtp_port: int = 5000            # video RTP
    rtcp_send_port: int = 5001      # tx -> rx RTCP SR
    rtcp_recv_port: int = 5002      # rx -> tx RTCP RR (loss/jitter feedback)


@dataclass(frozen=True)
class CaptureConfig:
    width: int = 1280
    height: int = 720
    framerate: int = 30
    device: str = "/dev/video0"


@dataclass(frozen=True)
class EncodeConfig:
    initial_bitrate_kbps: int = 2000     # starting point, policy.py adjusts from here
    min_bitrate_kbps: int = 300
    max_bitrate_kbps: int = 4000
    keyframe_interval_s: int = 2


@dataclass(frozen=True)
class AdaptiveConfig:
    eval_interval_s: float = 2.0     # how often policy.py checks RTCP stats
    loss_high_watermark: float = 0.05   # >5% loss -> step down
    loss_low_watermark: float = 0.01    # <1% loss for N cycles -> step up
    step_kbps: int = 300


NETWORK = NetworkConfig()
CAPTURE = CaptureConfig()
ENCODE = EncodeConfig()
ADAPTIVE = AdaptiveConfig()

