"""Dimmers, DC LED dimmer channels and the RGB strip."""

from __future__ import annotations

import math
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ATTR_RGB_COLOR, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhLight(client, entry.entry_id, c) for c in cards_of(client, "light"))


class IhLight(IhEntity, LightEntity):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        features = self._card.get("features") or []
        if "color" in features:
            mode = ColorMode.RGB
        elif "brightness" in features:
            mode = ColorMode.BRIGHTNESS
        else:
            mode = ColorMode.ONOFF
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}
        self._min = int(self._card.get("min") or 1)
        self._max = int(self._card.get("max") or 100)

    @property
    def is_on(self) -> bool | None:
        v = self.raw
        if isinstance(v, dict):
            v = v.get("on")
        return None if v is None else bool(v)

    @property
    def brightness(self) -> int | None:
        b = self.obj.get("brightness")
        if not isinstance(b, (int, float)):
            return None
        return max(1, min(255, round(b * 255 / 100)))

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        c = self.obj.get("color")
        if isinstance(c, str) and len(c) == 7 and c.startswith("#"):
            try:
                return int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
            except ValueError:
                return None
        return None

    async def async_turn_on(self, **kwargs: Any) -> None:
        value: dict[str, Any] = {"on": 1}
        if ATTR_BRIGHTNESS in kwargs and self._attr_color_mode != ColorMode.ONOFF:
            pct = math.ceil(int(kwargs[ATTR_BRIGHTNESS]) * 100 / 255)
            value["brightness"] = max(self._min, min(self._max, pct))
        if ATTR_RGB_COLOR in kwargs and self._attr_color_mode == ColorMode.RGB:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            value["color"] = f"#{int(r):02X}{int(g):02X}{int(b):02X}"
        await self.send(value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.send({"on": 0})
