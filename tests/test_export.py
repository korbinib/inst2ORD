"""Tests for serialising to web-app-importable files.

Assertions mirror exactly what ord-app does on import:
* Templates ▸ Import from JSON -> ``{binpb, variables}``, ``variables`` an
  array, ``binpb`` a base64 Reaction (``importFromFile``).
* Create Dataset from File -> parse the file as a ``Dataset``
  (``pb_utils.load_message``).
"""

import base64
import json

from google.protobuf import json_format, text_format
from ord_schema.proto import dataset_pb2, reaction_pb2

from inst2ord import export
from inst2ord.build_ord import build_dataset, build_reaction
from inst2ord.models import InputComponent, ReactionIntent, ROLE_REACTANT


def _intent():
    return ReactionIntent(
        run_id="Exp9", instrument="symyx-automation-studio",
        inputs=[InputComponent(name="water", role=ROLE_REACTANT)],
    )


def test_format_extensions():
    assert export.FORMAT_EXTENSIONS["template"] == "json"
    assert set(export.DATASET_FORMATS) == {"dataset", "binpb", "txtpb"}


def test_template_is_importable(tmp_path):
    path = tmp_path / "Exp9.json"
    export.write_template(build_reaction(_intent()), str(path))
    data = json.loads(path.read_text(encoding="utf-8"))

    # The app requires variables to be an array and binpb a base64 Reaction.
    assert set(data) == {"binpb", "variables"}
    assert isinstance(data["variables"], list)
    reaction = reaction_pb2.Reaction()
    reaction.ParseFromString(base64.b64decode(data["binpb"]))
    assert reaction.identifiers[0].value == "Exp9"
    assert "01_water" in reaction.inputs


def test_dataset_json_is_importable(tmp_path):
    path = tmp_path / "Exp9.json"
    export.write_dataset(build_dataset([_intent()]), str(path))
    parsed = json_format.Parse(path.read_text(encoding="utf-8"),
                               dataset_pb2.Dataset())
    assert parsed.name
    assert len(parsed.reactions) == 1
    assert parsed.reactions[0].identifiers[0].value == "Exp9"


def test_dataset_binpb_is_importable(tmp_path):
    path = tmp_path / "Exp9.binpb"
    export.write_dataset(build_dataset([_intent()]), str(path))
    parsed = dataset_pb2.Dataset.FromString(path.read_bytes())
    assert len(parsed.reactions) == 1


def test_dataset_txtpb_is_importable(tmp_path):
    path = tmp_path / "Exp9.txtpb"
    export.write_dataset(build_dataset([_intent()]), str(path))
    parsed = text_format.Parse(path.read_text(encoding="utf-8"),
                               dataset_pb2.Dataset())
    assert len(parsed.reactions) == 1
