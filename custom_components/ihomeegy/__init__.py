"""The iHomeegy integration: control iHomeegy units locally (no internet needed).

Home Assistant joins each unit like a person the owner invited: it has its own key and only the cards the owner gave
it, and the unit itself checks every command. One config entry = one unit.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send

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
    return tuple(sorted((e["id"], e.get("type", "")) for e in client.entities()))


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

    @callback
    def _on_update() -> None:
        if signature and client.desc and _entity_signature(client) != signature[0]:
            # cards added / removed, or the owner changed what Home Assistant may control
            signature[0] = _entity_signature(client)
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return
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
    signature.append(_entity_signature(client))
    entry.runtime_data = client

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
