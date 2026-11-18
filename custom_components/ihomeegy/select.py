"""Select cards (a list of options)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhSelect(client, entry.entry_id, c) for c in cards_of(client, "select"))


class IhSelect(IhEntity, SelectEntity):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._attr_options = [str(o) for o in (self._card.get("options") or [])]

    @property
    def current_option(self) -> str | None:
        v = self.raw
        return str(v) if isinstance(v, str) and v in self._attr_options else None

    async def async_select_option(self, option: str) -> None:
        await self.send(option)
