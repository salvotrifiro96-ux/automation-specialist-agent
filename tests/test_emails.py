from agent.emails import (
    EmailDraft,
    _extract_drafts_from_payload,
    _html_from_text,
    _swap_placeholders,
    build_email_payload,
)


class TestSwapPlaceholders:
    def test_replaces_nome(self):
        out = _swap_placeholders("Ciao [Nome], ecco il tuo PDF")
        assert "{{ contact.firstname }}" in out
        assert "[Nome]" not in out

    def test_keeps_link_literal(self):
        out = _swap_placeholders("Apri [LINK]")
        assert "[LINK]" in out

    def test_email_token(self):
        out = _swap_placeholders("Conferma su [Email]")
        assert "{{ contact.email }}" in out


class TestExtractDrafts:
    def test_confirmation_variants(self):
        payload = {
            "variants": [
                {"subject": "Sub 1", "preview": "P1", "body": "Body 1", "signature": "Sig 1", "tone": "amichevole"},
                {"subject": "Sub 2", "preview": "P2", "body": "Body 2"},
            ]
        }
        drafts = _extract_drafts_from_payload(
            subtype="confirmation_mail", title="Test", payload=payload,
        )
        assert len(drafts) == 2
        assert drafts[0].subject == "Sub 1"
        assert drafts[0].signature == "Sig 1"
        assert drafts[1].signature == ""

    def test_nurturing_sequence(self):
        payload = {
            "mails": [
                {"day": 1, "role": "bonding", "subject": "S1", "body": "B1"},
                {"day": 3, "role": "proof",   "subject": "S2", "body": "B2"},
            ]
        }
        drafts = _extract_drafts_from_payload(
            subtype="nurturing_sequence", title="Seq Test", payload=payload,
        )
        assert len(drafts) == 2
        assert "day1" in drafts[0].name
        assert "bonding" in drafts[0].name

    def test_skip_empty_body(self):
        payload = {"variants": [{"subject": "x", "body": ""}]}
        drafts = _extract_drafts_from_payload(
            subtype="confirmation_mail", title="X", payload=payload,
        )
        assert drafts == []

    def test_unknown_subtype(self):
        drafts = _extract_drafts_from_payload(
            subtype="something_else", title="X", payload={"variants": [{"subject": "s", "body": "b"}]},
        )
        assert drafts == []


class TestHtmlFromText:
    def test_paragraph_split(self):
        html = _html_from_text("Riga 1\n\nRiga 2", "")
        assert "<p>Riga 1</p>" in html
        assert "<p>Riga 2</p>" in html

    def test_newline_becomes_br(self):
        html = _html_from_text("R1\nR2", "")
        assert "R1<br/>R2" in html

    def test_appends_signature(self):
        html = _html_from_text("Body", "Salvo\nLMS")
        assert "Salvo" in html and "<br/>LMS" in html


class TestBuildEmailPayload:
    def _draft(self) -> EmailDraft:
        return EmailDraft(
            name="X",
            subject="S",
            preview="P",
            body_text="Hello\nWorld",
            signature="Sig",
        )

    def test_basic(self):
        p = build_email_payload(
            draft=self._draft(),
            from_name="Salvo",
            from_email="salvo@x.it",
        )
        assert p["name"] == "X"
        assert p["subject"] == "S"
        assert p["from"]["fromName"] == "Salvo"
        assert p["from"]["fromEmail"] == "salvo@x.it"
        assert p["state"] == "DRAFT"
        assert "Hello" in p["content"]["widgets"]["email_body"]["body"]["html"]

    def test_reply_to_optional(self):
        p = build_email_payload(
            draft=self._draft(),
            from_name="N",
            from_email="e@x.it",
            reply_to="reply@x.it",
        )
        assert p["from"]["replyTo"] == "reply@x.it"
