"""Placeholder for the team's own CUDA engine, loaded through its C ABI with ctypes.

Intentionally unimplemented: this is the fourth adapter behind the same WindSource interface. See
docs/LINKING_GUIDE.md for the exact functions the native library needs to export.
"""
from __future__ import annotations

from engine.wind.base import WindSourceBase


class NativeWind(WindSourceBase):
    name = "native"

    def __init__(self, dt_s: float = 0.05, **_: object) -> None:
        super().__init__(dt_s)
        raise NotImplementedError(
            "native.py is the slot for the team's own CUDA engine (C ABI via ctypes). "
            "See docs/LINKING_GUIDE.md for the contract to implement.")
