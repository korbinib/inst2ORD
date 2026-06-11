"""Pytest bootstrap: make the project root importable and share fixtures."""

import os
import sys

import pytest

_ROOT = os.path.dirname(__file__)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_EXAMPLES = os.path.join(_ROOT, "examples")


@pytest.fixture
def examples_dir():
    """Directory of the bundled instrument XML examples."""
    return os.path.join(_EXAMPLES, "xmls")


@pytest.fixture
def madmp_example():
    """Path to the bundled RDA ex9 maDMP example."""
    return os.path.join(_EXAMPLES, "madmp", "ex9-dmp-long.json")
