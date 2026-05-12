from agent.workflows import (
    build_assignment_workflow_payload,
    build_nurturing_workflow_payload,
    render_workflow_spec_md,
)


class TestAssignmentWorkflow:
    def test_basic_structure(self):
        p = build_assignment_workflow_payload(
            name="Test A",
            triggering_form_id="form-123",
            owner_ids_round_robin=["1", "2", "3"],
        )
        assert p["name"] == "Test A"
        assert p["objectTypeId"] == "0-1"
        assert p["isEnabled"] is False  # safety default
        assert len(p["triggers"]) == 1
        assert p["triggers"][0]["type"] == "FORM_SUBMITTED"

    def test_no_confirmation_email(self):
        p = build_assignment_workflow_payload(
            name="Test", triggering_form_id="f", owner_ids_round_robin=["1"],
        )
        # actions = [delay, rotate]  — niente send_email
        assert len(p["actions"]) == 2
        assert p["actions"][1]["type"] == "ROTATE_RECORD_TO_OWNER"

    def test_with_confirmation_email(self):
        p = build_assignment_workflow_payload(
            name="Test",
            triggering_form_id="f",
            owner_ids_round_robin=["1"],
            confirmation_email_id="email-42",
        )
        assert len(p["actions"]) == 3
        assert p["actions"][2]["type"] == "SINGLE_CONNECTION"
        assert p["actions"][2]["fields"]["emailContentId"] == "email-42"

    def test_owner_ids_passed_to_rotate(self):
        ids = ["100", "200", "300"]
        p = build_assignment_workflow_payload(
            name="X", triggering_form_id="f", owner_ids_round_robin=ids,
        )
        rotate = p["actions"][1]
        assert rotate["fields"]["staffIds"] == ids


class TestNurturingWorkflow:
    def test_skips_steps_without_email(self):
        sequence = [
            {"day": 1, "email_id": "e1", "delay_hours": 24},
            {"day": 2, "email_id": "", "delay_hours": 24},  # skipped
            {"day": 3, "email_id": "e3", "delay_hours": 48},
        ]
        p = build_nurturing_workflow_payload(
            name="Nurt", triggering_form_id="f", sequence=sequence,
        )
        # 2 step validi × (delay + email) = 4 actions
        assert len(p["actions"]) == 4

    def test_zero_delay_no_delay_action(self):
        sequence = [{"day": 1, "email_id": "e1", "delay_hours": 0}]
        p = build_nurturing_workflow_payload(
            name="N", triggering_form_id="f", sequence=sequence,
        )
        assert len(p["actions"]) == 1  # solo l'email send
        assert p["actions"][0]["type"] == "SINGLE_CONNECTION"

    def test_delay_converted_to_ms(self):
        sequence = [{"day": 1, "email_id": "e1", "delay_hours": 2}]
        p = build_nurturing_workflow_payload(
            name="N", triggering_form_id="f", sequence=sequence,
        )
        delay_action = p["actions"][0]
        assert delay_action["type"] == "DELAY"
        # 2h = 7_200_000 ms
        assert delay_action["fields"]["delta"] == 2 * 60 * 60 * 1000


def test_spec_md_contains_actions():
    p = build_assignment_workflow_payload(
        name="Test", triggering_form_id="f", owner_ids_round_robin=["1", "2"],
    )
    md = render_workflow_spec_md(p)
    assert "# Workflow: Test" in md
    assert "ROTATE_RECORD_TO_OWNER" in md
    assert "DELAY" in md
