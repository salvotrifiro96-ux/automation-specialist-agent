from agent.hubspot_api import Owner
from agent.owners import (
    AdvisorMatch,
    OwnerPool,
    _find_owner,
    round_robin_next,
)


def _owner(oid: str, first: str, last: str, email: str = "") -> Owner:
    return Owner(id=oid, email=email, first_name=first, last_name=last)


class TestFindOwner:
    def test_exact_email_match(self):
        owners = [
            _owner("1", "Mario", "Rossi", "mario@x.com"),
            _owner("2", "Anna", "Bianchi", "anna@x.com"),
        ]
        out = _find_owner(owners, email_hint="anna@x.com", name_hint="Wrong Name")
        assert out is not None and out.id == "2"

    def test_exact_name_match(self):
        owners = [
            _owner("1", "Mario", "Rossi"),
            _owner("2", "Anna", "Bianchi"),
        ]
        out = _find_owner(owners, email_hint="", name_hint="Anna Bianchi")
        assert out is not None and out.id == "2"

    def test_case_insensitive(self):
        owners = [_owner("1", "Mario", "Rossi")]
        out = _find_owner(owners, email_hint="", name_hint="MARIO  ROSSI")
        assert out is not None and out.id == "1"

    def test_fallback_contains(self):
        owners = [_owner("1", "Marco", "Polo")]
        out = _find_owner(owners, email_hint="", name_hint="Marco")
        assert out is not None and out.id == "1"

    def test_no_match(self):
        owners = [_owner("1", "Mario", "Rossi")]
        assert _find_owner(owners, email_hint="", name_hint="Inesistente") is None


class TestOwnerPool:
    def test_matched_owner_ids_in_order(self):
        pool = OwnerPool(matches=(
            AdvisorMatch("a", "", _owner("100", "A", "A")),
            AdvisorMatch("b", "", None),
            AdvisorMatch("c", "", _owner("300", "C", "C")),
        ))
        assert pool.matched_owner_ids == ("100", "300")
        assert pool.missing_advisors == ("b",)


class TestRoundRobin:
    def test_cycles(self):
        pool = OwnerPool(matches=(
            AdvisorMatch("a", "", _owner("1", "A", "A")),
            AdvisorMatch("b", "", _owner("2", "B", "B")),
            AdvisorMatch("c", "", _owner("3", "C", "C")),
        ))
        seen = [round_robin_next(pool, already_assigned=i) for i in range(6)]
        assert seen == ["1", "2", "3", "1", "2", "3"]

    def test_empty_pool(self):
        pool = OwnerPool(matches=())
        assert round_robin_next(pool, already_assigned=0) is None
        assert round_robin_next(pool, already_assigned=10) is None
