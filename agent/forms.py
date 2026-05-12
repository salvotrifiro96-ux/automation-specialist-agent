"""Costruzione del payload form HubSpot v3.

Il form di acquisizione del team Leone ha SEMPRE:
  - email (obbligatorio)
  - firstname / lastname (opzionali ma consigliati)
  - phone (opzionale)
  - id_campagna_refresh come HIDDEN field, valorizzato dal media-buyer
    con l'identificatore di campagna che ha lanciato la creative

Il payload e` un native HubSpot Form (`formType=hubspot`) — quello che si crea
da UI in Marketing -> Forms. Cosi` il form si puo` embeddare ovunque e
HubSpot raccoglie le submission nelle list/workflow standard.
"""
from __future__ import annotations

from typing import Any

from agent.properties import REFRESH_PROPERTY_NAME


def _field_group(field_payload: dict[str, Any]) -> dict[str, Any]:
    """Wrappa un field in un fieldGroup (la struttura nested di HubSpot v3)."""
    return {"groupType": "default_group", "richTextType": "text", "fields": [field_payload]}


def _contact_field(
    *,
    name: str,
    label: str,
    field_type: str = "single_line_text",
    required: bool = False,
    placeholder: str = "",
    hidden: bool = False,
    default_value: str = "",
) -> dict[str, Any]:
    """Costruisce un singolo field per il form."""
    field: dict[str, Any] = {
        "objectTypeId": "0-1",  # Contacts
        "name": name,
        "label": label,
        "required": required,
        "hidden": hidden,
        "fieldType": field_type,
    }
    if placeholder:
        field["placeholder"] = placeholder
    if default_value:
        field["defaultValue"] = default_value
    return field


def build_form_payload(
    *,
    name: str,
    submit_button_label: str = "Invia",
    success_message: str = "Grazie, ti contatteremo presto.",
    redirect_url: str = "",
    include_phone: bool = True,
    include_lastname: bool = True,
    default_campaign_id: str = "",
    consent_text: str = "Acconsento al trattamento dei miei dati personali secondo l'informativa privacy.",
    legal_basis: str = "LEGITIMATE_INTEREST_PQL",
) -> dict[str, Any]:
    """Costruisce il payload per POST /marketing/v3/forms.

    Args:
        name: nome interno del form in HubSpot
        submit_button_label: testo del bottone submit
        success_message: messaggio mostrato dopo invio (se redirect_url vuoto)
        redirect_url: URL di redirect dopo submit (alternativo al success_message)
        include_phone: se True aggiunge campo telefono opzionale
        include_lastname: se True aggiunge campo cognome opzionale
        default_campaign_id: valore default per id_campagna_refresh (hidden field).
            Lasciato vuoto se l'embedder lo passera` via JS al runtime.
        consent_text: testo del consenso GDPR
        legal_basis: base giuridica HubSpot
    """
    field_groups: list[dict[str, Any]] = []

    # Email — sempre primo, sempre required
    field_groups.append(_field_group(_contact_field(
        name="email",
        label="Email",
        field_type="email",
        required=True,
        placeholder="tua@email.it",
    )))

    field_groups.append(_field_group(_contact_field(
        name="firstname",
        label="Nome",
        required=False,
        placeholder="Mario",
    )))

    if include_lastname:
        field_groups.append(_field_group(_contact_field(
            name="lastname",
            label="Cognome",
            required=False,
            placeholder="Rossi",
        )))

    if include_phone:
        field_groups.append(_field_group(_contact_field(
            name="phone",
            label="Telefono",
            field_type="phone",
            required=False,
            placeholder="+39 ...",
        )))

    # Hidden campaign id — il link tra Meta ad e contatto HubSpot
    field_groups.append(_field_group(_contact_field(
        name=REFRESH_PROPERTY_NAME,
        label="Campaign ID",
        required=False,
        hidden=True,
        default_value=default_campaign_id,
    )))

    payload: dict[str, Any] = {
        "name": name,
        "formType": "hubspot",
        "archived": False,
        "fieldGroups": field_groups,
        "configuration": {
            "language": "it",
            "cloneable": True,
            "postSubmitAction": (
                {"type": "redirect_url", "value": redirect_url}
                if redirect_url
                else {"type": "thank_you", "value": success_message}
            ),
            "editable": True,
            "archivable": True,
            "recaptchaEnabled": False,
            "notifyContactOwner": False,
            "notifyRecipients": [],
            "createNewContactForNewEmail": False,
            "prePopulateKnownValues": True,
            "allowLinkToResetKnownValues": False,
            "lifecycleStages": [],
        },
        "displayOptions": {
            "renderRawHtml": False,
            "theme": "default_style",
            "submitButtonText": submit_button_label,
            "style": {
                "fontFamily": "arial, helvetica, sans-serif",
                "backgroundWidth": "100%",
                "labelTextColor": "#33475b",
                "labelTextSize": "13px",
                "helpTextColor": "#7C98B6",
                "helpTextSize": "11px",
                "legalConsentTextColor": "#33475b",
                "legalConsentTextSize": "14px",
            },
        },
        "legalConsentOptions": {
            "type": "legitimate_interest",
            "communicationConsentText": consent_text,
            "subscriptionTypeIds": [],
            "lawfulBasis": legal_basis,
        },
    }
    return payload
