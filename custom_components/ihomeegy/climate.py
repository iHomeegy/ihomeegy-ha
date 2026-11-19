"""The thermostat card, and the air conditioners kept in a Universal IR unit."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature, HVACMode
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import IhConfigEntry
from .entity import IhEntity, cards_of
from .ir import ir_card, parse_ac

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
    ents: list[ClimateEntity] = [IhClimate(client, entry.entry_id, c) for c in cards_of(client, "climate")]
    card = ir_card(client)
    if card is not None:
        ents.extend(IhIrAc(client, entry.entry_id, card, r) for r in client.ir.values() if r["k"] == "ac")
    add(ents)


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


# ---- an air conditioner kept in a Universal IR unit -----------------------------------------------------------------
# Its buttons are "off" and "<mode>/<fan>/<temp>[/<swing>]" (as the iHomeegy library writes them): the unit picks the
# code of the whole setting. An A/C never answers, so what is shown is the last setting sent (by the app, a scene,
# Home Assistant...), as on every universal remote.

_FAN_TO_HA = {"mid": "medium", "highest": "top"}  # the rest keep their own name (auto, low, high, quiet, turbo...)
_SWING_TO_HA = {"auto": "on", "swing": "on", "stop": "off", "fixed": "off"}


def _ha_names(names: list[str], table: dict[str, str]) -> dict[str, str]:
    """unit name -> the name shown in Home Assistant (only when that does not merge two of the remote's own names)."""
    out: dict[str, str] = {}
    for n in names:
        h = table.get(n, n)
        if h in out.values() or (h != n and h in names):
            h = n
        out[n] = h
    return out


class IhIrAc(IhEntity, ClimateEntity):
    """One A/C remote of the unit's Universal IR card."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1.0
    _attr_assumed_state = True

    def __init__(self, client: Any, entry_id: str, card: dict[str, Any], remote: dict[str, Any]) -> None:
        self._rid: int = remote["id"]
        super().__init__(client, entry_id, card, suffix=f"_ac{self._rid}")
        caps = remote.get("caps") or {}
        keys = [k for k in remote.get("keys", []) if isinstance(k, str)]
        # every setting the remote has a code for: (mode, fan, temp, swing)
        self._codes: set[tuple[str, str, int, str]] = set()
        for k in keys:
            a = parse_ac(k)
            if a:
                self._codes.add((a["m"], a["f"], a["t"], a["sw"]))
        self._has_off = "off" in keys or bool(caps.get("off"))
        modes = [m for m in (caps.get("modes") or []) if m in _MODES and m != "off"]
        if not modes:
            modes = sorted({c[0] for c in self._codes if c[0] in _MODES and c[0] != "off"})
        self._unit_modes = modes
        self._attr_hvac_modes = ([HVACMode.OFF] if self._has_off else []) + [_MODES[m] for m in modes]
        fans = [f for f in (caps.get("fans") or []) if isinstance(f, str)] or sorted({c[1] for c in self._codes})
        swings = [w for w in (caps.get("swing") or []) if isinstance(w, str)]
        self._fan_ha = _ha_names(fans, _FAN_TO_HA)
        self._swing_ha = _ha_names(swings, _SWING_TO_HA)
        self._attr_fan_modes = list(self._fan_ha.values()) or None
        self._attr_swing_modes = list(self._swing_ha.values()) or None
        temps = sorted({c[2] for c in self._codes})
        lo = caps.get("min") if isinstance(caps.get("min"), int) and caps.get("min") else (temps[0] if temps else 16)
        hi = caps.get("max") if isinstance(caps.get("max"), int) and caps.get("max") else (temps[-1] if temps else 30)
        self._attr_min_temp = float(lo)
        self._attr_max_temp = float(hi)
        feats = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON
        if self._has_off:
            feats |= ClimateEntityFeature.TURN_OFF
        if self._attr_fan_modes:
            feats |= ClimateEntityFeature.FAN_MODE
        if self._attr_swing_modes:
            feats |= ClimateEntityFeature.SWING_MODE
        self._attr_supported_features = feats
        self._room: str | None = card.get("room") if isinstance(card.get("room"), str) else None
        self._wanted: dict[str, Any] | None = None  # a setting chosen in Home Assistant while the A/C is off
        self._update_name()

    def _update_name(self) -> None:
        rem = self._client.ir.get(self._rid)
        if rem:
            self._attr_name = rem["n"]

    # -------- what the unit says --------
    def _last(self) -> str | None:
        last = self.obj.get("last")
        v = last.get(str(self._rid)) if isinstance(last, dict) else None
        return v if isinstance(v, str) else None

    def _setting(self) -> dict[str, Any] | None:
        """The A/C's setting: the last one sent, or the one it had before it was switched off."""
        a = parse_ac(self._last())
        if a:
            return a
        lon = self.obj.get("lon")
        a = parse_ac(lon.get(str(self._rid))) if isinstance(lon, dict) else None
        return self._wanted or a

    @property
    def available(self) -> bool:
        return super().available and self._rid in self._client.ir

    @property
    def hvac_mode(self) -> HVACMode | None:
        last = self._last()
        if last == "off":
            return HVACMode.OFF
        a = parse_ac(last)
        if a:
            return _MODES.get(a["m"])
        return HVACMode.OFF if self._has_off and last is None else None

    @property
    def target_temperature(self) -> float | None:
        a = self._setting()
        return float(a["t"]) if a else None

    @property
    def fan_mode(self) -> str | None:
        a = self._setting()
        return self._fan_ha.get(a["f"], a["f"]) if a else None

    @property
    def swing_mode(self) -> str | None:
        a = self._setting()
        if not a or not self._swing_ha:
            return None
        return self._swing_ha.get(a["sw"], a["sw"]) if a["sw"] else None

    @property
    def current_temperature(self) -> float | None:
        v = self._client.state.get(self._room) if self._room else None  # the unit's own temperature sensor
        return float(v) if isinstance(v, (int, float)) else None

    # -------- sending --------
    def _pick(self, want: dict[str, Any], keep: str) -> tuple[str, str, int, str]:
        """The setting the remote has a code for, closest to [want]. The mode never changes; [keep] ("f", "t" or "sw")
        stays when the remote has it in that mode."""
        target = (want["m"], want["f"], int(want["t"]), want.get("sw") or "")
        if not self._codes or target in self._codes:
            return target
        m, f, t, sw = target
        same_mode = [c for c in self._codes if c[0] == m]
        if not same_mode:
            raise HomeAssistantError("This A/C remote has no code for that setting")
        i = {"m": 0, "f": 1, "t": 2, "sw": 3}[keep]
        pool = [c for c in same_mode if c[i] == target[i]] or same_mode
        return min(pool, key=lambda c: (c[1] != f, abs(c[2] - t), c[3] != sw))

    def _base(self) -> dict[str, Any]:
        a = self._setting()
        if a and a["m"] in self._unit_modes:
            return dict(a)
        fans = list(self._fan_ha)
        temp = int(min(max(24, self._attr_min_temp), self._attr_max_temp))
        return {"m": self._unit_modes[0] if self._unit_modes else "cool", "f": "auto" if "auto" in fans else
                (fans[0] if fans else "auto"), "t": temp, "sw": ""}

    async def _send(self, want: dict[str, Any], keep: str) -> None:
        m, f, t, sw = self._pick(want, keep)
        ac: dict[str, Any] = {"m": m, "f": f, "t": t}
        if sw:
            ac["sw"] = sw
        await self.send({"r": self._rid, "ac": ac})
        self._wanted = None

    def _unit_name(self, table: dict[str, str], ha: str) -> str:
        return next((u for u, h in table.items() if h == ha), ha)

    async def _change(self, key: str, value: Any) -> None:
        want = self._base()
        want[key] = value
        if self.hvac_mode == HVACMode.OFF:
            self._wanted = want  # kept for the next "on": an IR A/C turns on with any setting it receives
            self.async_write_ha_state()
            return
        await self._send(want, key)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        mode = kwargs.get("hvac_mode")
        if ATTR_TEMPERATURE in kwargs:
            t = int(round(float(kwargs[ATTR_TEMPERATURE])))
            if mode and mode != HVACMode.OFF:
                want = self._base()
                want["t"] = t
                want["m"] = next((n for n in self._unit_modes if _MODES[n] == mode), want["m"])
                await self._send(want, "t")
                return
            await self._change("t", t)
        if mode:
            await self.async_set_hvac_mode(mode)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._change("f", self._unit_name(self._fan_ha, fan_mode))

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        await self._change("sw", self._unit_name(self._swing_ha, swing_mode))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        name = next((n for n in self._unit_modes if _MODES[n] == hvac_mode), None)
        if name is None:
            raise HomeAssistantError(f"This A/C remote has no {hvac_mode} mode")
        want = self._base()
        want["m"] = name
        await self._send(want, "m")

    async def async_turn_on(self) -> None:
        await self._send(self._base(), "m")

    async def async_turn_off(self) -> None:
        await self.send({"r": self._rid, "ac": {"m": "off"}})
