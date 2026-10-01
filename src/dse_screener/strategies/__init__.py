"""Strategy plugins. To add one: write a Strategy subclass and register it here;
its parameters then become configurable in config/profiles/*.yaml."""

from .base import Strategy
from .base_breakout import BaseBreakout
from .big_hands import BigHands
from .quiet_accumulation import QuietAccumulation
from .second_breakout import SecondBreakout

REGISTRY: dict[str, type[Strategy]] = {
    cls.name: cls for cls in (QuietAccumulation, BaseBreakout, BigHands, SecondBreakout)
}

__all__ = ["REGISTRY", "Strategy"]
