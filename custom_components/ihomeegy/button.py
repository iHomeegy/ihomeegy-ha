"""Pulse cards (e.g. a gate)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhButton(client, entry.entry_id, c) for c in cards_of(client, "button"))


class IhButton(IhEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        return self._client.connected  # a pulse card has no state

    async def async_press(self) -> None:
        await self.send("press")
