"""Tests for RInChI string construction from component InChIs."""

from inst2ord.rinchi import build_rinchi

WATER = "InChI=1S/H2O/h1H2"
PHENOL = "InChI=1S/C6H6O/c7-6-4-2-1-3-5-6/h1-5,7H"


def test_returns_none_without_structures():
    assert build_rinchi([None, None]) is None
    assert build_rinchi([]) is None


def test_single_reactant():
    assert build_rinchi([WATER]) == "RInChI=1.00.1S/<>H2O/h1H2/d-"


def test_components_sorted_and_prefix_stripped():
    out = build_rinchi([WATER, PHENOL])
    assert out.startswith("RInChI=1.00.1S/")
    assert "InChI=1S/" not in out  # per-component prefixes stripped
    assert out.endswith("/d-")
    # C6H6O sorts before H2O; components joined with '!'
    assert "C6H6O/c7-6-4-2-1-3-5-6/h1-5,7H!H2O/h1H2" in out


def test_no_structure_count_layer():
    assert build_rinchi([PHENOL, None]).endswith("/u0-1-0")


def test_products_set_layer_order_and_direction():
    # reactant H2O vs product C6H6O: C6H6O sorts first -> it is layer 2,
    # reactants land in layer 3, so direction is '-'.
    out = build_rinchi([WATER], [PHENOL])
    assert out.startswith("RInChI=1.00.1S/C6H6O")
    assert out.endswith("/d-")
