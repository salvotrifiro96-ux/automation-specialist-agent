"""Costruzione di Workflow v4 (Flows) HubSpot.

Due flussi MVP che il media-automation team Leone vuole avere sempre attivi:

  A. **Workflow di assegnazione + conferma**
     trigger: form submission (form id passato in input)
     actions:
       - delay: 1 minuto (debounce + permette ai dati di stabilirsi)
       - set property `hubspot_owner_id` round-robin tra il pool advisor
       - send marketing email "conferma" (id passato in input)

  B. **Workflow di nurturing**
     trigger: contact created from a specific source (form submission)
     actions (sequenza):
       - delay: N giorni
       - send marketing email "nurturing day N"
       - delay: M giorni
       - send marketing email "nurturing day M+N"
       - ...

L'API workflow v4 e` parzialmente in beta. La struttura JSON e` complessa
ma documentata. Esponiamo due builder helper che producono il payload
per `POST /automation/v4/flows`.

Note critiche:
- HubSpot non offre nativamente "round-robin" come action atomica nel
  workflow v4 builder API. Per fare round-robin reale si usa l'azione
  "ROTATE_OWNERS" presente nei workflow templates. Qui usiamo una
  ROTATE_RECORD_TO_OWNER action che HubSpot supporta con un set di
  staffIds — esattamente quello che ci serve.
- Se la creation API restituisce 400/501 (alcuni feature flags non attivi
  sul portale), l'app mostrera` la spec JSON dello workflow per
  configurazione manuale.
"""
from __future__ import annotations

from typing import Any


# Operatori HubSpot supportati per i property filter del trigger.
# Allineati alla nomenclatura della API v4 (`operation.operator`).
PROPERTY_OPERATORS: tuple[tuple[str, str], ...] = (
    ("EQ",                "uguale a"),
    ("NEQ",               "diverso da"),
    ("CONTAINS_TOKEN",    "contiene la parola"),
    ("NOT_CONTAINS_TOKEN","non contiene la parola"),
    ("STARTED_WITH",      "inizia con"),
    ("IS_KNOWN",          "ha un valore qualsiasi"),
    ("IS_NOT_KNOWN",      "non ha valore"),
    ("GT",                "maggiore di"),
    ("LT",                "minore di"),
)

# Operatori che NON richiedono un value (sono booleani sulla property)
OPERATORS_WITHOUT_VALUE = frozenset({"IS_KNOWN", "IS_NOT_KNOWN"})


def _build_property_trigger(
    *,
    property_name: str,
    operator: str,
    value: str = "",
) -> dict[str, Any]:
    """Costruisce il trigger ENROLLMENT_CRITERIA con un filtro property singolo."""
    operation: dict[str, Any] = {"operator": operator}
    if operator not in OPERATORS_WITHOUT_VALUE and value:
        # HubSpot accetta `values` (lista) sui filtri property
        operation["values"] = [value]
    return {
        "type": "ENROLLMENT_CRITERIA",
        "filters": [
            [
                {
                    "filterType": "PROPERTY",
                    "property": property_name,
                    "operation": operation,
                }
            ]
        ],
    }


def build_assignment_v2_payload(
    *,
    name: str,
    trigger_property_name: str,
    trigger_operator: str,
    trigger_value: str,
    target_owner_id: str,
    confirmation_email_id: str | None = None,
    delay_minutes: int = 1,
    enabled: bool = False,
) -> dict[str, Any]:
    """Workflow v2: trigger = property condition, action = assegnazione a
    UN SOLO owner + invio email conferma opzionale.

    Args:
        trigger_property_name: nome della contact property (es. id_campagna_refresh)
        trigger_operator: uno di PROPERTY_OPERATORS (EQ, NEQ, CONTAINS_TOKEN, ...)
        trigger_value: valore di confronto (ignorato per IS_KNOWN/IS_NOT_KNOWN)
        target_owner_id: l'owner_id HubSpot a cui assegnare
        confirmation_email_id: email Marketing da inviare dopo l'assegnazione
        delay_minutes: pausa prima delle action (default 1 min per dare tempo
            ai dati di stabilizzarsi)
    """
    actions: list[dict[str, Any]] = []
    if delay_minutes > 0:
        actions.append({
            "type": "DELAY",
            "actionTypeVersion": 0,
            "fields": {"delta": delay_minutes * 60_000, "unit": "MILLISECONDS"},
        })
    actions.append({
        "type": "SET_PROPERTY",
        "actionTypeVersion": 0,
        "fields": {
            "propertyName": "hubspot_owner_id",
            "objectTypeId": "0-1",
            "value": str(target_owner_id),
        },
    })
    if confirmation_email_id:
        actions.append({
            "type": "SINGLE_CONNECTION",
            "actionTypeVersion": 0,
            "fields": {
                "appId": 113,
                "subAction": "SEND_MARKETING_EMAIL",
                "emailContentId": confirmation_email_id,
            },
        })

    return {
        "name": name,
        "type": "CONTACT_FLOW",
        "isEnabled": enabled,
        "objectTypeId": "0-1",
        "triggers": [
            _build_property_trigger(
                property_name=trigger_property_name,
                operator=trigger_operator,
                value=trigger_value,
            )
        ],
        "actions": actions,
    }


def build_assignment_workflow_payload(
    *,
    name: str,
    triggering_form_id: str,
    owner_ids_round_robin: list[str],
    confirmation_email_id: str | None = None,
    enabled: bool = False,
) -> dict[str, Any]:
    """Workflow A: form submission -> assegnazione round-robin + email conferma.

    Args:
        name: nome del flow in HubSpot
        triggering_form_id: l'id del form HubSpot che fa partire il workflow
        owner_ids_round_robin: lista di owner_id da ruotare in round-robin
        confirmation_email_id: id della Marketing Email di conferma da inviare
                                (puo` essere None se la confermi via UI)
        enabled: se False crea il workflow in stato "draft". Sempre False per
                 sicurezza — l'operatore lo abilita da HubSpot UI dopo
                 review.

    Returns:
        Payload pronto per POST /automation/v4/flows
    """
    actions: list[dict[str, Any]] = [
        {
            "type": "DELAY",
            "actionTypeVersion": 0,
            "fields": {"delta": 60_000, "unit": "MILLISECONDS"},
        },
        {
            "type": "ROTATE_RECORD_TO_OWNER",
            "actionTypeVersion": 0,
            "fields": {
                "ownerSource": "STATIC",
                "staffIds": owner_ids_round_robin,
                "propertyName": "hubspot_owner_id",
                "objectTypeId": "0-1",
            },
        },
    ]
    if confirmation_email_id:
        actions.append(
            {
                "type": "SINGLE_CONNECTION",
                "actionTypeVersion": 0,
                "fields": {
                    "appId": 113,  # HubSpot internal app id for marketing email
                    "subAction": "SEND_MARKETING_EMAIL",
                    "emailContentId": confirmation_email_id,
                },
            }
        )

    return {
        "name": name,
        "type": "CONTACT_FLOW",
        "isEnabled": enabled,
        "objectTypeId": "0-1",
        "triggers": [
            {
                "type": "FORM_SUBMITTED",
                "filters": [
                    {
                        "filterType": "PROPERTY",
                        "property": "form_id",
                        "operation": {"operator": "IS_ANY_OF", "values": [triggering_form_id]},
                    }
                ],
            }
        ],
        "actions": actions,
    }


def build_nurturing_workflow_payload(
    *,
    name: str,
    triggering_form_id: str,
    sequence: list[dict[str, Any]],
    enabled: bool = False,
) -> dict[str, Any]:
    """Workflow B: sequenza nurturing mail.

    Args:
        sequence: lista ordinata di step. Ogni step e` un dict:
            {"day": int, "email_id": "...", "delay_hours": int}
            `day` e` informativo (per il nome dello step), `delay_hours`
            e` l'attesa effettiva PRIMA di mandare l'email.
        enabled: come sopra, default False per safety.
    """
    actions: list[dict[str, Any]] = []
    for step in sequence:
        delay_hours = int(step.get("delay_hours", 24))
        email_id = step.get("email_id")
        if not email_id:
            continue
        if delay_hours > 0:
            actions.append(
                {
                    "type": "DELAY",
                    "actionTypeVersion": 0,
                    "fields": {
                        "delta": delay_hours * 60 * 60 * 1000,
                        "unit": "MILLISECONDS",
                    },
                }
            )
        actions.append(
            {
                "type": "SINGLE_CONNECTION",
                "actionTypeVersion": 0,
                "fields": {
                    "appId": 113,
                    "subAction": "SEND_MARKETING_EMAIL",
                    "emailContentId": email_id,
                },
            }
        )

    return {
        "name": name,
        "type": "CONTACT_FLOW",
        "isEnabled": enabled,
        "objectTypeId": "0-1",
        "triggers": [
            {
                "type": "FORM_SUBMITTED",
                "filters": [
                    {
                        "filterType": "PROPERTY",
                        "property": "form_id",
                        "operation": {"operator": "IS_ANY_OF", "values": [triggering_form_id]},
                    }
                ],
            }
        ],
        "actions": actions,
    }


def render_workflow_spec_md(payload: dict[str, Any]) -> str:
    """Render in markdown del workflow per configurazione manuale (fallback)."""
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
