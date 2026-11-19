"""The TVs kept in a Universal IR unit (a remote made in the iHomeegy app, from the library or learned).

A TV never answers an IR remote, so on / off is what Home Assistant last sent (kept across restarts), as on every
universal remote. Only the buttons the remote really has are offered.
"""

from __future__ import annotations

import re
from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import IhConfigEntry
from .entity import IhEntity
from .ir import ir_card

_CH_DIGITS = 4  # one command carries at most 4 codes (the unit's limit)


async def async_setup_entry(hass: HomeAssistant, entry: IhConfigEntry, add: AddEntitiesCallback) -> None:
    client = entry.runtime_data
    card = ir_card(client)
    if card is None:
        return
    add(IhIrTv(client, entry.entry_id, card, r) for r in client.ir.values() if r["k"] == "tv")


def _source_name(key: str) -> str:
    """'src_hdmi1' -> 'HDMI 1'."""
    s = key[4:].replace("_", " ").upper()
    return re.sub(r"([A-Z])(\d)", r"\1 \2", s)


class IhIrTv(IhEntity, MediaPlayerEntity, RestoreEntity):
    """One TV remote of the unit's Universal IR card."""

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_assumed_state = True

    def __init__(self, client: Any, entry_id: str, card: dict[str, Any], remote: dict[str, Any]) -> None:
        self._rid: int = remote["id"]
        super().__init__(client, entry_id, card, suffix=f"_tv{self._rid}")
        self._keys: set[str] = {k for k in remote.get("keys", []) if isinstance(k, str)}
        self._sources = {_source_name(k): k for k in sorted(self._keys) if k.startswith("src_") and len(k) > 4}
        feats = MediaPlayerEntityFeature(0)
        if self._keys & {"power", "on"}:
            feats |= MediaPlayerEntityFeature.TURN_ON
        if self._keys & {"power", "off"}:
            feats |= MediaPlayerEntityFeature.TURN_OFF
        if self._keys & {"vol_up", "vol_down"}:
            feats |= MediaPlayerEntityFeature.VOLUME_STEP
        if "mute" in self._keys:
            feats |= MediaPlayerEntityFeature.VOLUME_MUTE
        if "ch_up" in self._keys:
            feats |= MediaPlayerEntityFeature.NEXT_TRACK
        if "ch_down" in self._keys:
            feats |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        if all(f"ch_{d}" in self._keys for d in range(10)):
            feats |= MediaPlayerEntityFeature.PLAY_MEDIA  # a channel number: its digits one after the other
        if self._sources:
            feats |= MediaPlayerEntityFeature.SELECT_SOURCE
            self._attr_source_list = list(self._sources)
        self._attr_supported_features = feats
        self._on: bool | None = None
        self._muted: bool | None = None
        self._seen_last: str | None = None
        self._update_name()

    def _update_name(self) -> None:
        rem = self._client.ir.get(self._rid)
        if rem:
            self._attr_name = rem["n"]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        old = await self.async_get_last_state()
        if old is not None and old.state in (MediaPlayerState.ON, MediaPlayerState.OFF):
            self._on = old.state == MediaPlayerState.ON
        self._seen_last = self._last()

    def _last(self) -> str | None:
        last = self.obj.get("last")
        v = last.get(str(self._rid)) if isinstance(last, dict) else None
        return v if isinstance(v, str) else None

    @callback
    def _on_update(self) -> None:
        # a button sent by the app / a scene: "on" / "off" say it, any other button but "power" means the TV is on
        last = self._last()
        if last != self._seen_last:
            self._seen_last = last
            if last == "off":
                self._on = False
            elif last and last != "power":
                self._on = True
        super()._on_update()

    @property
    def available(self) -> bool:
        return super().available and self._rid in self._client.ir

    @property
    def state(self) -> MediaPlayerState | None:
        if self._on is None:
            return None
        return MediaPlayerState.ON if self._on else MediaPlayerState.OFF

    @property
    def is_volume_muted(self) -> bool | None:
        return self._muted

    async def _press(self, *keys: str) -> None:
        if len(keys) == 1:
            await self.send({"r": self._rid, "k": keys[0]})
        else:
            await self.send([{"r": self._rid, "k": k} for k in keys])
        self._seen_last = keys[-1]

    async def async_turn_on(self) -> None:
        await self._press("on" if "on" in self._keys else "power")
        self._on = True
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        await self._press("off" if "off" in self._keys else "power")
        self._on = False
        self.async_write_ha_state()

    async def _button(self, key: str) -> None:
        if key not in self._keys:
            raise HomeAssistantError("This TV remote has no such button")
        await self._press(key)
        self._on = True
        self.async_write_ha_state()

    async def async_volume_up(self) -> None:
        await self._button("vol_up")

    async def async_volume_down(self) -> None:
        await self._button("vol_down")

    async def async_mute_volume(self, mute: bool) -> None:
        await self._button("mute")  # one button switches the sound off and on again
        self._muted = mute
        self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        await self._button("ch_up")

    async def async_media_previous_track(self) -> None:
        await self._button("ch_down")

    async def async_select_source(self, source: str) -> None:
        key = self._sources.get(source)
        if key is None:
            raise HomeAssistantError(f"Unknown source: {source}")
        await self._button(key)

    async def async_play_media(self, media_type: MediaType | str, media_id: str, **kwargs: Any) -> None:
        digits = str(media_id).strip()
        if media_type not in (MediaType.CHANNEL, "channel") or not digits.isdigit() or len(digits) > _CH_DIGITS:
            raise HomeAssistantError("Give a channel number (media type 'channel', up to 4 digits)")
        await self._press(*(f"ch_{d}" for d in digits))
        self._on = True
        self.async_write_ha_state()
