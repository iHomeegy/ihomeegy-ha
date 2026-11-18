"""Adding iHomeegy units: paste the invite code made in the iHomeegy app (Members > Invite).

Home Assistant accepts the invite like an invited phone does: it opens each unit once with the one-time invite key
and swaps it for a key of its own (the invite is dead after that). One invite may hold several units: each becomes
its own entry.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigFlow, ConfigFlowResult

from . import find_unit
from .const import CONF_HOST, CONF_KEY, CONF_NAME, CONF_PORT, CONF_UNIT_ID, DOMAIN
from .protocol import Invite, InviteUnit, IhError, IhRefused, IhTimeout, IhUnreachable, claim, new_key, parse_invite

try:  # Home Assistant 2025.1+
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # older versions
    from homeassistant.components.zeroconf import ZeroconfServiceInfo  # type: ignore[no-redef]

_LOGGER = logging.getLogger(__name__)

CONF_INVITE = "invite"
_SCHEMA = vol.Schema({vol.Required(CONF_INVITE): str})

# the worst error wins when several units of one invite fail
_ERROR_ORDER = ["unknown", "cannot_connect", "invite_used", "license", "unit_full", "storage"]


def _error_of(err: Exception) -> str:
    if isinstance(err, IhRefused):
        return "invite_used"
    if isinstance(err, (IhUnreachable, IhTimeout)):
        return "cannot_connect"
    if isinstance(err, IhError):
        return {"full": "unit_full", "limit": "unit_full", "license": "license", "storage": "storage"}.get(
            str(err), "invite_used"
        )
    return "unknown"


class IhomeegyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, Any] = {}

    async def _accept_unit(self, inv: Invite, u: InviteUnit) -> dict[str, Any]:
        """Claim one unit of the invite; returns the entry data. Raises the protocol's errors."""
        my_key = new_key()
        host, port = u.host, u.port
        if self._discovered.get(CONF_UNIT_ID) == u.id:
            host, port = self._discovered[CONF_HOST], self._discovered[CONF_PORT]
        last: Exception | None = None
        tried: set[tuple[str, int]] = set()
        for attempt in range(2):
            if attempt == 1 or not host:
                found = await find_unit(self.hass, u.id)  # the address in the invite is old, or there is none
                if not found:
                    break
                host, port = found
            if (host, port) in tried:
                continue
            tried.add((host, port))
            try:
                await claim(host, port, u.id, inv.key, my_key)
                return {
                    CONF_UNIT_ID: u.id,
                    CONF_KEY: my_key.hex(),
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_NAME: u.name,
                }
            except (IhUnreachable, IhTimeout) as err:
                last = err
                continue
        raise last or IhUnreachable("unit not found on this network")

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            inv = parse_invite(user_input[CONF_INVITE])
            if inv is None:
                errors[CONF_INVITE] = "invalid_invite"
            else:
                configured = {e.unique_id for e in self._async_current_entries(include_ignore=False)}
                todo = [u for u in inv.units if u.id not in configured]
                if not todo:
                    return self.async_abort(reason="already_configured")
                done: list[dict[str, Any]] = []
                worst = None
                for u in todo:
                    try:
                        done.append(await self._accept_unit(inv, u))
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("iHomeegy unit %s: invite not accepted: %s", u.id, err)
                        code = _error_of(err)
                        if worst is None or _ERROR_ORDER.index(code) > _ERROR_ORDER.index(worst):
                            worst = code
                if not done:
                    errors["base"] = worst or "unknown"
                else:
                    # the other units of the invite get entries of their own
                    for data in done[1:]:
                        self.hass.async_create_task(
                            self.hass.config_entries.flow.async_init(
                                DOMAIN, context={"source": SOURCE_IMPORT}, data=data
                            )
                        )
                    # Never abort after a claim: the unit already holds the new key. A discovery of the same unit that
                    # is still waiting in the list must not stop this (it is closed when the entry is made).
                    first = done[0]
                    await self.async_set_unique_id(first[CONF_UNIT_ID], raise_on_progress=False)
                    return self.async_create_entry(title=first[CONF_NAME], data=first)
        return self.async_show_form(step_id="user", data_schema=_SCHEMA, errors=errors)

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Another unit of the same invite (already claimed by async_step_user)."""
        await self.async_set_unique_id(import_data[CONF_UNIT_ID], raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=import_data[CONF_NAME], data=import_data)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """A unit seen on the network: keep the address of a known one up to date, offer the others."""
        props = discovery_info.properties or {}
        unit_id = str(props.get("id", "")).lower()
        if len(unit_id) != 16:
            return self.async_abort(reason="not_ihomeegy")
        host = str(discovery_info.ip_address)
        port = int(discovery_info.port or 8890)
        await self.async_set_unique_id(unit_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
        if props.get("p") != "1":
            return self.async_abort(reason="not_paired")  # set it up in the iHomeegy app first
        self._discovered = {CONF_UNIT_ID: unit_id, CONF_HOST: host, CONF_PORT: port}
        self.context["title_placeholders"] = {"id": unit_id[-4:].upper()}
        return await self.async_step_user()

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Home Assistant was removed from the unit (or its key replaced): accept a new invite for it."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        unit_id = entry.data[CONF_UNIT_ID]
        errors: dict[str, str] = {}
        if user_input is not None:
            inv = parse_invite(user_input[CONF_INVITE])
            unit = next((u for u in inv.units if u.id == unit_id), None) if inv else None
            if inv is None:
                errors[CONF_INVITE] = "invalid_invite"
            elif unit is None:
                errors[CONF_INVITE] = "other_unit"
            else:
                if not unit.host:
                    unit.host = entry.data[CONF_HOST]
                try:
                    data = await self._accept_unit(inv, unit)
                except Exception as err:  # noqa: BLE001
                    errors["base"] = _error_of(err)
                else:
                    return self.async_update_reload_and_abort(entry, data_updates=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_SCHEMA,
            errors=errors,
            description_placeholders={"name": entry.title},
        )
