"""Doc-consistency tests for the staging gateway switch-over procedure (issue #926).

Asserts that DEPLOYMENT.md no longer tells operators to use `scripts/release_control.py`
or a control endpoint to rewrite the gateway `environment`, and that the correct
fresh-state-dir method and its pitfalls are documented.
"""

from pathlib import Path

DEPLOYMENT_MD = Path(__file__).parent.parent.parent / "DEPLOYMENT.md"


def _text() -> str:
    return DEPLOYMENT_MD.read_text(encoding="utf-8")


def test_deployment_md_exists():
    assert DEPLOYMENT_MD.exists(), "DEPLOYMENT.md must exist"


def test_step3_does_not_recommend_release_control_py_for_environment():
    """Step 3 of the staging switch-over must not tell operators to use
    release_control.py to update the gateway environment field — that does not work
    (the controller rejects a target whose environment differs from its own)."""
    text = _text()
    # Find the staging switch-over section
    section_start = text.find("### Operator switch-over procedure (staging only)")
    assert section_start != -1, "switch-over section not found"
    # Find the next top-level section marker after the switch-over section
    section_end = text.find("\n## ", section_start + 1)
    section_text = text[section_start:section_end] if section_end != -1 else text[section_start:]
    # The section must not instruct operators to use release_control.py to rewrite environment
    assert "release_control.py or the gateway control endpoint" not in section_text, (
        "Step 3 must not recommend 'release_control.py or the gateway control endpoint' "
        "to change the gateway environment — that approach does not work; "
        "use the fresh-state-dir method instead."
    )


def test_step3_recommends_gateway_state_dir():
    """Step 3 must describe the GATEWAY_STATE_DIR fresh-subdirectory approach."""
    text = _text()
    section_start = text.find("### Operator switch-over procedure (staging only)")
    assert section_start != -1, "switch-over section not found"
    section_end = text.find("\n## ", section_start + 1)
    section_text = text[section_start:section_end] if section_end != -1 else text[section_start:]
    assert "GATEWAY_STATE_DIR" in section_text, (
        "Step 3 must mention GATEWAY_STATE_DIR as the mechanism for seeding a fresh record"
    )


def test_step3_mentions_old_record_left_in_place():
    """Step 3 must clarify that the old record is left on disk and can be deleted later."""
    text = _text()
    section_start = text.find("### Operator switch-over procedure (staging only)")
    assert section_start != -1, "switch-over section not found"
    section_end = text.find("\n## ", section_start + 1)
    section_text = text[section_start:section_end] if section_end != -1 else text[section_start:]
    assert "left" in section_text and ("old" in section_text or "unused" in section_text), (
        "Step 3 must mention that the old record is left in place / unused"
    )


def test_pitfalls_volume_deletion_documented():
    """The pitfall about Railway volume deletion failure must be documented."""
    text = _text()
    assert "Detach the existing volume before adding another" in text or (
        "detach" in text.lower() and "volume" in text.lower() and "already" in text.lower()
    ), "The Railway 'already has a volume' error pitfall must be documented"


def test_pitfalls_no_volume_loses_record():
    """The pitfall about losing the policy record without a volume must be documented."""
    text = _text()
    assert "without a volume" in text.lower() or (
        "without" in text and "volume" in text and "paused" in text
    ), (
        "The pitfall about losing the policy record on every deploy"
        " without a volume must be documented"
    )


def test_pitfalls_unset_build_id_no_record():
    """The pitfall about GATEWAY_RELEASED_BUILD_ID being unset must be documented."""
    text = _text()
    assert "GATEWAY_RELEASED_BUILD_ID" in text
    # The pitfall paragraph must mention that no record is created when the var is unset
    assert "no policy record is" in text or "no record is created" in text or (
        "GATEWAY_RELEASED_BUILD_ID" in text and "unset" in text
    ), (
        "The pitfall about GATEWAY_RELEASED_BUILD_ID being unset"
        " creating no record must be documented"
    )


def test_railway_deployment_steps_mention_gateway_state_dir():
    """The Railway deployment steps must mention GATEWAY_STATE_DIR as an optional variable."""
    text = _text()
    railway_section = text.find("### Railway deployment steps")
    assert railway_section != -1, "Railway deployment steps section not found"
    # Find end of that subsection (next ### or ##)
    next_section = text.find("\n##", railway_section + 1)
    section_text = (
        text[railway_section:next_section]
        if next_section != -1
        else text[railway_section:]
    )
    assert "GATEWAY_STATE_DIR" in section_text, (
        "Railway deployment steps must mention GATEWAY_STATE_DIR as an optional variable"
    )
