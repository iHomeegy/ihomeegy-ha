"""The fan card (speeds)."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhFan(client, entry.entry_id, c) for c in cards_of(client, "fan"))


class IhFan(IhEntity, FanEntity):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._speeds = max(1, int(self._card.get("speeds") or 1))
        f = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        if self._speeds > 1:
            f |= FanEntityFeature.SET_SPEED
        self._attr_supported_features = f
        self._attr_speed_count = self._speeds

    @property
    def is_on(self) -> bool | None:
        v = self.obj.get("on")
        return None if v is None else bool(v)

    @property
    def percentage(self) -> int | None:
        if not self.is_on:
            return 0
        s = self.obj.get("speed")
        if not isinstance(s, (int, float)):
            return None
        return round(int(s) * 100 / self._speeds)

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage <= 0:
            await self.send({"on": 0})
            return
        speed = max(1, min(self._speeds, math.ceil(percentage * self._speeds / 100)))
        await self.send({"on": 1, "speed": speed})

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any) -> None:
        if percentage:
            await self.async_set_percentage(percentage)
        else:
            await self.send({"on": 1})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send({"on": 0})
