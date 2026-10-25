"""Each rule, branch by branch, on a tiny world. The injected cases cover the system; these cover the edges."""

from __future__ import annotations

import itertools

import pytest

from rules.model import EXCLUSIVITY_TYPES, Status
from tests.rules.world import GEN, decide, executed, facts, request, store_with


def uspto(n: int, state: str, **kw: str) -> str:
    props = [f"gng:legalState state:{state}", 'gng:statusText "status"', "prov:wasDerivedFrom id:registry/uspto/1"]
    if "exp" in kw:
        props += [
            f'gng:expirationDate "{kw["exp"]}"^^xsd:date',
            'gng:expirationBasis "filing + 20 years"',
            "gng:expirationIsDerived true",
        ]
    if "lapse" in kw:
        props.append(f'gng:lapseDate "{kw["lapse"]}"^^xsd:date')
    if "reinstated" in kw:
        props.append(f'gng:reinstatedOn "{kw["reinstated"]}"^^xsd:date')
    if kw.get("disclaimer"):
        props.append("gng:hasTerminalDisclaimer true")
    return (
        'id:registry/uspto/1 a gng:RegistryRecord ; dct:title "USPTO" ; '
        'schema:url "https://example.org/u"^^xsd:anyURI .\n' + facts(n, "PatentLegalStatus", " ; ".join(props) + " ;")
    )


def nasa(n: int, exp: str | None = None, state: str | None = None) -> str:
    props = ['gng:statusText "Issued"', "prov:wasDerivedFrom id:registry/nasa-patents"]
    if exp:
        props += [
            f'gng:expirationDate "{exp}"^^xsd:date',
            'gng:expirationBasis "NASA nominal"',
            "gng:expirationIsDerived false",
        ]
    if state:
        props.append(f"gng:legalState state:{state}")
    return 'id:registry/nasa-patents a gng:RegistryRecord ; dct:title "NASA" .\n' + facts(
        n, "PatentLegalStatus", " ; ".join(props) + " ;"
    )


# ---------------------------------------------------------------------------------------------- R1


@pytest.mark.parametrize(
    ("facts_ttl", "status", "word"),
    [
        (uspto(1, "in-force", exp="2036-05-02"), Status.PASS, "in force"),
        (uspto(1, "in-force", exp="2026-12-31"), Status.FAIL, "term ended"),
        (uspto(1, "term-ended", exp="2025-01-01"), Status.FAIL, "term ended"),
        (uspto(1, "lapsed", exp="2030-01-01", lapse="2020-01-20"), Status.FAIL, "unpaid maintenance fees"),
        (uspto(1, "abandoned"), Status.FAIL, "no patent issued"),
        (uspto(1, "not-granted"), Status.FAIL, "no patent issued"),
        (uspto(1, "in-force"), Status.UNKNOWN, "no dates"),
        (nasa(1, exp="2026-12-31"), Status.FAIL, "before the requested start"),
        (nasa(1, exp="2036-01-01"), Status.UNKNOWN, "cannot show a lapse"),
        (nasa(1, state="application"), Status.UNKNOWN, "application"),
        (nasa(1), Status.UNKNOWN, "No registry"),
        ("", Status.UNKNOWN, "No registry"),
    ],
)
def test_r1_branches(facts_ttl: str, status: Status, word: str) -> None:
    f = decide(store_with(facts_ttl)).finding("R1")
    assert f["status"] == status, f["summary"]
    assert word.lower() in f["summary"].lower()


def test_r1_prefers_the_uspto_over_the_snapshot() -> None:
    f = decide(store_with(nasa(1, exp="2036-01-01"), uspto(2, "lapsed", exp="2030-01-01", lapse="2020-01-20"))).finding(
        "R1"
    )
    assert f["status"] == "FAIL"
    assert "snapshot still lists" in f["notes"][0]


def test_r1_derived_expiration_is_labeled_and_can_pass_or_fail() -> None:
    def filing(date: str) -> str:
        return facts(3, "FilingRecord", f'gng:filingDate "{date}"^^xsd:date ;', synthetic=True)

    ok = decide(store_with(filing("2016-05-02"))).finding("R1")
    assert ok["status"] == "PASS" and ok["details"]["expiration_derived"] is True
    assert "derived" in ok["notes"][0]
    assert decide(store_with(filing("2004-03-15"))).finding("R1")["status"] == "FAIL"


def test_r1_reinstated_patent_passes_with_an_intervening_rights_note() -> None:
    f = decide(store_with(uspto(1, "in-force", exp="2036-05-02", lapse="2024-06-24", reinstated="2025-05-21"))).finding(
        "R1"
    )
    assert f["status"] == "PASS"
    assert any("intervening rights" in n for n in f["notes"])


def test_r1_flags_a_terminal_disclaimer_and_a_term_that_ends_mid_request() -> None:
    f = decide(store_with(uspto(1, "in-force", exp="2029-01-01", disclaimer="1"))).finding("R1")
    assert f["status"] == "PASS"
    assert any("terminal disclaimer" in n for n in f["notes"])
    assert any("before the requested term ends" in n for n in f["notes"])


def test_r1_ignores_a_status_recorded_after_the_cutoff() -> None:
    late = uspto(1, "lapsed", exp="2030-01-01", lapse="2020-01-20").replace(
        "2026-10-24T18:00:00Z", "2026-12-01T00:00:00Z"
    )
    store = store_with(late)
    assert decide(store, cutoff="2026-11-01T00:00:00Z").finding("R1")["status"] == "UNKNOWN"
    assert decide(store, cutoff="2026-12-02T00:00:00Z").finding("R1")["status"] == "FAIL"


# ---------------------------------------------------------------------------------------------- R2


def expected_conflict(requested: str, existing: str) -> bool:
    return requested == "exclusive" or existing == "exclusive"


@pytest.mark.parametrize(("requested", "existing"), list(itertools.product(EXCLUSIVITY_TYPES, repeat=2)))
def test_r2_exclusivity_matrix(requested: str, existing: str) -> None:
    f = decide(store_with(executed(1, existing)), request(exclusivity=requested)).finding("R2")
    assert f["status"] == ("FAIL" if expected_conflict(requested, existing) else "PASS"), f["summary"]


@pytest.mark.parametrize(
    ("grant_field", "grant_territory", "req_field", "req_territory", "overlaps"),
    [
        ("optics", "US", "lasers", "US", True),  # a broad grant covers a narrower request
        ("lasers", "US", "optics", "US", True),  # a broad request covers a narrower grant
        ("lenses-and-mirrors", "US", "lasers", "US", False),  # siblings do not overlap
        ("lasers", "NORTH-AMERICA", "lasers", "US", True),
        ("lasers", "US", "lasers", "NORTH-AMERICA", True),
        ("lasers", "DE", "lasers", "US", False),
        ("lasers", "EUROPE", "lasers", "US", False),
        ("lasers", "WORLD", "lasers", "US", True),
    ],
)
def test_r2_hierarchy_in_both_directions(
    grant_field: str, grant_territory: str, req_field: str, req_territory: str, overlaps: bool
) -> None:
    store = store_with(executed(1, "exclusive", field=grant_field, territory=grant_territory))
    f = decide(store, request(field=req_field, territory=req_territory)).finding("R2")
    assert f["status"] == ("FAIL" if overlaps else "PASS")


@pytest.mark.parametrize(
    ("start", "end", "overlaps"),
    [
        ("2025-01-01", "2034-12-31", True),
        ("2018-01-01", "2024-12-31", False),
        ("2032-01-01", "2036-12-31", False),
        ("2030-01-01", "2036-12-31", True),
        ("2036-01-01", "2038-12-31", False),
        ("2020-01-01", "2027-06-30", True),
    ],
)
def test_r2_term_overlap(start: str, end: str, overlaps: bool) -> None:
    f = decide(store_with(executed(1, "exclusive", start=start, end=end))).finding("R2")
    assert f["status"] == ("FAIL" if overlaps else "PASS")


def test_r2_a_grant_recorded_after_the_cutoff_or_superseded_before_it_does_not_count() -> None:
    late = executed(1, "exclusive", recorded="2026-12-01T00:00:00Z")
    assert decide(store_with(late)).finding("R2")["status"] == "PASS"
    superseded = executed(1, "exclusive") + '\nid:fact/1 gng:supersededAt "2026-10-30T00:00:00Z"^^xsd:dateTime .'
    assert decide(store_with(superseded), cutoff="2026-11-01T00:00:00Z").finding("R2")["status"] == "PASS"
    assert decide(store_with(superseded), cutoff="2026-10-29T00:00:00Z").finding("R2")["status"] == "FAIL"


def proposed(
    n: int, licensee: str, exclusivity: str = "exclusive", field: str | None = None, territory: str | None = None
) -> str:
    props = [
        f"gng:exclusivityType excl:{exclusivity}",
        'gng:fieldOfUseStatus "not_mentioned"',
        'gng:publishedOn "2026-09-01"^^xsd:date',
    ]
    if field:
        props.append(f"gng:fieldOfUse field:{field}")
    if territory:
        props.append(f"gng:territory territory:{territory}")
    if licensee:
        props.append(f"gng:licensee id:licensee/{licensee}")
    return f'id:notice/{n} a gng:LicenseNotice ; dct:identifier "n{n}" .\n' + facts(
        n, "ProposedGrant", " ; ".join(props) + f" ; gng:announcedIn id:notice/{n} ;", valid_from="2026-09-01"
    )


def test_r2_another_partys_proposed_grant_needs_review_even_when_its_field_is_unstated() -> None:
    f = decide(store_with(proposed(1, "L2"))).finding("R2")
    assert f["status"] == "REVIEW"
    assert any("states no field" in n for n in f["notes"])


def test_r2_ignores_the_requesters_own_notice_and_non_overlapping_ones() -> None:
    assert decide(store_with(proposed(1, "L1"))).finding("R2")["status"] == "PASS"
    assert (
        decide(store_with(proposed(1, "L2", field="lenses-and-mirrors", territory="US"))).finding("R2")["status"]
        == "PASS"
    )
    assert (
        decide(
            store_with(proposed(1, "L2", exclusivity="non-exclusive")), request(exclusivity="non-exclusive")
        ).finding("R2")["status"]
        == "PASS"
    )
    assert (
        decide(store_with(proposed(1, "L2", exclusivity="non-exclusive")), request(exclusivity="exclusive")).finding(
            "R2"
        )["status"]
        == "REVIEW"
    )


def test_r2_an_executed_conflict_outranks_a_proposed_one() -> None:
    f = decide(store_with(executed(1, "exclusive"), proposed(2, "L2"))).finding("R2")
    assert f["status"] == "FAIL"


# ---------------------------------------------------------------------------------------------- R3


def co_request() -> object:
    return request(exclusivity="co-exclusive")


@pytest.mark.parametrize(
    ("existing", "status"),
    [
        ([], "UNKNOWN"),
        ([executed(1, "co-exclusive", licensee="L2")], "UNKNOWN"),  # no cap stated
        ([executed(1, "co-exclusive", licensee="L2", cap=3)], "PASS"),
        ([executed(1, "co-exclusive", licensee="L2", cap=2)], "PASS"),
    ],
)
def test_r3_cap_states(existing: list[str], status: str) -> None:
    f = decide(store_with(*existing), co_request()).finding("R3")  # type: ignore[arg-type]
    assert f["status"] == status, f["summary"]


def test_r3_fails_when_the_request_would_exceed_the_cap() -> None:
    two = [executed(1, "co-exclusive", licensee="L2", cap=2), executed(2, "co-exclusive", licensee="L3", cap=2)]
    f = decide(store_with('id:licensee/L3 a gng:Licensee ; schema:legalName "Third" .', *two), co_request()).finding(
        "R3"
    )  # type: ignore[arg-type]
    assert f["status"] == "FAIL"
    assert f["details"]["cap"] == 2 and f["details"]["holders"] == 2


def test_r3_does_not_count_the_requester_as_another_holder() -> None:
    own = executed(1, "co-exclusive", licensee="L1", cap=1)
    assert decide(store_with(own), co_request()).finding("R3")["status"] == "PASS"  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ["exclusive", "partially-exclusive", "non-exclusive"])
def test_r3_applies_only_to_co_exclusive_requests(kind: str) -> None:
    assert decide(store_with(), request(exclusivity=kind)).finding("R3")["status"] == "NOT_APPLICABLE"


# ---------------------------------------------------------------------------------------------- R4


def test_r4_window_states() -> None:
    def notice(deadline: str | None) -> str:
        n = proposed(1, "L1").replace(
            'gng:publishedOn "2026-09-01"^^xsd:date',
            'gng:publishedOn "2026-09-01"^^xsd:date'
            + (
                f' ; gng:objectionDeadline "{deadline}"^^xsd:date ; gng:objectionDeadlineBasis "stated date"'
                if deadline
                else ""
            ),
        )
        return n

    exclusive = request(exclusivity="exclusive")
    assert decide(store_with(notice("2026-11-04")), exclusive).finding("R4")["status"] == "PENDING"
    assert (
        decide(store_with(notice("2026-11-01")), exclusive).finding("R4")["status"] == "PENDING"
    )  # the last day still counts
    assert decide(store_with(notice("2026-10-31")), exclusive).finding("R4")["status"] == "PASS"
    assert decide(store_with(notice(None)), exclusive).finding("R4")["status"] == "UNKNOWN"
    assert decide(store_with(), exclusive).finding("R4")["status"] == "REVIEW"
    assert (
        decide(store_with(notice("2026-11-04")), request(exclusivity="non-exclusive")).finding("R4")["status"]
        == "NOT_APPLICABLE"
    )


def test_r4_matches_a_notice_through_an_approved_same_as_link() -> None:
    """A notice names 'Requester Corp' and the request says 'Requester Inc.'. A steward linked them."""
    other = proposed(1, "L2").replace(
        "gng:exclusivityType",
        'gng:objectionDeadline "2026-11-04"^^xsd:date ; gng:objectionDeadlineBasis "stated date" ; gng:exclusivityType',
    )
    exclusive = request(exclusivity="exclusive")
    assert decide(store_with(other), exclusive).finding("R4")["status"] == "REVIEW"
    link = "id:licensee/L1 owl:sameAs id:licensee/L2 ."
    assert decide(store_with(other, link), exclusive).finding("R4")["status"] == "PENDING"


# ---------------------------------------------------------------------------------------------- R5


def export(kind: str, countries: tuple[str, ...] = ()) -> str:
    permitted = "; ".join(f"gng:permittedTerritory territory:{c}" for c in countries)
    return facts(5, kind, permitted + " ;" if permitted else "", synthetic=True)


@pytest.mark.parametrize(
    ("ttl", "country", "status"),
    [
        (export("UnrestrictedExport"), "CN", "PASS"),
        (export("RestrictedExport", ("US", "CA")), "CA", "PASS"),
        (export("RestrictedExport", ("US", "CA")), "CN", "REVIEW"),
        (export("RestrictedExport", ("US",)), None, "UNKNOWN"),
        ("", "US", "UNKNOWN"),
    ],
)
def test_r5_states(ttl: str, country: str | None, status: str) -> None:
    assert decide(store_with(ttl), request(licensee_country=country)).finding("R5")["status"] == status


# ---------------------------------------------------------------------------------------------- R6


def ownership(complete: bool, owners: tuple[str, ...] = ()) -> str:
    listed = "".join(f"gng:coOwner id:coowner/{o} ; " for o in owners)
    nodes = "".join(f'id:coowner/{o} a gng:CoOwner ; schema:legalName "{o} University" .\n' for o in owners)
    return nodes + facts(
        6, "OwnershipRecord", f"gng:coOwnerListIsComplete {str(complete).lower()} ; {listed}", synthetic=True
    )


def consent(owner: str, n: int = 7) -> str:
    return facts(n, "ConsentRecord", f"gng:consentBy id:coowner/{owner} ;", synthetic=True)


@pytest.mark.parametrize(
    ("ttl", "status"),
    [
        ([], "UNKNOWN"),
        ([ownership(False)], "UNKNOWN"),
        ([ownership(True)], "PASS"),
        ([ownership(True, ("A",))], "REVIEW"),
        ([ownership(True, ("A",)), consent("A")], "PASS"),
        ([ownership(True, ("A", "B")), consent("A")], "REVIEW"),
        ([ownership(False, ("A",))], "REVIEW"),
        ([ownership(False, ("A",)), consent("A")], "UNKNOWN"),
    ],
)
def test_r6_states(ttl: list[str], status: str) -> None:
    f = decide(store_with(*ttl)).finding("R6")
    assert f["status"] == status, f["summary"]


# ---------------------------------------------------------------------------------------------- R7


@pytest.mark.parametrize("kind", EXCLUSIVITY_TYPES)
def test_r7_reviews_every_exclusive_family_request(kind: str) -> None:
    expected = "NOT_APPLICABLE" if kind == "non-exclusive" else "REVIEW"
    assert decide(store_with(), request(exclusivity=kind)).finding("R7")["status"] == expected


def test_an_exclusive_request_never_reaches_go_even_with_perfect_evidence() -> None:
    perfect = [uspto(1, "in-force", exp="2036-05-02"), export("UnrestrictedExport"), ownership(True)]
    assert decide(store_with(*perfect), request(exclusivity="non-exclusive")).verdict == "GO"
    for kind in ("exclusive", "partially-exclusive", "co-exclusive"):
        assert decide(store_with(*perfect), request(exclusivity=kind)).verdict != "GO"


_ = GEN
