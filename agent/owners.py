"""Pool round-robin di advisor HubSpot.

I 10 advisor del team Leone Master School sono giä definiti in
`meet-advisor-dashboard`. Qui li matchiamo agli owner HubSpot per email/nome
per ottenere i loro `owner_id`, che poi finiranno nel workflow di
assegnazione automatica del contatto post-form-submission.

Strategia di matching:
  1. Match esatto su email (preferito)
  2. Fallback: match esatto su full_name (case-insensitive)
  3. Se nessuno matcha, advisor segnato come MISSING — l'app lo segnala
     in sidebar e l'operatore decide se procedere comunque.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agent.hubspot_api import HubSpotClient, Owner


# I 10 advisor del team Leone, allineati a `meet-advisor-dashboard`.
# Email canoniche se note (la maggior parte usa il dominio leonemasterschool.it).
# Se l'email non e` confermata, lasciamo vuoto e si tenta il match per nome.
ADVISOR_TEAM: tuple[dict[str, str], ...] = (
    {"name": "Marvin Alessandrin",   "email": ""},
    {"name": "Domenico Primo",       "email": ""},
    {"name": "Nora D'Ascanio",       "email": ""},
    {"name": "Cristian Testa",       "email": ""},
    {"name": "Hassan Mozumber",      "email": ""},
    {"name": "Roberta Scicchitano",  "email": ""},
    {"name": "Asma Bouchrit",        "email": ""},
    {"name": "Mattia Primo",         "email": ""},
    {"name": "Vincenzo Meglioli",    "email": ""},
    {"name": "Manuel Cuccu",         "email": ""},
)


@dataclass(frozen=True)
class AdvisorMatch:
    """Risultato del matching advisor team -> HubSpot Owner."""

    advisor_name: str
    advisor_email_hint: str
    owner: Owner | None  # None se non matchato

    @property
    def is_matched(self) -> bool:
        return self.owner is not None


@dataclass(frozen=True)
class OwnerPool:
    """Pool selezionato di owner per il round-robin."""

    matches: tuple[AdvisorMatch, ...] = field(default=())

    @property
    def matched_owner_ids(self) -> tuple[str, ...]:
        """Lista degli owner_id matchati, in ordine team (per round-robin)."""
        return tuple(m.owner.id for m in self.matches if m.is_matched)

    @property
    def missing_advisors(self) -> tuple[str, ...]:
        return tuple(m.advisor_name for m in self.matches if not m.is_matched)


def _norm(s: str) -> str:
    """Normalizza per match case-insensitive."""
    return " ".join(s.lower().strip().split())


def _find_owner(
    owners: list[Owner],
    *,
    email_hint: str,
    name_hint: str,
) -> Owner | None:
    if email_hint:
        for o in owners:
            if _norm(o.email) == _norm(email_hint):
                return o
    target = _norm(name_hint)
    if not target:
        return None
    for o in owners:
        if _norm(o.full_name) == target:
            return o
    # Fallback "contains" piu` permissivo per nomi con varianti
    for o in owners:
        if target in _norm(o.full_name):
            return o
    return None


def build_owner_pool(
    client: HubSpotClient,
    advisors: tuple[dict[str, str], ...] = ADVISOR_TEAM,
) -> OwnerPool:
    """Costruisce il pool matchando i 10 advisor agli owner HubSpot."""
    owners = client.list_owners(only_active=True)
    matches: list[AdvisorMatch] = []
    for adv in advisors:
        owner = _find_owner(
            owners,
            email_hint=adv.get("email", ""),
            name_hint=adv.get("name", ""),
        )
        matches.append(
            AdvisorMatch(
                advisor_name=adv["name"],
                advisor_email_hint=adv.get("email", ""),
                owner=owner,
            )
        )
    return OwnerPool(matches=tuple(matches))


def round_robin_next(
    pool: OwnerPool, *, already_assigned: int = 0
) -> str | None:
    """Ritorna il prossimo owner_id da assegnare in round-robin.

    `already_assigned` e` il numero di contatti gia` assegnati: serve a
    determinare il cursore. La funzione e` PURA, l'orchestrazione (es. salvare
    il cursor) e` responsabilita` del chiamante / workflow HubSpot.
    """
    ids = pool.matched_owner_ids
    if not ids:
        return None
    return ids[already_assigned % len(ids)]
