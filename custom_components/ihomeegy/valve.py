"""Water / gas valves."""

from __future__ import annotations

from typing import Any

from homeassistant.components.valve import ValveDeviceClass, ValveEntity, ValveEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhValve(client, entry.entry_id, c) for c in cards_of(client, "valve"))


class IhValve(IhEntity, ValveEntity):
    _attr_reports_position = False
    _attr_supported_features = ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        if "gas" in str(self._card.get("name", "")).lower():
            self._attr_device_class = ValveDeviceClass.GAS
        else:
            self._attr_device_class = ValveDeviceClass.WATER

    @property
    def is_closed(self) -> bool | None:
        s = self.obj.get("state")
        if s in ("closed", "opening"):
            return True
        if s in ("open", "closing"):
            return False
        return None

    @property
    def is_opening(self) -> bool:
        return self.obj.get("state") == "opening"

    @property
    def is_closing(self) -> bool:
        return self.obj.get("state") == "closing"

    async def async_open_valve(self) -> None:
        await self.send("open")

    async def async_close_valve(self) -> None:
        await self.send("close")
