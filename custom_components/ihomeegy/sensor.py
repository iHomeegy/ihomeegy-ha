"""Temperature / humidity, and the Energy Meter's readings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of

_UNITS = {"°C": UnitOfTemperature.CELSIUS, "%": PERCENTAGE}
_CLASSES = {"temperature": SensorDeviceClass.TEMPERATURE, "humidity": SensorDeviceClass.HUMIDITY}


@dataclass(frozen=True)
class _Reading:
    key: str
    name: str
    unit: str | None
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    precision: int


# the Energy Meter card's state: {"on":1, "v":230.1, "a":1.234, "w":283.6, "hz":50.0, "pf":0.98, "kwh":..., ...}
_METER = (
    _Reading("w", "Power", UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT, 1),
    _Reading("v", "Voltage", UnitOfElectricPotential.VOLT, SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT, 1),
    _Reading("a", "Current", UnitOfElectricCurrent.AMPERE, SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT, 3),
    _Reading("hz", "Frequency", UnitOfFrequency.HERTZ, SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT, 1),
    _Reading("pf", "Power factor", None, SensorDeviceClass.POWER_FACTOR, SensorStateClass.MEASUREMENT, 2),
    _Reading("kwh", "Energy", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 3),
    _Reading("today", "Energy today", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING, 3),
    _Reading("temp", "Temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, 1),
)


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    ents: list[SensorEntity] = [IhSensor(client, entry.entry_id, c) for c in cards_of(client, "sensor")]
    for card in cards_of(client, "switch"):
        if card.get("em"):
            ents.extend(IhMeterSensor(client, entry.entry_id, card, r) for r in _METER)
    add(ents)


class IhSensor(IhEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._attr_device_class = _CLASSES.get(str(self._card.get("class") or ""))
        unit = self._card.get("unit")
        self._attr_native_unit_of_measurement = _UNITS.get(unit, unit)
        p = self._card.get("precision")
        if isinstance(p, int):
            self._attr_suggested_display_precision = p

    @property
    def native_value(self) -> float | None:
        v = self.raw
        return float(v) if isinstance(v, (int, float)) else None


class IhMeterSensor(IhEntity, SensorEntity):
    def __init__(self, client: Any, entry_id: str, card: dict[str, Any], reading: _Reading) -> None:
        super().__init__(client, entry_id, card, suffix=f"_{reading.key}")
        self._r = reading
        self._attr_device_class = reading.device_class
        self._attr_state_class = reading.state_class
        self._attr_native_unit_of_measurement = reading.unit
        self._attr_suggested_display_precision = reading.precision
        self._update_name()

    def _update_name(self) -> None:
        card = self._card.get("name") or self._cid
        self._attr_name = f"{card} {self._r.name.lower()}" if card else self._r.name

    @property
    def available(self) -> bool:
        return self._client.connected and isinstance(self.obj.get(self._r.key), (int, float))

    @property
    def native_value(self) -> float | None:
        v = self.obj.get(self._r.key)
        return float(v) if isinstance(v, (int, float)) else None
