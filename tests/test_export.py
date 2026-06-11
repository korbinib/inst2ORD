"""Tests for serialising built messages to importable files."""

import base64
import json

from ord_schema import message_helpers
from ord_schema.proto import dataset_pb2, reaction_pb2

from inst2ord import export
from inst2ord.build_ord import build_dataset, build_reaction
from inst2ord.models import InputComponent, ReactionIntent, ROLE_REACTANT


def _reaction(run_id="Exp9"):
    intent = ReactionIntent(
        run_id=run_id, instrument="symyx-automation-studio",
        inputs=[InputComponent(name="water", role=ROLE_REACTANT)],
    )
    return build_reaction(intent)


def test_template_payload_shape_and_roundtrip():
    payload = export.template_payload(_reaction(), "Exp9")
    assert set(payload) == {"name", "binpb", "variables"}
    assert payload["name"] == "Exp9"
    assert payload["variables"] == {}  # no enumeration placeholders

    decoded = reaction_pb2.Reaction()
    decoded.ParseFromString(base64.b64decode(payload["binpb"]))
    assert decoded.identifiers[0].value == "Exp9"
    assert "01_water" in decoded.inputs


def test_write_template_file(tmp_path):
    path = tmp_path / "Exp9.json"
    export.write_template(_reaction(), "Exp9", str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data) == {"name", "binpb", "variables"}
    decoded = reaction_pb2.Reaction()
    decoded.ParseFromString(base64.b64decode(data["binpb"]))
    assert decoded.identifiers[0].value == "Exp9"


def test_template_matches_ord_app_contract():
    """Mirror ord-app's TemplateCreateModel acceptance (offline).

    The web app validates a template by base64-decoding ``binpb`` and
    parsing it as a Reaction (``load_message(b64decode(raw), Reaction)``),
    requires a string ``name`` and a JSON-object ``variables``.  If this
    passes, the template is importable by the app.
    """
    payload = export.template_payload(_reaction("Exp42"), "Exp42")
    assert isinstance(payload["name"], str) and payload["name"]
    assert isinstance(payload["variables"], dict)
    json.dumps(payload["variables"])  # variables must be JSON-serialisable
    # The exact deserialisation the app performs must not raise:
    reaction_pb2.Reaction.FromString(base64.b64decode(payload["binpb"]))


def test_write_message_dataset_roundtrips(tmp_path):
    intent = ReactionIntent(
        run_id="Exp9", instrument="x",
        inputs=[InputComponent(name="water", role=ROLE_REACTANT)],
    )
    path = tmp_path / "ds.pb.gz"
    export.write_message(build_dataset([intent]), str(path))
    loaded = message_helpers.load_message(str(path), dataset_pb2.Dataset)
    assert len(loaded.reactions) == 1
