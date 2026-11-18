"""The shutter (roller shutter / curtain motor)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import ATTR_POSITION, CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    add(IhCover(client, entry.entry_id, c) for c in cards_of(client, "cover"))


class IhCover(IhEntity, CoverEntity):
    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        f = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        features = self._card.get("features") or []
        if "stop" in features:
            f |= CoverEntityFeature.STOP
        if "position" in features:
            f |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = f

    @property
    def current_cover_position(self) -> int | None:
        p = self.obj.get("position")  # absent until the shutter knows where it is (calibration)
        return int(p) if isinstance(p, (int, float)) else None

    @property
    def is_opening(self) -> bool:
        return self.obj.get("state") == "opening"

    @property
    def is_closing(self) -> bool:
        return self.obj.get("state") == "closing"

    @property
    def is_closed(self) -> bool | None:
        s = self.obj.get("state")
        if s == "closed":
            return True
        p = self.current_cover_position
        if p is not None:
            return p <= 0
        return None if s not in ("open",) else False

    async def async_open_cover(self, **kwargs: Any) -> None:
        await self.send("open")

    async def async_close_cover(self, **kwargs: Any) -> None:
        await self.send("close")

    async def async_stop_cover(self, **kwargs: Any) -> None:
        await self.send("stop")

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        await self.send({"position": int(kwargs[ATTR_POSITION])})
