"""Resolve maDMP affiliation cities from the ROR API.

A maDMP affiliation may carry a ROR id (e.g. ``https://ror.org/03yrm5c26``).
This module resolves that id to the organisation's city via the ROR **v2**
API -- ``locations[].geonames_details.name`` -- and caches each response on
disk so a given ROR is fetched at most once.  Network or format failures
degrade gracefully to ``None``: the builder then simply omits
``provenance.city`` and still records the affiliation name and ROR.

It mirrors the compound resolver's network/cache discipline and, like it,
touches the network only when explicitly enabled by the CLI (``--resolve``).
The ORD builder stays network-free: it reads the ``city`` this module writes
onto :class:`~inst2ord.models.Affiliation` rather than calling out itself.
"""

from __future__ import annotations

import json
import os

from inst2ord.models import MaDmp

_ROR_URL = "https://api.ror.org/v2/organizations/{id}"


class RorClient:
    """Look up affiliation cities from the ROR API, with on-disk caching."""

    def __init__(
        self, cache_dir: str | None = None, timeout: float = 15.0
    ) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout

    def city(self, ror: str) -> str | None:
        """Return the city for a ROR id/URL, or ``None`` if unavailable.

        ``None`` covers a missing id, a transient network failure (not
        cached) and an organisation with no geonames city (cached as a
        known miss so it is not re-fetched).
        """
        ror_id = _ror_id(ror)
        if not ror_id:
            return None
        cached = self._cache_read(ror_id)
        if cached is not None:
            return cached.get("city")
        result = self._fetch(ror_id)
        if result is None:
            return None  # transient failure -- do not cache as a miss
        self._cache_write(ror_id, result)
        return result.get("city")

    # -- internals ----------------------------------------------------------

    def _fetch(self, ror_id: str) -> dict | None:
        import requests  # local import keeps the dep optional

        try:
            response = requests.get(
                _ROR_URL.format(id=ror_id), timeout=self.timeout
            )
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            payload = response.json()
        except ValueError:
            return None
        return {"city": _city_from_payload(payload)}

    def _cache_path(self, ror_id: str) -> str | None:
        if not self.cache_dir:
            return None
        return os.path.join(self.cache_dir, f"{ror_id}.json")

    def _cache_read(self, ror_id: str) -> dict | None:
        path = self._cache_path(ror_id)
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            return None

    def _cache_write(self, ror_id: str, data: dict) -> None:
        path = self._cache_path(ror_id)
        if not path:
            return
        os.makedirs(self.cache_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)


def enrich_affiliations(madmp: MaDmp, client: RorClient) -> None:
    """Fill :attr:`Affiliation.city` for every ROR-bearing affiliation.

    Walks the contact and contributors, looking up each distinct ROR once
    (already-resolved affiliations are skipped), so the maDMP the builder
    later consumes carries the cities inline.
    """
    seen: dict[str, str | None] = {}
    for person in _people(madmp):
        for affiliation in person.affiliations:
            if not affiliation.ror or affiliation.city:
                continue
            if affiliation.ror not in seen:
                seen[affiliation.ror] = client.city(affiliation.ror)
            affiliation.city = seen[affiliation.ror]


def _people(madmp: MaDmp) -> list:
    people = list(madmp.contributors)
    if madmp.contact:
        people.append(madmp.contact)
    return people


def _city_from_payload(payload) -> str | None:
    """Pull the city from a ROR v2 organisation record's locations."""
    if not isinstance(payload, dict):
        return None
    locations = payload.get("locations")
    if not isinstance(locations, list):
        return None
    for location in locations:
        if not isinstance(location, dict):
            continue
        details = location.get("geonames_details")
        if isinstance(details, dict) and details.get("name"):
            return details["name"]
    return None


def _ror_id(ror) -> str | None:
    """Reduce a ROR id or URL to the bare id the ROR API expects."""
    if not isinstance(ror, str) or not ror.strip():
        return None
    return ror.rstrip("/").rsplit("/", 1)[-1] or None
