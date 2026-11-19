"""The remotes kept in a Universal IR unit (card type "ir"), read from the unit.

The unit keeps every remote (made in the iHomeegy app from the library or learned) and sends a button by its name:
{"ir1": {"r": <remote id>, "k": "power"}} or, for an A/C, {"ir1": {"r": <id>, "ac": {"m": "cool", "f": "auto", "t": 24}}}.
An IR device never answers, so the unit's state only holds the last button sent per remote ("last") and, for an A/C
that is off, the setting it had ("lon").

Home Assistant shows TVs (media player) and air conditioners (climate) only, for now.
"""

from __future__ import annotations

import logging
from typing import Any

from .protocol import IhError, UnitClient

_LOGGER = logging.getLogger(__name__)

KINDS = ("ac", "tv")  # the remote kinds Home Assistant shows
_MAX_PAGES = 30  # ir_keys pages of one remote (~1.5 KB each); far more than any real remote


def ir_card(client: UnitClient) -> dict[str, Any] | None:
    return next((e for e in client.entities() if e.get("type") == "ir"), None)


async def _keys(client: UnitClient, rid: int) -> list[str]:
    keys: list[str] = []
    start = 0
    for _ in range(_MAX_PAGES):
        r = await client.request({"t": "ir_keys", "id": rid, "from": start})
        page = r.get("k")
        if not isinstance(page, list):
            break
        keys.extend(str(k) for k in page)
        nxt = r.get("next")
        if not isinstance(nxt, int) or nxt <= start:
            break
        start = nxt
    return keys


async def fetch(
    client: UnitClient, old: dict[int, dict[str, Any]]
) -> tuple[dict[int, dict[str, Any]], set[str]] | None:
    """The unit's TV and A/C remotes {id: {"id","n","k","m","c","keys",["caps"]}}, and the ids of all its remotes (any
    kind). None when the unit did not answer.

    The buttons (and an A/C's capabilities) are read again only when the remote changed (its code set or its count).
    """
    try:
        lst = await client.request({"t": "ir_list"})
    except IhError as err:
        _LOGGER.debug("%s: ir_list failed: %s", client.unit_id, err)
        return None
    rows = lst.get("r")
    if lst.get("t") != "ir" or not isinstance(rows, list):
        return None
    out: dict[int, dict[str, Any]] = {}
    every: set[str] = set()
    for row in rows:
        rid = row.get("id") if isinstance(row, dict) else None
        if not isinstance(rid, int) or rid < 1:
            continue
        every.add(str(rid))
        if row.get("k") not in KINDS:
            continue
        rem = {"id": rid, "n": str(row.get("n") or f"Remote {rid}"), "k": row["k"], "m": str(row.get("m") or ""),
               "c": int(row.get("c") or 0)}
        prev = old.get(rid)
        if prev and all(prev.get(x) == rem[x] for x in ("k", "m", "c")):
            rem["keys"] = prev.get("keys", [])
            if "caps" in prev:
                rem["caps"] = prev["caps"]
        else:
            try:
                rem["keys"] = await _keys(client, rid)
                if rem["k"] == "ac":
                    caps = await client.request({"t": "ir_caps", "id": rid})
                    rem["caps"] = {k: caps.get(k) for k in ("modes", "fans", "swing", "min", "max", "off")}
            except IhError as err:
                _LOGGER.debug("%s: remote %s: %s", client.unit_id, rid, err)
                return None
        out[rid] = rem
    return out, every


def signature(remotes: dict[int, dict[str, Any]]) -> tuple:
    """What decides which IR entities exist and what they can do (a name change does not count)."""
    return tuple(sorted((r["id"], r["k"], r["m"], r["c"]) for r in remotes.values()))


def parse_ac(key: Any) -> dict[str, Any] | None:
    """'cool/auto/24' or 'cool/auto/24/on' -> {"m","f","t","sw"}; None for anything else ('off', 'swing', ...)."""
    if not isinstance(key, str):
        return None
    p = key.split("/")
    if len(p) not in (3, 4):
        return None
    try:
        t = int(p[2])
    except ValueError:
        return None
    return {"m": p[0], "f": p[1], "t": t, "sw": p[3] if len(p) == 4 else ""}
