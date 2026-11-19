"""Base entity: one card of an iHomeegy unit."""

from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .protocol import IhCommandError, IhError, UnitClient

_REFUSALS = {
    "forbidden": "The owner did not give Home Assistant this card",
    "license": "The unit's license does not allow it",
    "busy": "The unit is busy right now (e.g. a moving shutter), try again",
    "not_found": "This remote has no code for that (add the button in the iHomeegy app)",
    "no_ir": "The unit's IR transmitter is not set up",
}


def cards_of(client: UnitClient, *types: str) -> list[dict[str, Any]]:
    return [e for e in client.entities() if e.get("type") in types]


class IhEntity(Entity):
    """One card. Its state comes pushed from the unit (no polling)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, client: UnitClient, entry_id: str, card: dict[str, Any], suffix: str = "") -> None:
        self._client = client
        self._entry_id = entry_id
        self._card = card
        self._cid: str = card["id"]
        self._attr_unique_id = f"{client.unit_id}_{self._cid}{suffix}"
        self._attr_name = card.get("name") or self._cid
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, client.unit_id)})

    async def async_added_to_hass(self) -> None:
        from . import signal_update  # noqa: PLC0415 - avoids an import cycle

        self.async_on_remove(async_dispatcher_connect(self.hass, signal_update(self._entry_id), self._on_update))

    @callback
    def _on_update(self) -> None:
        for e in self._client.entities():  # the card may have been renamed in the app
            if e.get("id") == self._cid:
                self._card = e
                self._update_name()
                break
        self.async_write_ha_state()

    def _update_name(self) -> None:
        self._attr_name = self._card.get("name") or self._cid

    @property
    def raw(self) -> Any:
        """This card's value in the unit's state (None when the unit has none)."""
        return self._client.state.get(self._cid)

    @property
    def obj(self) -> dict[str, Any]:
        v = self.raw
        return v if isinstance(v, dict) else {}

    @property
    def available(self) -> bool:
        return self._client.connected and self.raw is not None

    async def send(self, value: Any) -> None:
        try:
            await self._client.command({self._cid: value})
        except IhCommandError as err:
            raise HomeAssistantError(_REFUSALS.get(err.err, f"The unit refused: {err.err}")) from err
        except IhError as err:
            raise HomeAssistantError(f"Cannot reach the iHomeegy unit: {err}") from err
