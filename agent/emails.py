"""Marketing Email HubSpot da output del copywriter.

Pipeline:
  1. Legge da `agent_outputs` su Supabase i subtype `confirmation_mail` e
     `nurturing_sequence` / `nurturing_single`
  2. Per ogni mail (= variante o singolo elemento della sequenza) costruisce
     il payload HubSpot Marketing Email v3
  3. Sostituisce i placeholder del copywriter con i token HubSpot:
        [Nome]  -> {{ contact.firstname }}
        [LINK]  -> mantenuto come placeholder, l'operatore lo sostituira` con
                   il link reale in HubSpot UI prima di pubblicare

Le email vengono create in stato DRAFT. L'operatore le rivede in HubSpot,
imposta sender/from, e le pubblica.

Note di scope:
  - HubSpot Marketing Email API v3 e` parzialmente in beta. La creazione
    funziona ma alcuni campi (es. business_unit_id, custom HTML) richiedono
    permessi extra. Qui usiamo `dragAndDrop` con `simple_richtext` content,
    cosi` l'operatore le edita facilmente in UI.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agent.hubspot_api import HubSpotClient
from agent.store import SupabaseStore


# Mapping dei placeholder copywriter -> token HubSpot.
_PLACEHOLDER_MAP: tuple[tuple[str, str], ...] = (
    ("[Nome]", "{{ contact.firstname }}"),
    ("[Cognome]", "{{ contact.lastname }}"),
    ("[Email]", "{{ contact.email }}"),
    # [LINK] non viene tradotto: lasciato letterale come reminder
    # all'operatore di sostituirlo in HubSpot UI col link reale.
)


@dataclass(frozen=True)
class EmailDraft:
    """Una mail pronta per essere creata in HubSpot."""

    name: str          # nome interno HubSpot
    subject: str
    preview: str
    body_text: str     # con merge tag HubSpot
    signature: str


@dataclass(frozen=True)
class ImportPlan:
    """Cosa importare in HubSpot da un singolo output del copywriter."""

    output_id: str
    output_title: str
    subtype: str
    drafts: tuple[EmailDraft, ...]


def _swap_placeholders(text: str) -> str:
    out = text
    for src, dst in _PLACEHOLDER_MAP:
        out = out.replace(src, dst)
    return out


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s_-]+", "", text)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:max_len] or "untitled"


def _extract_drafts_from_payload(
    *,
    subtype: str,
    title: str,
    payload: dict[str, Any],
) -> list[EmailDraft]:
    """Costruisce gli `EmailDraft` partendo dal payload jsonb del copywriter."""
    items: list[dict[str, Any]] = []
    if subtype == "confirmation_mail":
        items = payload.get("variants") or []
    elif subtype in ("nurturing_sequence", "nurturing_single"):
        items = payload.get("mails") or []
    else:
        return []

    out: list[EmailDraft] = []
    for idx, m in enumerate(items, 1):
        subject = (m.get("subject") or "").strip()
        body = (m.get("body") or "").strip()
        if not subject or not body:
            continue
        name_parts = [_slug(title), f"v{idx}"]
        if "day" in m:
            name_parts.append(f"day{m['day']}")
        if m.get("role"):
            name_parts.append(_slug(m["role"], 30))
        out.append(
            EmailDraft(
                name=" — ".join(p for p in name_parts if p),
                subject=_swap_placeholders(subject),
                preview=_swap_placeholders(m.get("preview", "") or ""),
                body_text=_swap_placeholders(body),
                signature=_swap_placeholders(m.get("signature", "") or ""),
            )
        )
    return out


def list_importable_outputs(store: SupabaseStore, limit: int = 50) -> list[ImportPlan]:
    """Lista degli output copywriter convertibili in marketing email."""
    plans: list[ImportPlan] = []
    for subtype in ("confirmation_mail", "nurturing_sequence", "nurturing_single"):
        rows = store.list_recent_outputs(
            agent_type="copywriter", subtype=subtype, limit=limit
        )
        for row in rows:
            drafts = _extract_drafts_from_payload(
                subtype=row.get("subtype", ""),
                title=row.get("title", ""),
                payload=row.get("payload") or {},
            )
            if not drafts:
                continue
            plans.append(
                ImportPlan(
                    output_id=str(row["id"]),
                    output_title=str(row.get("title", "")),
                    subtype=str(row.get("subtype", "")),
                    drafts=tuple(drafts),
                )
            )
    # Ordino per recency mescolato — semplice: prendiamo prima i nurturing
    # (piu` strategici) poi le conferma.
    return plans


# ── Build payload HubSpot Marketing Email v3 ───────────────────────


def _html_from_text(body_text: str, signature: str) -> str:
    """Converte plain text + signature in HTML semplice (paragrafi + br).

    HubSpot Marketing Email accetta HTML in `content.modules.email_body`
    quando il template e` `drag_and_drop`. Tenermo il design minimale
    cosi` l'operatore edita facilmente.
    """
    def _para(block: str) -> str:
        return "<p>" + block.replace("\n", "<br/>") + "</p>"

    paragraphs = [p.strip() for p in body_text.split("\n\n") if p.strip()]
    html = "\n".join(_para(p) for p in paragraphs)
    if signature.strip():
        html += "\n" + _para(signature)
    return html


def build_email_payload(
    *,
    draft: EmailDraft,
    from_name: str,
    from_email: str,
    reply_to: str | None = None,
    subscription_id: int | None = None,
) -> dict[str, Any]:
    """Costruisce il payload per POST /marketing/v3/emails/.

    `subscription_id` (Subscription type) e` opzionale ma fortemente
    consigliato per la conformita` GDPR HubSpot. Se non passato, HubSpot
    usera` il default subscription type "Marketing Information".
    """
    html_body = _html_from_text(draft.body_text, draft.signature)
    payload: dict[str, Any] = {
        "name": draft.name,
        "type": "AB_EMAIL" if False else "BATCH_EMAIL",
        "subject": draft.subject,
        "language": "it",
        "from": {
            "fromName": from_name,
            "replyTo": reply_to or from_email,
        },
        "subscriptionDetails": {
            **({"subscriptionId": subscription_id} if subscription_id else {}),
            "officeLocationId": None,
        },
        "content": {
            "previewText": draft.preview,
            "templatePath": "@hubspot/email_drag_drop/templates/drag_drop_email.html",
            # widgets: HubSpot UI auto-populates module structure for
            # drag-and-drop templates. Per creation via API, basta passare
            # un singolo body module con il nostro HTML.
            "widgets": {
                "email_body": {
                    "body": {
                        "module_id": 1155639,  # default email_body module
                        "html": html_body,
                    }
                }
            },
        },
        "state": "DRAFT",
    }
    # Ripuliamo `from.fromEmail` solo se passato — HubSpot lo accetta solo
    # se l'indirizzo e` verificato. Meglio lasciarlo settato dall'operatore.
    if from_email:
        payload["from"]["fromEmail"] = from_email
    return payload


def create_drafts(
    *,
    client: HubSpotClient,
    drafts: list[EmailDraft],
    from_name: str,
    from_email: str,
    reply_to: str | None = None,
) -> list[dict[str, Any]]:
    """Crea N draft email su HubSpot. Ritorna le risposte API (con id)."""
    out: list[dict[str, Any]] = []
    for draft in drafts:
        payload = build_email_payload(
            draft=draft,
            from_name=from_name,
            from_email=from_email,
            reply_to=reply_to,
        )
        res = client.create_marketing_email(payload)
        out.append(res)
    return out
