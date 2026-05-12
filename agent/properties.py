"""Custom property `id_campagna_refresh` su contatti HubSpot.

Idempotente: verifica se esiste, altrimenti crea. Usato sia in setup iniziale
che ogni volta che il form viene generato (cosi` siamo sicuri che il campo
nascosto del form punti a una property reale).
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.hubspot_api import HubSpotClient, Property

# Nome canonico della property che il team Leone usa per legare un contatto
# a una campagna Meta in refresh. Allineato a quanto gia` presente in
# meta-ads-analyzer / refresher.
REFRESH_PROPERTY_NAME = "id_campagna_refresh"
REFRESH_PROPERTY_LABEL = "ID campagna refresh"
REFRESH_PROPERTY_DESCRIPTION = (
    "Identificatore della campagna Meta da cui il contatto e` arrivato. "
    "Valorizzato automaticamente dal form Leone come hidden field; usato "
    "dai workflow di assegnazione e nurturing per segmentare per campagna."
)


@dataclass(frozen=True)
class PropertyStatus:
    """Esito della verifica/creazione."""

    property: Property
    created: bool


def ensure_refresh_property(client: HubSpotClient) -> PropertyStatus:
    """Garantisce che la property `id_campagna_refresh` esista.

    Se esiste, ritorna `created=False` + la property esistente.
    Se manca, la crea come single-line text e ritorna `created=True`.
    """
    existing = client.find_contact_property(REFRESH_PROPERTY_NAME)
    if existing is not None:
        return PropertyStatus(property=existing, created=False)

    created = client.create_contact_property(
        name=REFRESH_PROPERTY_NAME,
        label=REFRESH_PROPERTY_LABEL,
        property_type="string",
        field_type="text",
        description=REFRESH_PROPERTY_DESCRIPTION,
    )
    return PropertyStatus(property=created, created=True)
