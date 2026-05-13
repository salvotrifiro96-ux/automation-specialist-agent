from agent.workflows import (
    build_funnel_workflow_payload,
    render_workflow_spec_md,
)


class TestFunnelWorkflowStructure:
    def test_basic_structure(self):
        p = build_funnel_workflow_payload(
            name="Test",
            triggering_form_id="form-123",
            confirmation_email_id="email-1",
        )
        assert p["name"] == "Test"
        assert p["type"] == "CONTACT_FLOW"
        assert p["objectTypeId"] == "0-1"
        assert p["isEnabled"] is False  # safety default

    def test_trigger_is_form_submission(self):
        p = build_funnel_workflow_payload(
            name="X",
            triggering_form_id="form-XYZ",
            confirmation_email_id="email-1",
        )
        assert len(p["triggers"]) == 1
        trig = p["triggers"][0]
        assert trig["type"] == "FORM_SUBMITTED"
        assert trig["filters"][0]["property"] == "form_id"
        assert trig["filters"][0]["operation"]["values"] == ["form-XYZ"]


class TestConfirmationOnly:
    def test_default_delay_then_email(self):
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id="email-conf",
        )
        # actions = [delay 1min, send conferma]
        assert len(p["actions"]) == 2
        assert p["actions"][0]["type"] == "DELAY"
        assert p["actions"][0]["fields"]["delta"] == 60_000
        assert p["actions"][1]["type"] == "SINGLE_CONNECTION"
        assert p["actions"][1]["fields"]["emailContentId"] == "email-conf"

    def test_zero_delay_skips_delay_action(self):
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id="email-conf",
            confirmation_delay_minutes=0,
        )
        assert len(p["actions"]) == 1
        assert p["actions"][0]["type"] == "SINGLE_CONNECTION"

    def test_no_confirmation_email_no_actions(self):
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id=None,
        )
        assert p["actions"] == []


class TestNurturingSequence:
    def test_nurturing_appended_after_confirmation(self):
        seq = [
            {"day": 1, "email_id": "e1", "delay_hours": 24},
            {"day": 2, "email_id": "e2", "delay_hours": 48},
        ]
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id="conf",
            nurturing_sequence=seq,
        )
        # [delay 1m, send conf, delay 24h, send e1, delay 48h, send e2] = 6
        assert len(p["actions"]) == 6
        types = [a["type"] for a in p["actions"]]
        assert types == [
            "DELAY", "SINGLE_CONNECTION",
            "DELAY", "SINGLE_CONNECTION",
            "DELAY", "SINGLE_CONNECTION",
        ]
        # Verifica che la sequenza sia in ordine
        send_ids = [a["fields"]["emailContentId"] for a in p["actions"] if a["type"] == "SINGLE_CONNECTION"]
        assert send_ids == ["conf", "e1", "e2"]

    def test_zero_delay_in_step_omits_delay(self):
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id=None,
            nurturing_sequence=[{"day": 1, "email_id": "e1", "delay_hours": 0}],
        )
        assert len(p["actions"]) == 1
        assert p["actions"][0]["type"] == "SINGLE_CONNECTION"

    def test_skips_steps_without_email_id(self):
        seq = [
            {"day": 1, "email_id": "e1", "delay_hours": 24},
            {"day": 2, "email_id": "", "delay_hours": 24},  # saltato
            {"day": 3, "email_id": None, "delay_hours": 24},  # saltato
            {"day": 4, "email_id": "e4", "delay_hours": 48},
        ]
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id=None,
            nurturing_sequence=seq,
        )
        # 2 step validi × (delay + send) = 4 actions
        assert len(p["actions"]) == 4
        send_ids = [a["fields"]["emailContentId"] for a in p["actions"] if a["type"] == "SINGLE_CONNECTION"]
        assert send_ids == ["e1", "e4"]

    def test_delay_hours_converted_to_ms(self):
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id=None,
            nurturing_sequence=[{"day": 1, "email_id": "e1", "delay_hours": 2}],
        )
        delay = p["actions"][0]
        assert delay["type"] == "DELAY"
        assert delay["fields"]["delta"] == 2 * 60 * 60 * 1000

    def test_marketing_app_id_in_send_action(self):
        p = build_funnel_workflow_payload(
            name="N",
            triggering_form_id="f",
            confirmation_email_id="conf",
        )
        send = p["actions"][-1]
        assert send["fields"]["appId"] == 113
        assert send["fields"]["subAction"] == "SEND_MARKETING_EMAIL"


class TestEnabled:
    def test_default_disabled(self):
        p = build_funnel_workflow_payload(
            name="X", triggering_form_id="f", confirmation_email_id="c",
        )
        assert p["isEnabled"] is False

    def test_explicit_enabled(self):
        p = build_funnel_workflow_payload(
            name="X", triggering_form_id="f", confirmation_email_id="c",
            enabled=True,
        )
        assert p["isEnabled"] is True


def test_spec_md_contains_actions():
    p = build_funnel_workflow_payload(
        name="Test", triggering_form_id="f", confirmation_email_id="c",
        nurturing_sequence=[{"day": 1, "email_id": "e1", "delay_hours": 24}],
    )
    md = render_workflow_spec_md(p)
    assert "# Workflow: Test" in md
    assert "SINGLE_CONNECTION" in md
    assert "DELAY" in md
