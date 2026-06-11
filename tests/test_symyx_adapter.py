"""Tests for the Symyx Automation Studio adapter and XML parsing."""

from inst2ord.adapters import detect_adapter
from inst2ord.adapters.symyx_automation_studio import (
    SymyxAutomationStudioAdapter,
)
from inst2ord.models import ROLE_REACTANT, ROLE_SOLVENT

_CHEMFILE = """\
<Symyx.AutomationStudio.Core.ChemicalManager>
\t<Symyx.AutomationStudio.Core.ChemicalManager.Chemicals>
\t\t<Symyx.AutomationStudio.Core.ChemicalManager.Chemical>
\t\t\t<Name>phenol, 1.6 mg in 4 mL H20</Name>
\t\t\t<Type>stNormal</Type>
\t\t\t<SubstrateType>Rack 8x12 1mL Vial</SubstrateType>
\t\t\t<SubstratePosition>Deck 8-9 Heat-Stir 2</SubstratePosition>
\t\t\t<Row>0</Row><Column>0</Column><Units>undefined</Units>
\t\t</Symyx.AutomationStudio.Core.ChemicalManager.Chemical>
\t\t<Symyx.AutomationStudio.Core.ChemicalManager.Chemical>
\t\t\t<Name>water</Name>
\t\t\t<Type>stBackingSolvent</Type>
\t\t</Symyx.AutomationStudio.Core.ChemicalManager.Chemical>
\t\t<Symyx.AutomationStudio.Core.ChemicalManager.Chemical>
\t\t\t<Name>Sample plate</Name>
\t\t\t<Type>stPlate</Type>
\t\t\t<SubstrateType>Rack 4x6 4mL Vial</SubstrateType>
\t\t</Symyx.AutomationStudio.Core.ChemicalManager.Chemical>
\t</Symyx.AutomationStudio.Core.ChemicalManager.Chemicals>
\t<Symyx.AutomationStudio.Core.ChemicalManager.Libraries />
</Symyx.AutomationStudio.Core.ChemicalManager>
<ChemicalsAndAssociatedDispenseModes>
<ChemicalManager>
  <Chemical Name="water" Mode="Non-Viscous Liquid|ADT" />
</ChemicalManager>
</ChemicalsAndAssociatedDispenseModes>
"""

_PROMPTFILE = """\
<?xml version="1.0" encoding="utf-8" ?>
<promptsOptionsConfiguration>
  <categories>
    <category description="Design loading" name="DesignLoadingOption">
      <prompts>
        <prompt name="ForceHardwareInitialization" type="List[System.String]"
                description="Force hardware initialization">@No;Yes</prompt>
        <prompt name="EmailNotificationList" type="List[System.String]"
                description="Email notification list">a@x.org;b@y.org</prompt>
      </prompts>
    </category>
  </categories>
</promptsOptionsConfiguration>
"""


def _make_run(tmp_path):
    (tmp_path / "Exp001ChemFile.xml").write_text(_CHEMFILE, encoding="utf-8")
    (tmp_path / "Exp001Prompt.xml").write_text(_PROMPTFILE, encoding="utf-8")


def test_sniff(tmp_path):
    adapter = SymyxAutomationStudioAdapter()
    chem = tmp_path / "Exp001ChemFile.xml"
    chem.write_text(_CHEMFILE, encoding="utf-8")
    other = tmp_path / "notes.txt"
    other.write_text("hello", encoding="utf-8")
    assert adapter.sniff(str(chem)) is True
    assert adapter.sniff(str(other)) is False


def test_parse_inline_run(tmp_path):
    _make_run(tmp_path)
    adapter = SymyxAutomationStudioAdapter()
    intents = adapter.parse_dir(str(tmp_path))
    assert len(intents) == 1
    intent = intents[0]
    assert intent.run_id == "Exp001"

    # Plate is labware, not an input; reagent + solvent are inputs.
    assert len(intent.inputs) == 2
    assert len(intent.labware) == 1
    phenol = intent.inputs[0]
    assert phenol.role == ROLE_REACTANT
    assert phenol.amount_text == "1.6 mg"
    water = intent.inputs[1]
    assert water.role == ROLE_SOLVENT
    assert water.extra["DispenseMode"] == "Non-Viscous Liquid|ADT"

    # PromptFile: '@' marks the selected option; emails are collected.
    force = next(o for o in intent.setup_options
                 if o.name == "ForceHardwareInitialization")
    assert force.value == "No"
    assert force.options == ["No", "Yes"]
    assert intent.provenance.operator_emails == ["a@x.org", "b@y.org"]


def test_parse_bundled_examples(examples_dir):
    adapter = detect_adapter(examples_dir)
    assert adapter is not None
    assert adapter.name == "symyx-automation-studio"

    intents = {i.run_id: i for i in adapter.parse_dir(examples_dir)}
    assert "Exp333" in intents
    exp333 = intents["Exp333"]
    assert len(exp333.inputs) == 4
    phenol = next(c for c in exp333.inputs if "phenol" in c.name)
    assert phenol.amount_text == "1.6 mg"
    # Plate entries must not leak into inputs.
    names = {c.name for c in exp333.inputs}
    assert "Sample plate" not in names
