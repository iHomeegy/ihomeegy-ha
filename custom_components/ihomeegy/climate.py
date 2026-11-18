"""The thermostat card."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of

_MODES = {
    "off": HVACMode.OFF,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "auto": HVACMode.AUTO,
    "heat_cool": HVACMode.HEAT_COOL,
    "dry": HVACMode.DRY,
    "fan": HVACMode.FAN_ONLY,
    "fan_only": HVACMode.FAN_ONLY,
}


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhClimate(client, entry.entry_id, c) for c in cards_of(client, "climate"))


class IhClimate(IhEntity, ClimateEntity):
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._unit_modes = [m for m in (self._card.get("modes") or []) if m in _MODES]
        self._attr_hvac_modes = [_MODES[m] for m in self._unit_modes] or [HVACMode.OFF]
        self._attr_min_temp = float(self._card.get("min") or 16)
        self._attr_max_temp = float(self._card.get("max") or 30)
        self._attr_target_temperature_step = float(self._card.get("step") or 1)
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        )

    @property
    def hvac_mode(self) -> HVACMode | None:
        return _MODES.get(str(self.obj.get("mode")))

    @property
    def target_temperature(self) -> float | None:
        t = self.obj.get("target")
        return float(t) if isinstance(t, (int, float)) else None

    @property
    def current_temperature(self) -> float | None:
        t = self.obj.get("current")
        return float(t) if isinstance(t, (int, float)) else None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        for name in self._unit_modes:
            if _MODES[name] == hvac_mode:
                await self.send({"mode": name})
                return

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if ATTR_TEMPERATURE in kwargs:
            await self.send({"target": float(kwargs[ATTR_TEMPERATURE])})

    async def async_turn_on(self) -> None:
        await self.send({"on": 1})

    async def async_turn_off(self) -> None:
        await self.send({"mode": "off"})
