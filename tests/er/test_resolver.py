"""Entity resolution: normalization, the three outcomes, and the measured quality on the labeled pairs."""

from __future__ import annotations

import pytest

from er.evaluate import load, metrics, report
from er.normalize import compact, normalize
from er.resolver import AMBIGUOUS_FROM, Party, compare, pair_id, propose_links, resolve


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Orbital Lens Works, Inc.", "ORBITAL LENS WORKS INCORPORATED"),
        ("GenH2", "GenH2 Corporation"),
        ("Halcyon Sensorics GmbH", "Halcyon Sensorics"),
        ("North Wind Labs LLC", "Northwind Labs"),
    ],
)
def test_legal_forms_case_and_spacing_do_not_separate_one_name(a: str, b: str) -> None:
    assert compact(a) == compact(b)
    assert compare(a, b).status == "match"


def test_normalize_keeps_the_distinguishing_words() -> None:
    assert normalize("Cobalt Ridge Medical, LLC") != normalize("Cobalt Ridge Aerospace, LLC")


def test_the_same_name_at_two_addresses_goes_to_a_person() -> None:
    o = compare("Acme Sensors Inc.", "Acme Sensors", "Huntsville, Alabama", "Portland, Oregon")
    assert o.status == "ambiguous" and "addresses disagree" in o.basis


def test_similar_but_different_names_are_proposed_never_linked() -> None:
    o = compare("Cobalt Ridge Medical", "Cobalt Ridge Medicals Group")
    assert o.status in ("ambiguous", "none")
    assert o.status != "match"


def test_comparison_is_symmetric_on_every_labeled_pair() -> None:
    for r in load():
        ab = compare(r["a"], r["b"], r["address_a"], r["address_b"])
        ba = compare(r["b"], r["a"], r["address_b"], r["address_a"])
        assert (ab.status, ab.score) == (ba.status, ba.score), r["id"]


def test_two_exact_matches_stay_ambiguous_for_a_steward() -> None:
    parties = [Party("urn:a", "GenH2"), Party("urn:b", "GenH2 Corporation"), Party("urn:c", "Other Co")]
    status, ranked = resolve("GenH2 Corp.", parties)
    assert status == "ambiguous"
    assert {c.party.iri for c in ranked[:2]} == {"urn:a", "urn:b"}


def test_pair_ids_do_not_depend_on_order_and_linked_pairs_are_not_proposed() -> None:
    a, b = Party("urn:a", "GenH2"), Party("urn:b", "GenH2 Corporation")
    assert pair_id("urn:a", "urn:b") == pair_id("urn:b", "urn:a")
    assert len(propose_links([a, b])) == 1
    assert propose_links([a, b], linked={frozenset(("urn:a", "urn:b"))}) == []


def test_the_threshold_was_set_on_the_development_split() -> None:
    assert AMBIGUOUS_FROM == 0.74
    splits = {r["split"] for r in load()}
    assert splits == {"dev", "test", "holdout"}
    assert sum(1 for r in load() if r["split"] == "holdout") == 20


def test_an_automatic_match_is_never_wrong_on_any_split() -> None:
    """The resolver links nothing by itself, but a 'match' is shown as the likely answer, so it must be right."""
    for name, m in report().items():
        assert m["auto"]["fp"] == 0, name


def test_quality_on_the_held_out_pairs() -> None:
    holdout = metrics([r for r in load() if r["split"] == "holdout"])
    assert holdout["auto"]["precision"] == 1.0 and holdout["auto"]["recall"] >= 0.9
    assert holdout["proposed"]["recall"] == 1.0, "every true pair reaches the steward queue"
    test = metrics([r for r in load() if r["split"] == "test"])
    assert test["proposed"]["recall"] >= 0.9
