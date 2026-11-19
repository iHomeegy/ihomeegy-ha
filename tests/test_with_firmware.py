"""End to end inside Home Assistant: the config flow, the entities and the services, against the REAL unit firmware
built for the PC (t/full/b/fw_unit). Skipped when that build is not there (it is not part of this repository)."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import time

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.ihomeegy.const import DOMAIN

BIN = "/home/claude/w/t/full/b/fw_unit"
PORT = 8890
pytestmark = [
    pytest.mark.skipif(not os.path.exists(BIN), reason="needs the PC build of the unit firmware"),
    pytest.mark.enable_socket,
]

sys.path.insert(0, "/home/claude/w/fw/tools")
sys.path.insert(0, "/home/claude/w/t")


class Owner:
    """The owner's phone, the way the app talks (blocking test helper)."""

    def __init__(self, psk: bytes) -> None:
        import noise_client_lib as N  # noqa: PLC0415

        for _ in range(40):
            try:
                self.c = N.SockConn("127.0.0.1", PORT)
                break
            except ConnectionRefusedError:
                time.sleep(0.25)
        self.c.s.settimeout(5)
        self.s = N.Session(self.c, psk=psk)
        self.s.handshake()
        self.seq = 100
        self.msg()

    def send(self, d: dict) -> None:
        self.s.send(json.dumps(d).encode())

    def msg(self, t: float = 5) -> dict:
        self.c.s.settimeout(t)
        return json.loads(self.s.recv())

    def req(self, d: dict) -> dict:
        self.seq += 1
        d = {**d, "seq": self.seq}
        self.send(d)
        for _ in range(60):
            m = self.msg(6)
            if m.get("t") == "ping":
                self.send({"t": "pong"})
            if m.get("seq") == self.seq:
                return m
        raise RuntimeError("no reply")

    def close(self) -> None:
        self.c.close()


@pytest.fixture(autouse=True)
def _local_sockets():
    """The unit runs on this machine: allow sockets (Home Assistant's test plugin blocks them)."""
    import pytest_socket  # noqa: PLC0415

    pytest_socket.enable_socket()
    yield


@pytest.fixture(scope="module")
def unit():
    """A provisioned, licensed, paired unit with an owner. Yields (unit id, home key)."""
    import pytest_socket  # noqa: PLC0415

    pytest_socket.enable_socket()
    import provision as P  # noqa: PLC0415
    import lictest  # noqa: PLC0415

    fs = "/tmp/fs_ha_pytest"
    shutil.rmtree(fs, ignore_errors=True)
    os.makedirs(fs)
    os.environ["IH_NO_NTP"] = "1"
    os.environ["IH_FS_DIR"] = fs
    subprocess.run(["pkill", "-f", BIN], check=False)
    time.sleep(0.5)
    lk = P.ProcLink(BIN)
    dev_id = secrets.token_hex(8)
    label = secrets.token_bytes(32)
    lictest.provision(lk, dev_id, label)
    time.sleep(1)
    lk.p.kill()
    lk.p.wait()
    log = open("/tmp/fw_ha_pytest.log", "ab")
    proc = subprocess.Popen([BIN], stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ))
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
    o.close()
    yield dev_id, home
    proc.kill()
    proc.wait()


def make_invite(dev_id: str, home: bytes, cards: list[str], host: str = "127.0.0.1") -> str:
    o = Owner(home)
    k = secrets.token_bytes(32)
    a = o.req({"t": "mem_add", "n": "Home Assistant", "mid": "hass0001", "r": "member", "cards": cards, "auto": 0, "key": k.hex()})
    o.close()
    assert a["ok"], a
    j = {"v": 1, "k": k.hex(), "m": "hass0001", "n": "Home Assistant", "b": "Hossam",
         "u": [{"i": dev_id, "n": "Test unit", "h": host, "p": PORT}]}
    return "ihome://join?d=" + base64.urlsafe_b64encode(json.dumps(j).encode()).decode().rstrip("=")


def owner_cmd(home: bytes, values: dict) -> None:
    o = Owner(home)
    r = o.req({"t": "cmd", "set": values})
    o.close()
    assert r.get("ok"), r


async def _wait(hass: HomeAssistant, pred, t: float = 6.0) -> bool:
    end = time.monotonic() + t
    while time.monotonic() < end:
        await hass.async_block_till_done()
        if pred():
            return True
        await asyncio.sleep(0.1)
    return False


CARDS = ["r3", "r4", "cov1", "dim1", "fan1", "valve1", "lock1", "btn1", "clim1", "temp1", "siren1", "num1", "sel1", "in1"]


async def test_flow_entities_and_control(hass: HomeAssistant, unit) -> None:
    dev_id, home = unit

    # a code that is not an invite
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"invite": "hello"})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"invite": "invalid_invite"}

    # the real invite
    code = await hass.async_add_executor_job(make_invite, dev_id, home, CARDS)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"invite": code})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert result["data"]["unit_id"] == dev_id and len(result["data"]["key"]) == 64
    entry = result["result"]
    await hass.async_block_till_done()
    assert entry.state is config_entries.ConfigEntryState.LOADED

    # the same invite again: dead
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"invite": code})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"

    reg = er.async_get(hass)
    ids = {e.unique_id.split("_", 1)[1]: e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    print("\nENTITIES", json.dumps(ids, indent=1))
    for c in CARDS + ["hum1"]:
        assert c in ids, f"{c} missing"
    assert "r5" not in ids  # not given to Home Assistant
    domains = {c: ids[c].split(".")[0] for c in CARDS}
    assert domains == {
        "r3": "switch", "r4": "switch", "cov1": "cover", "dim1": "light", "fan1": "fan", "valve1": "valve",
        "lock1": "lock", "btn1": "button", "clim1": "climate", "temp1": "sensor", "siren1": "siren",
        "num1": "number", "sel1": "select", "in1": "binary_sensor",
    }, domains

    st = lambda c: hass.states.get(ids[c])  # noqa: E731

    # switch
    await hass.services.async_call("switch", "turn_on", {"entity_id": ids["r3"]}, blocking=True)
    assert await _wait(hass, lambda: st("r3").state == "on")
    await hass.services.async_call("switch", "turn_off", {"entity_id": ids["r3"]}, blocking=True)
    assert await _wait(hass, lambda: st("r3").state == "off")
    # light: brightness 50% of 255
    await hass.services.async_call("light", "turn_on", {"entity_id": ids["dim1"], "brightness": 128}, blocking=True)
    assert await _wait(hass, lambda: st("dim1").state == "on" and st("dim1").attributes.get("brightness") in (128, 130))
    await hass.services.async_call("light", "turn_off", {"entity_id": ids["dim1"]}, blocking=True)
    assert await _wait(hass, lambda: st("dim1").state == "off")
    # fan
    await hass.services.async_call("fan", "set_percentage", {"entity_id": ids["fan1"], "percentage": 66}, blocking=True)
    assert await _wait(hass, lambda: st("fan1").state == "on"), st("fan1")
    print("FAN", st("fan1").attributes)
    # valve
    await hass.services.async_call("valve", "open_valve", {"entity_id": ids["valve1"]}, blocking=True)
    assert await _wait(hass, lambda: st("valve1").state in ("opening", "open"), 8), st("valve1")
    # lock
    await hass.services.async_call("lock", "lock", {"entity_id": ids["lock1"]}, blocking=True)
    assert await _wait(hass, lambda: st("lock1").state == "locked")
    # climate
    await hass.services.async_call("climate", "set_hvac_mode", {"entity_id": ids["clim1"], "hvac_mode": "cool"}, blocking=True)
    await hass.services.async_call("climate", "set_temperature", {"entity_id": ids["clim1"], "temperature": 23}, blocking=True)
    assert await _wait(hass, lambda: st("clim1").state == "cool" and st("clim1").attributes.get("temperature") == 23)
    # number / select / button / siren
    await hass.services.async_call("number", "set_value", {"entity_id": ids["num1"], "value": 20}, blocking=True)
    assert await _wait(hass, lambda: float(st("num1").state) == 20)
    await hass.services.async_call("select", "select_option", {"entity_id": ids["sel1"], "option": "Away"}, blocking=True)
    assert await _wait(hass, lambda: st("sel1").state == "Away")
    await hass.services.async_call("button", "press", {"entity_id": ids["btn1"]}, blocking=True)
    await hass.services.async_call("siren", "turn_on", {"entity_id": ids["siren1"]}, blocking=True)
    assert await _wait(hass, lambda: st("siren1").state == "on")
    await hass.services.async_call("siren", "turn_off", {"entity_id": ids["siren1"]}, blocking=True)
    # sensors have values
    assert await _wait(hass, lambda: st("temp1").state not in ("unknown", "unavailable"))
    print("TEMP", st("temp1").state, st("temp1").attributes)
    # the owner switches a card from the app: Home Assistant follows at once
    await hass.async_add_executor_job(owner_cmd, home, {"r4": 1})
    assert await _wait(hass, lambda: st("r4").state == "on")
    # cover entity exists and is not "unavailable"
    print("COVER", st("cov1").state, st("cov1").attributes)
    assert st("cov1").state != "unavailable"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_removed_then_reinvited(hass: HomeAssistant, unit) -> None:
    """The owner removes Home Assistant from the unit: a re-authentication asks for a new invite, which works."""
    dev_id, home = unit
    code = await hass.async_add_executor_job(make_invite, dev_id, home, ["r3"])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"invite": code})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    await hass.async_block_till_done()
    reg = er.async_get(hass)
    ents = er.async_entries_for_config_entry(reg, entry.entry_id)
    assert [e.unique_id.split("_", 1)[1] for e in ents] == ["r3"]

    def remove_ha() -> None:
        o = Owner(home)
        lst = o.req({"t": "mem_list"})
        slot = [m["s"] for m in lst["m"] if m.get("on") == 1 and m["s"] != 0][0]
        assert o.req({"t": "mem_del", "s": slot})["ok"]
        o.close()

    await hass.async_add_executor_job(remove_ha)
    flows = []
    for _ in range(60):
        await hass.async_block_till_done()
        flows = [f for f in hass.config_entries.flow.async_progress() if f["context"].get("source") == "reauth"]
        if flows:
            break
        await asyncio.sleep(0.1)
    assert flows, "no re-authentication started"
    assert hass.states.get(ents[0].entity_id).state == "unavailable"

    # an invite for another unit is refused, a new one for this unit works
    other = "ihome://join?d=" + base64.urlsafe_b64encode(json.dumps(
        {"v": 1, "k": "00" * 32, "u": [{"i": "0123456789abcdef", "n": "x", "h": "127.0.0.1", "p": PORT}]}).encode()).decode().rstrip("=")
    r = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"invite": other})
    assert r["type"] is FlowResultType.FORM and r["errors"] == {"invite": "other_unit"}
    code = await hass.async_add_executor_job(make_invite, dev_id, home, ["r3", "r4"])
    r = await hass.config_entries.flow.async_configure(flows[0]["flow_id"], {"invite": code})
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "reauth_successful", r
    await hass.async_block_till_done()
    ok = False
    for _ in range(60):
        await hass.async_block_till_done()
        ents = er.async_entries_for_config_entry(reg, entry.entry_id)
        st = hass.states.get(ents[0].entity_id) if ents else None
        if st and st.state != "unavailable" and len(ents) == 2:
            ok = True
            break
        await asyncio.sleep(0.1)
    assert ok, [(e.entity_id, hass.states.get(e.entity_id)) for e in ents]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_invite_while_the_unit_waits_in_discovered(hass: HomeAssistant, unit) -> None:
    """The unit is also in "Discovered" (zeroconf flow open): pasting an invite must still make the entry."""
    from ipaddress import ip_address  # noqa: PLC0415

    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo  # noqa: PLC0415

    dev_id, home = unit
    info = ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"), ip_addresses=[ip_address("127.0.0.1")], port=PORT, hostname="ihome.local.",
        type="_ihomenoise._tcp.local.", name=f"ihome-{dev_id}._ihomenoise._tcp.local.",
        properties={"v": "2", "id": dev_id, "p": "1"},
    )
    disc = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=info)
    assert disc["type"] is FlowResultType.FORM
    code = await hass.async_add_executor_job(make_invite, dev_id, home, ["r3"])
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"invite": code})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    assert not [f for f in hass.config_entries.flow.async_progress() if f["flow_id"] == disc["flow_id"]]
    assert await hass.config_entries.async_unload(result["result"].entry_id)
    await hass.async_block_till_done()
