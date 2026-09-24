"""Tests des capteurs : valeurs, unités, device classes et attributs."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.sensor import (
    ATTR_STATE_CLASS,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_UNIT_OF_MEASUREMENT,
    UnitOfVolume,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eau_du_pic.const import (
    CONF_AUTOLOGIN,
    CONF_LOGIN,
    CONF_PASSWORD,
    DOMAIN,
)
from custom_components.eau_du_pic.data import Contrat, TeleindexPoint
from custom_components.eau_du_pic.sensor import SENSOR_DESCRIPTIONS
from tests.conftest import TEST_LOGIN, TEST_PASSWORD, TEST_TOKEN


async def _setup_integration(hass, teleindex_return=None):
    """Ajoute une entry configurée et la fait démarrer avec un client mocké."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_LOGIN,
        data={
            CONF_LOGIN: TEST_LOGIN,
            CONF_PASSWORD: TEST_PASSWORD,
            CONF_AUTOLOGIN: TEST_TOKEN,
        },
    )
    entry.add_to_hass(hass)

    if teleindex_return is None:
        teleindex_return = (
            [
                TeleindexPoint(
                    dateni=datetime(2026, 9, 17, 1, 0, 0),
                    index_l=159874,
                    conso_l=817,
                    numserie="AB01CD***123",
                    estimated=False,
                )
            ],
            2,
        )

    def make_client(*args, **kwargs):
        client = MagicMock()
        client.async_get_contrats = AsyncMock(
            return_value=[Contrat("12345", "340000001")]
        )
        client.async_get_teleindex = AsyncMock(return_value=teleindex_return)
        return client

    with patch(
        "custom_components.eau_du_pic.EauDuPicApiClient", side_effect=make_client
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    return entry


def _entity_id_for(hass, entry, suffix: str) -> str | None:
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    return registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_12345_{suffix}"
    )


async def test_two_sensors_per_contract(hass):
    entry = await _setup_integration(hass)

    assert _entity_id_for(hass, entry, "index") is not None
    assert _entity_id_for(hass, entry, "conso_hier") is not None


async def test_index_sensor_state_and_metadata(hass):
    entry = await _setup_integration(hass)
    entity_id = _entity_id_for(hass, entry, "index")
    state = hass.states.get(entity_id)

    assert state is not None
    assert float(state.state) == 159.874
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UnitOfVolume.CUBIC_METERS
    assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.WATER
    assert state.attributes[ATTR_STATE_CLASS] == SensorStateClass.TOTAL_INCREASING


async def test_conso_sensor_state_and_metadata(hass):
    entry = await _setup_integration(hass)
    entity_id = _entity_id_for(hass, entry, "conso_hier")
    state = hass.states.get(entity_id)

    assert state is not None
    assert float(state.state) == 817
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UnitOfVolume.LITERS
    assert state.attributes[ATTR_DEVICE_CLASS] == SensorDeviceClass.WATER
    assert state.attributes[ATTR_STATE_CLASS] == SensorStateClass.TOTAL


async def test_diagnostic_attributes(hass):
    entry = await _setup_integration(hass)
    state = hass.states.get(_entity_id_for(hass, entry, "index"))

    assert state.attributes["numserie"] == "AB01CD***123"
    assert state.attributes["numcontrat"] == "340000001"
    assert state.attributes["dateni"] == "2026-09-17T01:00:00"
    assert state.attributes["jours_completes"] == 2
    assert state.attributes["estimated_consumption"] is False


async def test_sensors_unknown_without_real_point(hass):
    entry = await _setup_integration(hass, teleindex_return=([], 7))

    state_index = hass.states.get(_entity_id_for(hass, entry, "index"))
    state_conso = hass.states.get(_entity_id_for(hass, entry, "conso_hier"))

    assert state_index.state == "unknown"
    assert state_conso.state == "unknown"
    assert state_index.attributes["jours_completes"] == 7


def test_sensor_descriptions_are_coherent():
    """Index en m³ total_increasing, conso en L total, les deux en WATER."""
    index, conso = SENSOR_DESCRIPTIONS

    assert index.native_unit_of_measurement == UnitOfVolume.CUBIC_METERS
    assert index.state_class == SensorStateClass.TOTAL_INCREASING
    assert index.device_class == SensorDeviceClass.WATER
    assert conso.native_unit_of_measurement == UnitOfVolume.LITERS
    assert conso.state_class == SensorStateClass.TOTAL
    assert conso.device_class == SensorDeviceClass.WATER
