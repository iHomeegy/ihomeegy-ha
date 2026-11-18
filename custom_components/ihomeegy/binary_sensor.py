"""Inputs and the RF hub's sensors (door, window, motion, smoke, gas, water leak, ...)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of

_CLASSES = {
    "door": BinarySensorDeviceClass.DOOR,
    "window": BinarySensorDeviceClass.WINDOW,
    "garage_door": BinarySensorDeviceClass.GARAGE_DOOR,
    "opening": BinarySensorDeviceClass.OPENING,
    "motion": BinarySensorDeviceClass.MOTION,
    "occupancy": BinarySensorDeviceClass.OCCUPANCY,
    "presence": BinarySensorDeviceClass.PRESENCE,
    "smoke": BinarySensorDeviceClass.SMOKE,
    "gas": BinarySensorDeviceClass.GAS,
    "water": BinarySensorDeviceClass.MOISTURE,
    "moisture": BinarySensorDeviceClass.MOISTURE,
    "safety": BinarySensorDeviceClass.SAFETY,
    "sos": BinarySensorDeviceClass.SAFETY,
    "problem": BinarySensorDeviceClass.PROBLEM,
    "vibration": BinarySensorDeviceClass.VIBRATION,
    "power": BinarySensorDeviceClass.POWER,
}


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhBinarySensor(client, entry.entry_id, c) for c in cards_of(client, "binary_sensor"))


class IhBinarySensor(IhEntity, BinarySensorEntity):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._attr_device_class = _CLASSES.get(str(self._card.get("class") or self._card.get("htype") or ""))

    @property
    def is_on(self) -> bool | None:
        v = self.raw
        return None if v is None else bool(v)
