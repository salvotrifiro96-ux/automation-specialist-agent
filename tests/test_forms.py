from agent.forms import build_form_payload
from agent.properties import REFRESH_PROPERTY_NAME


def test_basic_form_structure():
    payload = build_form_payload(name="LP Test")
    assert payload["name"] == "LP Test"
    assert payload["formType"] == "hubspot"
    assert payload["configuration"]["language"] == "it"
    assert isinstance(payload["fieldGroups"], list)
    assert len(payload["fieldGroups"]) >= 2  # email + firstname minimum


def test_email_field_always_required():
    payload = build_form_payload(name="X")
    email_groups = [
        g for g in payload["fieldGroups"]
        for f in g["fields"]
        if f["name"] == "email"
    ]
    assert email_groups, "email field deve esistere"
    assert email_groups[0]["fields"][0]["required"] is True


def test_hidden_campaign_id_field_present():
    payload = build_form_payload(name="X", default_campaign_id="refresh_test_42")
    fields = [f for g in payload["fieldGroups"] for f in g["fields"]]
    refresh = [f for f in fields if f["name"] == REFRESH_PROPERTY_NAME]
    assert refresh, f"campo {REFRESH_PROPERTY_NAME} deve esistere"
    assert refresh[0]["hidden"] is True
    assert refresh[0]["defaultValue"] == "refresh_test_42"


def test_redirect_takes_precedence():
    payload = build_form_payload(
        name="X",
        success_message="msg",
        redirect_url="https://example.com/thanks",
    )
    psa = payload["configuration"]["postSubmitAction"]
    assert psa["type"] == "redirect_url"
    assert psa["value"] == "https://example.com/thanks"


def test_thank_you_when_no_redirect():
    payload = build_form_payload(
        name="X",
        success_message="grazie!",
        redirect_url="",
    )
    psa = payload["configuration"]["postSubmitAction"]
    assert psa["type"] == "thank_you"
    assert psa["value"] == "grazie!"


def test_omit_phone_and_lastname():
    payload = build_form_payload(
        name="X",
        include_phone=False,
        include_lastname=False,
    )
    names = [f["name"] for g in payload["fieldGroups"] for f in g["fields"]]
    assert "phone" not in names
    assert "lastname" not in names
    assert "firstname" in names  # ma firstname resta
    assert "email" in names
