"""Build a Reaction InChI (RInChI) string from component InChIs.

RInChI (IUPAC, v1.00) identifies a *reaction* and is assembled directly from
the standard InChIs of the components -- which inst2ord already resolves --
so no extra toolkit is needed to construct the string:

    RInChI=1.00.1S/<layer2>/<layer3>/<agents>/d<dir>/u<n-n-n>

* component InChIs have their ``InChI=1S/`` prefix stripped and are joined
  with ``!`` within a group; the two reaction sides are separated by ``<>``;
* the two sides are ordered alphabetically by their aggregate string (the
  smaller becomes layer 2) and ``/d+`` or ``/d-`` records which side is the
  starting material; ``/d=`` is equilibrium (not produced here);
* ``/u`` counts components with no structure (e.g. unresolved names) per
  group; it is omitted when all counts are zero;
* agents (species on both sides) -- none for a reactant-only template.

This produces the canonical-format RInChI *string*. Generating the hashed
**RInChIKey** still requires the official IUPAC RInChI software and is out of
scope here.
"""

from __future__ import annotations

from collections.abc import Iterable

_STD_PREFIX = "InChI=1S/"


def _bodies(inchis: Iterable[str | None]) -> tuple[list[str], int]:
    """Return (sorted stripped InChI bodies, count of no-structure items)."""
    bodies: list[str] = []
    no_structure = 0
    for inchi in inchis:
        if inchi and inchi.startswith(_STD_PREFIX):
            bodies.append(inchi[len(_STD_PREFIX):])
        else:
            no_structure += 1  # missing or non-standard InChI
    return sorted(bodies), no_structure


def build_rinchi(
    reactants: Iterable[str | None],
    products: Iterable[str | None] = (),
    agents: Iterable[str | None] = (),
) -> str | None:
    """Build a RInChI string, or ``None`` if no component has a structure."""
    r_bodies, r_ns = _bodies(reactants)
    p_bodies, p_ns = _bodies(products)
    a_bodies, a_ns = _bodies(agents)
    if not (r_bodies or p_bodies or a_bodies):
        return None

    r_agg, p_agg = "!".join(r_bodies), "!".join(p_bodies)
    if r_agg <= p_agg:
        layer2, layer3, direction = r_agg, p_agg, "+"
        counts = (r_ns, p_ns, a_ns)
    else:
        layer2, layer3, direction = p_agg, r_agg, "-"
        counts = (p_ns, r_ns, a_ns)

    rinchi = f"RInChI=1.00.1S/{layer2}<>{layer3}"
    if a_bodies:
        rinchi += "<>" + "!".join(a_bodies)
    rinchi += f"/d{direction}"
    if any(counts):
        rinchi += "/u{}-{}-{}".format(*counts)
    return rinchi
