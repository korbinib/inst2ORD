"""Instrument-adapter registry.

Register new instruments by adding their adapter class to ``_ADAPTERS``.
Nothing else in inst2ord needs to change to support another instrument.
"""

from __future__ import annotations

import os

from inst2ord.adapters.base import InstrumentAdapter
from inst2ord.adapters.symyx_automation_studio import (
    SymyxAutomationStudioAdapter,
)

# All known adapters, in detection-preference order.
_ADAPTERS: list[type[InstrumentAdapter]] = [
    SymyxAutomationStudioAdapter,
]


def available_adapters() -> list[InstrumentAdapter]:
    """Return one instance of every registered adapter."""
    return [cls() for cls in _ADAPTERS]


def get_adapter(name: str) -> InstrumentAdapter:
    """Return the adapter registered under ``name``."""
    for adapter in available_adapters():
        if adapter.name == name:
            return adapter
    known = ", ".join(a.name for a in available_adapters())
    raise KeyError(f"Unknown instrument adapter {name!r}. Known: {known}")


def detect_adapter(input_dir: str) -> InstrumentAdapter | None:
    """Auto-detect the adapter for ``input_dir`` by sniffing its files."""
    paths = [
        os.path.join(input_dir, name)
        for name in sorted(os.listdir(input_dir))
        if os.path.isfile(os.path.join(input_dir, name))
    ]
    for adapter in available_adapters():
        if any(adapter.sniff(path) for path in paths):
            return adapter
    return None


__all__ = [
    "InstrumentAdapter",
    "available_adapters",
    "get_adapter",
    "detect_adapter",
]
