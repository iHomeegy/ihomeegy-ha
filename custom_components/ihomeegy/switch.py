"""ON/OFF lines (relays) and the Energy Meter's relay."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhSwitch(client, entry.entry_id, c) for c in cards_of(client, "switch"))


class IhSwitch(IhEntity, SwitchEntity):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._attr_device_class = SwitchDeviceClass.OUTLET if self._card.get("class") == "outlet" else SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        v = self.raw
        if isinstance(v, dict):  # Energy Meter: {"on":1, "v":..., ...}
            v = v.get("on")
        return None if v is None else bool(v)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.send(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send(0)
