"""The door lock card."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhLock(client, entry.entry_id, c) for c in cards_of(client, "lock"))


class IhLock(IhEntity, LockEntity):
    @property
    def is_locked(self) -> bool | None:
        s = self.obj.get("state")
        return None if s is None else s == "locked"

    async def async_lock(self, **kwargs: Any) -> None:
        await self.send("lock")

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.send("unlock")
