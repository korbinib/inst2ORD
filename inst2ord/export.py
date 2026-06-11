"""Serialise built ORD messages to importable files.

Two output families are supported (selected by the CLI ``--format``):

* **template** (default) -- a JSON file for the ORD web app
  (``app.open-reaction-database.org``, the ``ord-app`` Contribution Editor),
  which stores a template as a *single Reaction*.  Its create payload is
  ``{"name": ..., "binpb": <base64 Reaction protobuf>, "variables": {...}}``
  (see ord-app ``TemplateCreateModel``).  :func:`write_template` emits
  exactly that, so the file can be imported as a template.
* **protobuf** -- a ``Dataset`` written as binary ``.pb(.gz)`` or text
  ``.pbtxt`` via :func:`write_message` (delegates to ``ord_schema``); this is
  the dataset-level interchange/archival format and retains maDMP
  Dataset-level metadata that a single-reaction template cannot.
"""

from __future__ import annotations

import base64
import json

from ord_schema import message_helpers
from ord_schema.proto import reaction_pb2


def template_payload(
    reaction: reaction_pb2.Reaction,
    name: str,
    variables: dict | None = None,
) -> dict:
    """Return an ord-app template-create payload for one reaction.

    ``variables`` are enumeration placeholders (``$name$``); inst2ord does
    not generate any, so it defaults to ``{}``.
    """
    serialized = reaction.SerializeToString()
    return {
        "name": name,
        "binpb": base64.b64encode(serialized).decode("ascii"),
        "variables": variables if variables is not None else {},
    }


def write_template(
    reaction: reaction_pb2.Reaction, name: str, path: str
) -> None:
    """Write an ord-app template JSON file for ``reaction``."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(template_payload(reaction, name), handle, indent=2)


def write_message(message, path: str) -> None:
    """Write a proto message as ``.pb(.gz)``/``.pbtxt``/``.json``.

    Delegates to ``ord_schema`` so the format follows the file extension.
    """
    message_helpers.write_message(message, path)
