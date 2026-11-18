"""The siren card."""

from __future__ import annotations

from typing import Any

from homeassistant.components.siren import SirenEntity, SirenEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhSiren(client, entry.entry_id, c) for c in cards_of(client, "siren"))


class IhSiren(IhEntity, SirenEntity):
    _attr_supported_features = SirenEntityFeature.TURN_ON | SirenEntityFeature.TURN_OFF

    @property
    def is_on(self) -> bool | None:
        v = self.raw
        if isinstance(v, dict):
            v = v.get("on")
        return None if v is None else bool(v)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.send(1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send(0)
