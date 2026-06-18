"""Tests for the ROR affiliation-city lookup (no network: _fetch is stubbed)."""

from inst2ord.models import Affiliation, MaDmp, Person
from inst2ord.ror import (
    RorClient,
    _city_from_payload,
    _ror_id,
    enrich_affiliations,
)

_PAYLOAD = {
    "id": "https://ror.org/03yrm5c26",
    "locations": [
        {"geonames_details": {"name": "Vienna", "country_name": "Austria"}}
    ],
}


def test_ror_id_from_url_and_bare():
    assert _ror_id("https://ror.org/03yrm5c26") == "03yrm5c26"
    assert _ror_id("03yrm5c26") == "03yrm5c26"
    assert _ror_id("http://ror.org/03yrm5c26/") == "03yrm5c26"
    assert _ror_id("") is None
    assert _ror_id(None) is None


def test_city_from_payload_walks_locations():
    assert _city_from_payload(_PAYLOAD) == "Vienna"
    assert _city_from_payload({"locations": [{}]}) is None
    assert _city_from_payload({"locations": "nope"}) is None
    assert _city_from_payload("nope") is None


def test_city_uses_cache_and_fetches_once(tmp_path, monkeypatch):
    client = RorClient(cache_dir=str(tmp_path))
    calls = []
    monkeypatch.setattr(
        client, "_fetch", lambda rid: calls.append(rid) or {"city": "Vienna"}
    )
    assert client.city("https://ror.org/03yrm5c26") == "Vienna"
    # Second call (even via a fresh client) is served from disk -> no fetch.
    fresh = RorClient(cache_dir=str(tmp_path))
    monkeypatch.setattr(
        fresh, "_fetch", lambda rid: calls.append(rid) or {"city": "X"}
    )
    assert fresh.city("03yrm5c26") == "Vienna"
    assert calls == ["03yrm5c26"]  # fetched exactly once


def test_transient_failure_is_not_cached(tmp_path, monkeypatch):
    client = RorClient(cache_dir=str(tmp_path))
    monkeypatch.setattr(client, "_fetch", lambda rid: None)
    assert client.city("03yrm5c26") is None
    assert not list(tmp_path.iterdir())  # nothing written


def test_missing_id_returns_none_without_fetch(monkeypatch):
    client = RorClient()
    monkeypatch.setattr(
        client, "_fetch", lambda rid: (_ for _ in ()).throw(AssertionError())
    )
    assert client.city("") is None


def test_enrich_affiliations_fills_city_once(monkeypatch):
    ror = "https://ror.org/03yrm5c26"
    madmp = MaDmp(
        contact=Person(affiliations=[Affiliation(name="TU", ror=ror)]),
        contributors=[
            Person(affiliations=[Affiliation(name="TU", ror=ror)]),
            Person(affiliations=[Affiliation(name="No ROR")]),
        ],
    )
    client = RorClient()
    calls = []
    monkeypatch.setattr(
        client, "city", lambda r: calls.append(r) or "Vienna"
    )
    enrich_affiliations(madmp, client)
    assert madmp.contact.affiliations[0].city == "Vienna"
    assert madmp.contributors[0].affiliations[0].city == "Vienna"
    assert madmp.contributors[1].affiliations[0].city is None  # no ROR
    assert calls == [ror]  # one lookup despite two uses of the same ROR
