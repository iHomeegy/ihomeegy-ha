"""Number cards (e.g. a pump timer)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of

_UNITS = {"min": UnitOfTime.MINUTES, "s": UnitOfTime.SECONDS, "h": UnitOfTime.HOURS}


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhNumber(client, entry.entry_id, c) for c in cards_of(client, "number"))


class IhNumber(IhEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._attr_native_min_value = float(self._card.get("min") or 0)
        self._attr_native_max_value = float(self._card.get("max") or 100)
        self._attr_native_step = float(self._card.get("step") or 1)
        unit = self._card.get("unit")
        self._attr_native_unit_of_measurement = _UNITS.get(unit, unit)

    @property
    def native_value(self) -> float | None:
        v = self.raw
        return float(v) if isinstance(v, (int, float)) else None

    async def async_set_native_value(self, value: float) -> None:
        await self.send(float(value))
