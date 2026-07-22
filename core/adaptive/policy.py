# adaptive/policy.py

"""
Pure decision logic — takes stats in, returns a bitrate decision out.
No GStreamer, no networking here, so it's trivially unit-testable.
"""
import logging
from core.config import AdaptiveConfig, EncodeConfig

log = logging.getLogger(__name__)


class BitratePolicy:
    def __init__(self, adaptive: AdaptiveConfig, encode: EncodeConfig):
        self._cfg = adaptive
        self._enc = encode
        self.current_kbps = encode.initial_bitrate_kbps
        self._good_cycles = 0  # consecutive low-loss cycles, for step-up

    def decide(self, loss_fraction: float) -> int:
        """
        loss_fraction: 0.0-1.0, from RTCP receiver reports.
        Returns the new target bitrate in kbps (may be unchanged).
        """
        if loss_fraction >= self._cfg.loss_high_watermark:
            self._good_cycles = 0
            new_bitrate = max(
                self._enc.min_bitrate_kbps,
                self.current_kbps - self._cfg.step_kbps,
            )
            if new_bitrate != self.current_kbps:
                log.info(
                    "Loss %.1f%% >= watermark, stepping DOWN %d -> %d kbps",
                    loss_fraction * 100, self.current_kbps, new_bitrate,
                )
            self.current_kbps = new_bitrate

        elif loss_fraction <= self._cfg.loss_low_watermark:
            self._good_cycles += 1
            if self._good_cycles >= 3:  # require sustained good link before stepping up
                new_bitrate = min(
                    self._enc.max_bitrate_kbps,
                    self.current_kbps + self._cfg.step_kbps,
                )
                if new_bitrate != self.current_kbps:
                    log.info(
                        "Link stable, stepping UP %d -> %d kbps",
                        self.current_kbps, new_bitrate,
                    )
                self.current_kbps = new_bitrate
                self._good_cycles = 0
        else:
            self._good_cycles = 0  # in the middle zone, hold steady

        return self.current_kbps


