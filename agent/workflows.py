"""Workflow v4 (Flows) HubSpot — un solo builder unificato per il funnel Leone.

Scope: un workflow per campagna che gestisce TUTTO il post-iscrizione:

    trigger:  FORM_SUBMITTED sul form dello step 1
    actions (in ordine):
      1. (opzionale) DELAY breve prima della conferma (default 1min)
      2. (opzionale) SINGLE_CONNECTION send marketing email "conferma"
      3. per ogni step di nurturing in sequenza:
         - DELAY (delay_hours convertito in ms)
         - SINGLE_CONNECTION send marketing email dello step

Il workflow viene sempre creato `isEnabled=False` per safety: l'operatore
lo rivede in HubSpot UI e lo attiva manualmente.

Se la v4 Flows API rifiuta la creazione (alcune feature flag non sono
attive su tutti i portal), l'app espone `render_workflow_spec_md(payload)`
per produrre una spec leggibile da ricreare manualmente in UI.
"""
from __future__ import annotations

from typing import Any


# appId interno HubSpot per la send-marketing-email action.
_MARKETING_APP_ID = 113


def _delay_action(delta_ms: int) -> dict[str, Any]:
    return {
        "type": "DELAY",
        "actionTypeVersion": 0,
        "fields": {"delta": delta_ms, "unit": "MILLISECONDS"},
    }


def _send_email_action(email_id: str) -> dict[str, Any]:
    return {
        "type": "SINGLE_CONNECTION",
        "actionTypeVersion": 0,
        "fields": {
            "appId": _MARKETING_APP_ID,
            "subAction": "SEND_MARKETING_EMAIL",
            "emailContentId": email_id,
        },
    }


def _form_trigger(form_id: str) -> dict[str, Any]:
    return {
        "type": "FORM_SUBMITTED",
        "filters": [
            {
                "filterType": "PROPERTY",
                "property": "form_id",
                "operation": {"operator": "IS_ANY_OF", "values": [form_id]},
            }
        ],
    }


def build_funnel_workflow_payload(
    *,
    name: str,
    triggering_form_id: str,
    confirmation_email_id: str | None = None,
    confirmation_delay_minutes: int = 1,
    nurturing_sequence: list[dict[str, Any]] | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    """Costruisce il payload del workflow unico Leone (form -> conferma -> nurturing).

    Args:
        name: nome del flow in HubSpot
        triggering_form_id: id del form HubSpot che fa partire il workflow
        confirmation_email_id: id Marketing Email da inviare come conferma.
            Se None, la conferma viene saltata (raro, ma supportato).
        confirmation_delay_minutes: pausa prima della conferma. Default 1min
            per dare ai dati il tempo di stabilizzarsi su HubSpot.
        nurturing_sequence: lista ordinata di step. Ogni step e` un dict:
            ``{"day": int, "email_id": "...", "delay_hours": int}``.
            `day` e` informativo (lo usiamo nel nome). `delay_hours` e`
            l'attesa PRIMA di mandare l'email (rispetto allo step precedente).
            Step senza `email_id` vengono saltati.
        enabled: stato iniziale del workflow. Default False — sempre.

    Returns:
        Payload pronto per ``POST /automation/v4/flows``.
    """
    actions: list[dict[str, Any]] = []

    if confirmation_email_id:
        if confirmation_delay_minutes > 0:
            actions.append(_delay_action(confirmation_delay_minutes * 60_000))
        actions.append(_send_email_action(confirmation_email_id))

    for step in (nurturing_sequence or []):
        email_id = step.get("email_id")
        if not email_id:
            continue
        delay_hours = int(step.get("delay_hours", 24))
        if delay_hours > 0:
            actions.append(_delay_action(delay_hours * 60 * 60 * 1000))
        actions.append(_send_email_action(email_id))

    return {
        "name": name,
        "type": "CONTACT_FLOW",
        "isEnabled": enabled,
        "objectTypeId": "0-1",
        "triggers": [_form_trigger(triggering_form_id)],
        "actions": actions,
    }


def render_workflow_spec_md(payload: dict[str, Any]) -> str:
    """Render markdown del workflow per ricreazione manuale in HubSpot UI."""
    lines = [f"# Workflow: {payload.get('name', '?')}", ""]
    lines.append(f"**Tipo**: {payload.get('type')}  ")
    lines.append(f"**Object**: {payload.get('objectTypeId')}  ")
    lines.append(f"**Enabled**: {payload.get('isEnabled')}  ")
    lines.append("")
    lines.append("## Trigger")
    for t in payload.get("triggers", []):
        lines.append(f"- type={t.get('type')}, filters={t.get('filters')}")
    lines.append("")
    lines.append("## Actions (ordine)")
    for i, a in enumerate(payload.get("actions", []), 1):
        f = a.get("fields", {})
        lines.append(f"{i}. **{a.get('type')}** — fields: `{f}`")
    return "\n".join(lines)
