"""Parsers turning source files into :mod:`inst2ord.models` dataclasses."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

_XML_DECL_RE = re.compile(r"^\s*<\?xml[^>]*\?>", re.IGNORECASE)


def load_xml_root(path: str) -> ET.Element:
    """Parse an XML file that may be a multi-root fragment.

    The platform's ``*ChemFile.xml`` files contain two sibling top-level
    elements (``<...ChemicalManager>`` and
    ``<ChemicalsAndAssociatedDispenseModes>``) and therefore are not
    well-formed XML documents.  We strip any BOM and ``<?xml?>`` declaration
    and wrap the content in a synthetic root so a single parse works for
    both ChemFiles and the well-formed PromptFiles.

    Returns the synthetic ``<inst2ordRoot>`` element whose children are the
    document's original top-level elements.
    """
    with open(path, "r", encoding="utf-8-sig") as handle:
        text = handle.read()
    text = _XML_DECL_RE.sub("", text).strip()
    return ET.fromstring(f"<inst2ordRoot>{text}</inst2ordRoot>")


def text_or_none(element: ET.Element | None) -> str | None:
    """Return stripped element text, or ``None`` for missing/empty nodes."""
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None
