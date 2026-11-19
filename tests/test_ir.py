"""Universal IR unit inside Home Assistant: TVs -> media player, air conditioners -> climate, other remotes skipped.
Runs against the REAL firmware built for the PC as a Universal IR unit (IH_PRODUCT_UIR); skipped when it is not there."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import random
import secrets
import shutil
import subprocess
import sys
import time
import zlib
from datetime import timedelta

import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.ihomeegy.const import DOMAIN

BIN = "/home/claude/w/t/fw_unit_ir_0137"
PORT = 8890
OUT = "/tmp/ha_ir_out.txt"
pytestmark = [
    pytest.mark.skipif(not os.path.exists(BIN), reason="needs the PC build of the Universal IR firmware"),
    pytest.mark.enable_socket,
]

sys.path.insert(0, "/home/claude/w/fw/tools")
sys.path.insert(0, "/home/claude/w/t")
sys.path.insert(0, os.path.dirname(__file__))
from test_with_firmware import Owner, _wait  # noqa: E402


def pulses(key: str) -> list[int]:
    rnd = random.Random(zlib.crc32(key.encode()))
    return [9000, 4500] + [rnd.choice([560, 1690]) if i % 2 else 560 for i in range(64)] + [560]


def sent() -> list[list[int]]:
    if not os.path.exists(OUT):
        return []
    return [list(map(int, ln.split()))[1:] for ln in open(OUT).read().split("\n") if ln.strip()]


def near(a: list[int], b: list[int]) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= max(60, y * 0.13) for x, y in zip(a, b))


def was_sent(key: str, back: int = 1) -> bool:
    s = sent()
    return len(s) >= back and near(s[-back], pulses(key))


TV_KEYS = ["power", "vol_up", "vol_down", "mute", "ch_up", "ch_down", "src_hdmi1", "src_tv"] + [f"ch_{d}" for d in range(10)]
AC_KEYS = ["off"] + [f"{m}/{f}/{t}" for m in ("cool", "heat") for f in ("auto", "low", "high") for t in range(18, 31)] + [
    "dry/auto/24", "cool/auto/24/on"]


def put_remote(o: Owner, name: str, kind: str, keys: list[str]) -> int:
    import irc  # noqa: PLC0415

    txt = "".join(f"{k}\t{irc.b64(irc.encode(pulses(k)))}\n" for k in keys)
    a = o.req({"t": "ir_put", "id": 0, "n": name, "k": kind, "m": "x/1", "size": len(txt),
               "sha": hashlib.sha256(txt.encode()).hexdigest()})
    assert a["ok"], a
    rid = a["id"]
    for off in range(0, len(txt), 900):
        assert o.req({"t": "ir_data", "id": rid, "off": off, "d": txt[off:off + 900]})["ok"]
    assert o.req({"t": "ir_end", "id": rid})["ok"]
    return rid


@pytest.fixture(autouse=True)
def _local_sockets():
    import pytest_socket  # noqa: PLC0415

    pytest_socket.enable_socket()
    yield


@pytest.fixture(scope="module")
def ir_unit():
    import pytest_socket  # noqa: PLC0415

    pytest_socket.enable_socket()
    import provision as P  # noqa: PLC0415
    import lictest  # noqa: PLC0415

    fs = "/tmp/fs_ha_ir_pytest"
    shutil.rmtree(fs, ignore_errors=True)
    os.makedirs(fs)
    if os.path.exists(OUT):
        os.remove(OUT)
    env = dict(os.environ, IH_NO_NTP="1", IH_FS_DIR=fs, IH_IR_OUT=OUT, IH_DHT="23.4 45")
    os.environ.update(IH_NO_NTP="1", IH_FS_DIR=fs)
    subprocess.run(["pkill", "-f", "fw_unit"], check=False)
    time.sleep(0.5)
    lk = P.ProcLink(BIN)
    dev_id = secrets.token_hex(8)
    label = secrets.token_bytes(32)
    lictest.provision(lk, dev_id, label)
    time.sleep(1)
    lk.p.kill()
    lk.p.wait()
    log = open("/tmp/fw_ha_ir_pytest.log", "ab")
    proc = subprocess.Popen([BIN], stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, env=env)
    time.sleep(1.5)
    o = Owner(label)
    home = secrets.token_bytes(32)
    o.send({"t": "pair", "key": home.hex()})
    for _ in range(20):
        if o.msg().get("t") == "pair_ok":
            break
    o.close()
    time.sleep(0.3)
    o = Owner(home)
    o.req({"t": "mem_set", "s": 0, "n": "Hossam", "mid": "own00001"})
    tv = put_remote(o, "Living room TV", "tv", TV_KEYS)
    ac = put_remote(o, "Bedroom A/C", "ac", AC_KEYS)
    fan = put_remote(o, "Ceiling fan", "fan", ["power", "speed/low"])
    o.close()
    yield dev_id, home, tv, ac, fan
    proc.kill()
    proc.wait()


def invite(dev_id: str, home: bytes, cards: list[str]) -> str:
    o = Owner(home)
    k = secrets.token_bytes(32)
    a = o.req({"t": "mem_add", "n": "Home Assistant", "mid": "hass0001", "r": "member", "cards": cards, "auto": 0, "key": k.hex()})
    o.close()
    assert a["ok"], a
    j = {"v": 1, "k": k.hex(), "m": "hass0001", "n": "Home Assistant", "b": "Hossam",
         "u": [{"i": dev_id, "n": "UIR", "h": "127.0.0.1", "p": PORT}]}
    return "ihome://join?d=" + base64.urlsafe_b64encode(json.dumps(j).encode()).decode().rstrip("=")


def owner_req(home: bytes, d: dict) -> dict:
    o = Owner(home)
    r = o.req(d)
    o.close()
    return r


async def test_ir_tv_and_ac(hass: HomeAssistant, ir_unit) -> None:
    dev_id, home, tv, ac, fan = ir_unit
    code = await hass.async_add_executor_job(invite, dev_id, home, ["ir1", "temp1"])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"invite": code})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    entry = result["result"]
    await hass.async_block_till_done()
    reg = er.async_get(hass)

    def ids() -> dict[str, str]:
        return {e.unique_id.split("_", 1)[1]: e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}

    print("\nIR ENTITIES", json.dumps(ids(), indent=1))
    e = ids()
    assert e[f"ir1_tv{tv}"].startswith("media_player.") and e[f"ir1_ac{ac}"].startswith("climate.")
    assert f"ir1_fan{fan}" not in e and not [k for k in e if k.startswith("ir1_") and k.endswith(str(fan))], e
    st = lambda k: hass.states.get(ids()[k])  # noqa: E731
    A, T = f"ir1_ac{ac}", f"ir1_tv{tv}"

    # ---- the A/C
    a = st(A)
    print("AC", a.state, a.attributes)
    assert a.attributes["friendly_name"].endswith("Bedroom A/C")
    assert set(a.attributes["hvac_modes"]) == {"off", "cool", "heat", "dry"}
    assert set(a.attributes["fan_modes"]) == {"auto", "low", "high"}
    assert a.attributes["min_temp"] == 18 and a.attributes["max_temp"] == 30
    # the room temperature (the unit's own sensor, read a few seconds after it starts)
    assert await _wait(hass, lambda: st(A).attributes.get("current_temperature") == 23.4, 30)
    call = lambda svc, **kw: hass.services.async_call("climate", svc, {"entity_id": ids()[A], **kw}, blocking=True)  # noqa: E731
    await call("set_hvac_mode", hvac_mode="cool")
    assert await _wait(hass, lambda: st(A).state == "cool") and was_sent("cool/auto/24")
    await call("set_temperature", temperature=21)
    assert await _wait(hass, lambda: st(A).attributes.get("temperature") == 21) and was_sent("cool/auto/21")
    await call("set_fan_mode", fan_mode="high")
    assert await _wait(hass, lambda: st(A).attributes.get("fan_mode") == "high") and was_sent("cool/high/21")
    await call("set_hvac_mode", hvac_mode="dry")  # the remote has dry only with auto / 24: that one
    assert await _wait(hass, lambda: st(A).state == "dry" and st(A).attributes.get("temperature") == 24)
    assert was_sent("dry/auto/24")
    await call("set_hvac_mode", hvac_mode="heat")
    assert await _wait(hass, lambda: st(A).state == "heat") and was_sent("heat/auto/24")
    n = len(sent())
    await call("turn_off")
    assert await _wait(hass, lambda: st(A).state == "off") and was_sent("off") and len(sent()) == n + 1
    await call("set_temperature", temperature=26)  # while off: kept, nothing sent
    await hass.async_block_till_done()
    assert len(sent()) == n + 1 and st(A).attributes.get("temperature") == 26
    await call("turn_on")
    assert await _wait(hass, lambda: st(A).state == "heat") and was_sent("heat/auto/26")
    # the owner changes the A/C from the app: Home Assistant follows
    await hass.async_add_executor_job(owner_req, home, {"t": "cmd", "set": {"ir1": {"r": ac, "ac": {"m": "cool", "f": "low", "t": 19}}}})
    assert await _wait(hass, lambda: st(A).state == "cool" and st(A).attributes.get("temperature") == 19
                       and st(A).attributes.get("fan_mode") == "low")

    # ---- the TV
    t = st(T)
    assert t.state == "off"  # a new TV starts "off" (an "unknown" one shows no controls in Home Assistant)
    print("TV", t.state, t.attributes)
    assert t.attributes["source_list"] == ["HDMI 1", "TV"]
    mp = lambda svc, **kw: hass.services.async_call("media_player", svc, {"entity_id": ids()[T], **kw}, blocking=True)  # noqa: E731
    await mp("turn_on")
    assert await _wait(hass, lambda: st(T).state == "on") and was_sent("power")
    await mp("volume_up")
    assert was_sent("vol_up")
    await mp("volume_mute", is_volume_muted=True)
    assert was_sent("mute") and st(T).attributes.get("is_volume_muted") is True
    await mp("media_next_track")
    assert was_sent("ch_up")
    await mp("select_source", source="HDMI 1")
    assert was_sent("src_hdmi1")
    n = len(sent())
    await mp("play_media", media_content_type="channel", media_content_id="105")
    assert len(sent()) == n + 3 and was_sent("ch_1", 3) and was_sent("ch_0", 2) and was_sent("ch_5", 1)
    await mp("turn_off")
    assert await _wait(hass, lambda: st(T).state == "off") and was_sent("power")

    # ---- a remote added / deleted in the app: Home Assistant follows (its periodic check)
    def add_and_delete() -> int:
        o = Owner(home)
        new = put_remote(o, "Office A/C", "ac", ["off", "cool/auto/24"])
        assert o.req({"t": "ir_del", "id": tv})["ok"]
        o.close()
        return new

    new = await hass.async_add_executor_job(add_and_delete)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    ok = False
    for _ in range(100):
        await hass.async_block_till_done()
        e = ids()
        if f"ir1_ac{new}" in e and entry.state is config_entries.ConfigEntryState.LOADED and hass.states.get(e[f"ir1_ac{new}"]):
            ok = True
            break
        await asyncio.sleep(0.1)
    assert ok, ids()
    await hass.async_block_till_done()
    assert hass.states.get(ids()[f"ir1_ac{new}"]).attributes["friendly_name"].endswith("Office A/C")
    # the deleted TV: its entity is gone
    assert T not in ids() and A in ids(), ids()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
