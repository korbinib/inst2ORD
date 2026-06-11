"""Serialise built ORD messages to web-app-importable files.

The ORD web app (``app.open-reaction-database.org``) has two import paths,
with different formats:

* **Templates ▸ Import from JSON** -- a JSON file
  ``{"binpb": <base64 Reaction protobuf>, "variables": []}``.  ``binpb`` is a
  single ``Reaction``; ``variables`` must be a JSON *array* of enumeration
  placeholders (empty when there are none); the template name is entered in
  the import dialog, not the file.  This matches the app's own template JSON
  export (ord-app ``importFromFile`` / ``downloadTemplateInJSON``).
  :func:`write_template` emits this.
* **Create Dataset from File** -- a ``Dataset`` message as ``.json`` /
  ``.binpb`` / ``.txtpb`` (ord-app ``pb_utils.load_message``).
  :func:`write_dataset` emits this.
"""

from __future__ import annotations

import base64
import json

from ord_schema import message_helpers
from ord_schema.proto import dataset_pb2, reaction_pb2

# CLI --format -> file extension.
FORMAT_EXTENSIONS = {
    "template": "json",   # Templates > Import from JSON (a single Reaction)
    "dataset": "json",    # Create Dataset from File (a Dataset, JSON)
    "binpb": "binpb",     # Create Dataset from File (a Dataset, binary)
    "txtpb": "txtpb",     # Create Dataset from File (a Dataset, text)
}
# Formats that produce a Dataset (the rest produce a single-Reaction template).
DATASET_FORMATS = ("dataset", "binpb", "txtpb")


def write_template(reaction: reaction_pb2.Reaction, path: str) -> None:
    """Write a Templates ▸ Import from JSON file for one reaction.

    Shape: ``{"binpb": <base64 Reaction>, "variables": []}``.
    """
    serialized = reaction.SerializeToString()
    payload = {
        "binpb": base64.b64encode(serialized).decode("ascii"),
        "variables": [],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def write_dataset(dataset: dataset_pb2.Dataset, path: str) -> None:
    """Write ``dataset`` to ``path``; the extension selects the format."""
    message_helpers.write_message(dataset, path)
