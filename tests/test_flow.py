"""Config flow parts that need no unit."""
from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ihomeegy.const import DOMAIN

UNIT = "0123456789abcdef"


def _info(uid: str, host: str, paired: str = "1") -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host), ip_addresses=[ip_address(host)], port=8890, hostname="ihome.local.",
        type="_ihomenoise._tcp.local.", name=f"ihome-{uid}._ihomenoise._tcp.local.",
        properties={"v": "2", "id": uid, "p": paired},
    )


async def test_zeroconf_updates_the_address(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id=UNIT, data={"unit_id": UNIT, "key": "11" * 32, "host": "192.168.1.5", "port": 8890, "name": "x"})
    entry.add_to_hass(hass)
    with patch("custom_components.ihomeegy.async_setup_entry", return_value=True):
        r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_info(UNIT, "192.168.1.77"))
        await hass.async_block_till_done()
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "already_configured"
    assert entry.data["host"] == "192.168.1.77"


async def test_zeroconf_new_unit_asks_for_an_invite(hass: HomeAssistant) -> None:
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_info("fedcba9876543210", "192.168.1.9"))
    assert r["type"] is FlowResultType.FORM and r["step_id"] == "user"
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_info("aaaaaaaaaaaaaaaa", "192.168.1.10", paired="0"))
    assert r["type"] is FlowResultType.ABORT and r["reason"] == "not_paired"
