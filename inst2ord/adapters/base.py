"""The instrument-adapter contract.

An adapter encapsulates everything specific to one instrument's native
output: how its files are recognised, how related files are grouped into
logical runs, and how each run is parsed into the neutral
:class:`~inst2ord.models.ReactionIntent`.  Everything downstream of an
adapter is instrument-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from inst2ord.models import ReactionIntent


class InstrumentAdapter(ABC):
    """Base class for instrument adapters.

    Subclasses set :attr:`name` (a stable, unique identifier used on the
    command line) and implement :meth:`sniff` and :meth:`parse_dir`.
    """

    #: Stable identifier, e.g. ``"symyx-automation-studio"``.
    name: str = ""
    #: Human-readable one-line description.
    description: str = ""

    @abstractmethod
    def sniff(self, path: str) -> bool:
        """Return True if ``path`` looks like a file from this instrument.

        Should be cheap (read only a small prefix) and side-effect free; it
        is used for auto-detecting the adapter for a directory.
        """

    @abstractmethod
    def parse_dir(self, input_dir: str) -> list[ReactionIntent]:
        """Discover logical runs under ``input_dir`` and parse each one.

        Returns one :class:`ReactionIntent` per logical run (for this
        instrument, per ``Exp###``).
        """
