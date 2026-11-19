"""The iHomeegy integration: control iHomeegy units locally (no internet needed).

Home Assistant joins each unit like a person the owner invited: it has its own key and only the cards the owner gave
it, and the unit itself checks every command. One config entry = one unit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from . import ir as ihir

from .const import CONF_HOST, CONF_KEY, CONF_PORT, CONF_UNIT_ID, DEFAULT_PORT, DOMAIN, MANUFACTURER, ZEROCONF_TYPE
from .protocol import UnitClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.FAN,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SIREN,
    Platform.SWITCH,
    Platform.VALVE,
]

type IhConfigEntry = ConfigEntry[UnitClient]


def signal_update(entry_id: str) -> str:
    return f"{DOMAIN}_update_{entry_id}"


def _entity_signature(client: UnitClient) -> tuple:
    """What decides which entities exist: when it changes, the entry is reloaded."""
    return tuple(sorted((e["id"], e.get("type", "")) for e in client.entities())), ihir.signature(client.ir)


IR_REFRESH = timedelta(minutes=5)  # remotes added / changed in the app (the unit does not announce them)


async def find_unit(hass: HomeAssistant, unit_id: str, timeout: float = 4.0) -> tuple[str, int] | None:
    """Look for a unit on the network by its id (mDNS "_ihomenoise._tcp", TXT id=<unit id>)."""
    from homeassistant.components import zeroconf  # noqa: PLC0415 - only when needed
    from zeroconf import ServiceStateChange  # noqa: PLC0415
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo  # noqa: PLC0415

    aiozc = await zeroconf.async_get_async_instance(hass)
    names: set[str] = set()

    def _on_change(zeroconf: Any, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is not ServiceStateChange.Removed:
            names.add(name)

    browser = AsyncServiceBrowser(aiozc.zeroconf, [ZEROCONF_TYPE], handlers=[_on_change])
    try:
        await asyncio.sleep(timeout)
    finally:
        with contextlib.suppress(Exception):
            await browser.async_cancel()
    for name in names:
        info = AsyncServiceInfo(ZEROCONF_TYPE, name)
        if not await info.async_request(aiozc.zeroconf, 3000):
            continue
        props = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in (info.properties or {}).items()
        }
        if str(props.get("id", "")).lower() != unit_id:
            continue
        addrs = info.parsed_scoped_addresses()
        v4 = [a for a in addrs if ":" not in a]
        if v4 or addrs:
            return (v4 or addrs)[0], int(info.port or DEFAULT_PORT)
    return None


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry) -> bool:
    unit_id: str = entry.data[CONF_UNIT_ID]
    signature: list[tuple] = []
    ir_run: dict[str, Any] = {"busy": False, "at": 0.0, "was_connected": False, "ids": set()}

    async def _refresh_ir() -> None:
        """Read the Universal IR remotes again (a new / changed / deleted remote reloads the entry)."""
        if ir_run["busy"] or not client.connected or ihir.ir_card(client) is None:
            return
        ir_run["busy"] = True
        ir_run["at"] = time.monotonic()
        try:
            got = await ihir.fetch(client, client.ir)
        finally:
            ir_run["busy"] = False
        if got is None:
            return
        remotes, ir_run["ids"] = got
        names_changed = {r["id"]: r["n"] for r in remotes.values()} != {r["id"]: r["n"] for r in client.ir.values()}
        client.ir = remotes
        if signature and _entity_signature(client) != signature[0]:
            signature[0] = _entity_signature(client)
            hass.config_entries.async_schedule_reload(entry.entry_id)
        elif names_changed:
            async_dispatcher_send(hass, signal_update(entry.entry_id))

    def _schedule_ir() -> None:
        hass.async_create_background_task(_refresh_ir(), f"ihomeegy ir {unit_id}")

    @callback
    def _on_update() -> None:
        if signature and client.desc and _entity_signature(client) != signature[0]:
            # cards added / removed, or the owner changed what Home Assistant may control
            signature[0] = _entity_signature(client)
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return
        if signature:
            if client.connected and not ir_run["was_connected"]:
                _schedule_ir()  # (re)connected: the remotes may have changed meanwhile
            else:
                last = (client.state.get("ir1") or {}).get("last") if isinstance(client.state.get("ir1"), dict) else None
                if isinstance(last, dict) and time.monotonic() - ir_run["at"] > 30:
                    if any(k not in ir_run["ids"] for k in last):  # a button of a remote we do not know (maybe a new one)
                        _schedule_ir()
        ir_run["was_connected"] = client.connected
        async_dispatcher_send(hass, signal_update(entry.entry_id))

    @callback
    def _on_removed(code: int) -> None:
        _LOGGER.warning("iHomeegy unit %s: Home Assistant was removed from it (code %s)", unit_id, code)
        entry.async_start_reauth(hass)

    async def _find() -> tuple[str, int] | None:
        return await find_unit(hass, unit_id)

    client = UnitClient(
        unit_id,
        entry.data[CONF_HOST],
        int(entry.data.get(CONF_PORT, DEFAULT_PORT)),
        bytes.fromhex(entry.data[CONF_KEY]),
        on_update=_on_update,
        on_removed=_on_removed,
        find_host=_find,
    )
    client.start()
    if not await client.wait_ready(20):
        await client.stop()
        raise ConfigEntryNotReady(f"iHomeegy unit {unit_id} is not reachable")
    if ihir.ir_card(client) is not None:
        got = await ihir.fetch(client, {})
        if got is not None:
            client.ir, ir_run["ids"] = got
            # a remote deleted in the app: its entity goes too (only IR ones; they are made again if it comes back)
            keep = {f"{unit_id}_ir1_{r['k']}{r['id']}" for r in client.ir.values()}
            reg = er.async_get(hass)
            for ent in er.async_entries_for_config_entry(reg, entry.entry_id):
                if ent.unique_id.startswith(f"{unit_id}_ir1_") and ent.unique_id not in keep:
                    reg.async_remove(ent.entity_id)
        ir_run["at"] = time.monotonic()
    signature.append(_entity_signature(client))
    ir_run["was_connected"] = client.connected
    entry.runtime_data = client

    async def _periodic(_now: Any) -> None:
        await _refresh_ir()

    entry.async_on_unload(async_track_time_interval(hass, _periodic, IR_REFRESH))

    desc = client.desc
    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, unit_id)},
        manufacturer=MANUFACTURER,
        model=str(desc.get("model") or client.hello.get("model") or ""),
        name=str(desc.get("name") or entry.title),
        sw_version=str(desc.get("fw") or client.hello.get("fw") or ""),
        serial_number=unit_id,
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IhConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.stop()
    return ok
