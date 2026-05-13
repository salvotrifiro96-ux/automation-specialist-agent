"""HubSpot Graph API wrapper per l'Automation Specialist Agent.

Espone solo cio` che serve al wizard a 4 step:
  - properties:  find / create custom contact field (`id_campagna_refresh`)
  - forms:       list / create Marketing Forms v3
  - emails:      list / create Marketing Emails v3
  - workflows:   create v4 Flow

Niente SDK: requests + REST puro, error wrapping uniforme.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

BASE = "https://api.hubapi.com"


class HubSpotError(RuntimeError):
    """Raised when the HubSpot API returns a non-2xx response."""


def _check(r: requests.Response, ctx: str) -> dict[str, Any]:
    if 200 <= r.status_code < 300:
        if not r.content:
            return {}
        try:
            return r.json()
        except ValueError:
            return {"_raw": r.text}
    try:
        body = r.json()
    except ValueError:
        body = {"raw": r.text[:400]}
    raise HubSpotError(
        f"{ctx} -> {r.status_code}: {body.get('message') or body}"
    )


@dataclass(frozen=True)
class Property:
    name: str
    label: str
    type: str
    field_type: str
    group_name: str


@dataclass(frozen=True)
class Form:
    id: str
    name: str
    field_count: int
    archived: bool


class HubSpotClient:
    """Wrapper minimale ma typo-safe degli endpoint usati dal wizard."""

    def __init__(self, access_token: str, portal_id: str = "") -> None:
        if not access_token:
            raise ValueError("HubSpot access_token mancante")
        self.token = access_token
        self.portal_id = portal_id

    # ── low-level ─────────────────────────────────────────────────
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        r = requests.get(
            f"{BASE}{path}",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        return _check(r, f"GET {path}")

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        r = requests.post(
            f"{BASE}{path}",
            headers=self._headers(),
            data=json.dumps(body),
            timeout=30,
        )
        return _check(r, f"POST {path}")

    # ── Properties (custom field id_campagna_refresh) ────────────
    def find_contact_property(self, name: str) -> Property | None:
        try:
            data = self._get(f"/crm/v3/properties/contacts/{name}")
        except HubSpotError as e:
            if "404" in str(e):
                return None
            raise
        return Property(
            name=data["name"],
            label=data.get("label", ""),
            type=data.get("type", ""),
            field_type=data.get("fieldType", ""),
            group_name=data.get("groupName", ""),
        )

    def create_contact_property(
        self,
        *,
        name: str,
        label: str,
        group_name: str = "contactinformation",
        property_type: str = "string",
        field_type: str = "text",
        description: str = "",
    ) -> Property:
        body = {
            "name": name,
            "label": label,
            "type": property_type,
            "fieldType": field_type,
            "groupName": group_name,
            "description": description,
        }
        data = self._post("/crm/v3/properties/contacts", body)
        return Property(
            name=data["name"],
            label=data.get("label", ""),
            type=data.get("type", ""),
            field_type=data.get("fieldType", ""),
            group_name=data.get("groupName", ""),
        )

    # ── Forms (Marketing Forms v3) ───────────────────────────────
    def list_forms(self, limit: int = 100) -> list[Form]:
        data = self._get("/marketing/v3/forms", params={"limit": limit})
        out: list[Form] = []
        for f in data.get("results", []):
            try:
                fc = len(f.get("fieldGroups", [])) if "fieldGroups" in f else 0
            except Exception:
                fc = 0
            out.append(
                Form(
                    id=f["id"],
                    name=f.get("name", ""),
                    field_count=fc,
                    archived=bool(f.get("archived", False)),
                )
            )
        return out

    def create_form(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Crea un form marketing. Payload da ``agent/forms.py``."""
        return self._post("/marketing/v3/forms", payload)

    # ── Marketing Emails ────────────────────────────────────────
    def list_marketing_emails(self, limit: int = 50) -> list[dict[str, Any]]:
        data = self._get("/marketing/v3/emails/", params={"limit": limit})
        return data.get("results", []) or []

    def create_marketing_email(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Crea una marketing email in stato draft. Payload da ``agent/emails.py``."""
        return self._post("/marketing/v3/emails/", payload)

    # ── Workflows v4 (Flows) ─────────────────────────────────────
    def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Crea un workflow v4 (Flow). Payload da ``agent/workflows.py``."""
        return self._post("/automation/v4/flows", payload)
