from agent.workflows import (
    OPERATORS_WITHOUT_VALUE,
    PROPERTY_OPERATORS,
    build_assignment_v2_payload,
    build_assignment_workflow_payload,
    build_nurturing_workflow_payload,
    render_workflow_spec_md,
)


class TestAssignmentV2:
    def test_basic_with_value(self):
        p = build_assignment_v2_payload(
            name="X",
            trigger_property_name="id_campagna_refresh",
            trigger_operator="EQ",
            trigger_value="refresh_test",
            target_owner_id="owner-123",
        )
        t = p["triggers"][0]
        assert t["type"] == "ENROLLMENT_CRITERIA"
        f = t["filters"][0][0]
        assert f["property"] == "id_campagna_refresh"
        assert f["operation"]["operator"] == "EQ"
        assert f["operation"]["values"] == ["refresh_test"]

    def test_operator_without_value_omits_values_field(self):
        p = build_assignment_v2_payload(
            name="X",
            trigger_property_name="email",
            trigger_operator="IS_KNOWN",
            trigger_value="ignored",
            target_owner_id="o-1",
        )
        op = p["triggers"][0]["filters"][0][0]["operation"]
        assert op["operator"] == "IS_KNOWN"
        assert "values" not in op

    def test_owner_set_property_action(self):
        p = build_assignment_v2_payload(
            name="X",
            trigger_property_name="lifecyclestage",
            trigger_operator="EQ",
            trigger_value="marketingqualifiedlead",
            target_owner_id="owner-42",
        )
        set_actions = [a for a in p["actions"] if a["type"] == "SET_PROPERTY"]
        assert len(set_actions) == 1
        assert set_actions[0]["fields"]["propertyName"] == "hubspot_owner_id"
        assert set_actions[0]["fields"]["value"] == "owner-42"

    def test_delay_optional(self):
        p_no_delay = build_assignment_v2_payload(
            name="X",
            trigger_property_name="email",
            trigger_operator="IS_KNOWN",
            trigger_value="",
            target_owner_id="o-1",
            delay_minutes=0,
        )
        assert not any(a["type"] == "DELAY" for a in p_no_delay["actions"])

        p_with_delay = build_assignment_v2_payload(
            name="X",
            trigger_property_name="email",
            trigger_operator="IS_KNOWN",
            trigger_value="",
            target_owner_id="o-1",
            delay_minutes=5,
        )
        delays = [a for a in p_with_delay["actions"] if a["type"] == "DELAY"]
        assert len(delays) == 1
        assert delays[0]["fields"]["delta"] == 5 * 60_000

    def test_confirmation_email_appended_last(self):
        p = build_assignment_v2_payload(
            name="X",
            trigger_property_name="email",
            trigger_operator="IS_KNOWN",
            trigger_value="",
            target_owner_id="o-1",
            confirmation_email_id="email-99",
        )
        last = p["actions"][-1]
        assert last["type"] == "SINGLE_CONNECTION"
        assert last["fields"]["emailContentId"] == "email-99"


class TestPropertyOperatorsConstants:
    def test_operators_list_nonempty(self):
        assert len(PROPERTY_OPERATORS) > 0

    def test_operators_without_value_subset(self):
        codes = {c for c, _ in PROPERTY_OPERATORS}
        assert OPERATORS_WITHOUT_VALUE.issubset(codes)


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
