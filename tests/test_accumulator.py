"""Tests for the AnalysisAccumulator service."""

from app.services.accumulator import AnalysisAccumulator


def test_accumulator_mood():
    """Accumulator should detect <mood> tags."""
    acc = AnalysisAccumulator()
    events = acc.ingest("The mood is <mood>melancholic</mood> here.")
    assert len(events) == 1
    assert events[0]["type"] == "mood"
    assert events[0]["value"] == "melancholic"


def test_accumulator_theme():
    """Accumulator should detect <theme> tags."""
    acc = AnalysisAccumulator()
    events = acc.ingest("<theme>loss</theme> and <theme>water</theme>")
    assert len(events) == 2
    assert events[0]["value"] == "loss"
    assert events[1]["value"] == "water"


def test_accumulator_symbol():
    """Accumulator should detect <symbol> tags with name attribute."""
    acc = AnalysisAccumulator()
    events = acc.ingest('<symbol name="bridge">a threshold</symbol>')
    assert len(events) == 1
    assert events[0]["type"] == "symbol"
    assert events[0]["name"] == "bridge"
    assert events[0]["meaning"] == "a threshold"


def test_accumulator_fragment():
    """Accumulator should detect <fragment> tags with label attribute."""
    acc = AnalysisAccumulator()
    events = acc.ingest('<fragment label="Interpretation">Deep meaning here</fragment>')
    assert len(events) == 1
    assert events[0]["type"] == "fragment"
    assert events[0]["label"] == "Interpretation"
    assert events[0]["content"] == "Deep meaning here"


def test_accumulator_title():
    """Accumulator should detect <title> tags."""
    acc = AnalysisAccumulator()
    events = acc.ingest("The <title>The Bridge</title> is revealed.")
    assert len(events) == 1
    assert events[0]["type"] == "title"
    assert events[0]["value"] == "The Bridge"


def test_accumulator_no_duplicates():
    """Accumulator should not emit the same event twice."""
    acc = AnalysisAccumulator()
    events1 = acc.ingest("<mood>serene</mood>")
    events2 = acc.ingest("<mood>serene</mood>")
    assert len(events1) == 1
    assert len(events2) == 0


def test_accumulator_build_analysis():
    """build_analysis() should compile all events into a DreamAnalysis object."""
    acc = AnalysisAccumulator()
    acc.ingest("<mood>luminous</mood>")
    acc.ingest("<theme>transformation</theme>")
    acc.ingest('<symbol name="butterfly">metamorphosis</symbol>')
    acc.ingest('<fragment label="Core">The dream reveals a shift</fragment>')
    acc.ingest("<title>The Chrysalis</title>")

    analysis = acc.build_analysis()
    assert analysis["emotionalTone"] == "luminous"
    assert "transformation" in analysis["themes"]
    assert len(analysis["symbols"]) == 1
    assert analysis["symbols"][0]["name"] == "butterfly"
    assert len(analysis["fragments"]) == 1
    assert analysis["fragments"][0]["label"] == "Core"
    assert analysis["summary"] != ""
