"""Tests du config flow : ajout initial, doublon, erreurs, re-authentification."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import slugify
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eau_du_pic.api import (
    EauDuPicApiClientAuthenticationError,
    EauDuPicApiClientCommunicationError,
)
from custom_components.eau_du_pic.const import (
    CONF_AUTOLOGIN,
    CONF_LOGIN,
    CONF_PASSWORD,
    DOMAIN,
)
from custom_components.eau_du_pic.data import Contrat
from tests.conftest import TEST_LOGIN, TEST_PASSWORD, TEST_TOKEN

FLOW_INPUT = {CONF_LOGIN: TEST_LOGIN, CONF_PASSWORD: TEST_PASSWORD}


def _patch_flow_client(token: str | None = TEST_TOKEN, error: Exception | None = None):
    """Patche le client utilisé par le config flow (validation par signin)."""
    client = MagicMock()
    if error is not None:
        client.async_signin = AsyncMock(side_effect=error)
    else:
        client.async_signin = AsyncMock(return_value=token)
    return patch(
        "custom_components.eau_du_pic.config_flow.EauDuPicApiClient",
        return_value=client,
    )


def _patch_setup_client():
    """Patche le client utilisé par async_setup_entry (collecte de données)."""
    client = MagicMock()
    client.async_get_contrats = AsyncMock(return_value=[Contrat("12345", "340000001")])
    client.async_get_teleindex = AsyncMock(return_value=([], 0))
    return patch("custom_components.eau_du_pic.EauDuPicApiClient", return_value=client)


async def test_user_form_is_shown(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_user_flow_creates_entry(hass):
    with (
        _patch_flow_client() as flow_patch,
        _patch_setup_client() as setup_patch,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], FLOW_INPUT
        )
        await hass.async_block_till_done()

    assert flow_patch.called
    assert setup_patch.called
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Eau du Pic ({TEST_LOGIN})"
    assert result["data"][CONF_LOGIN] == TEST_LOGIN
    assert result["data"][CONF_PASSWORD] == TEST_PASSWORD
    assert result["data"][CONF_AUTOLOGIN] == TEST_TOKEN


async def test_user_flow_rejects_bad_credentials(hass):
    with _patch_flow_client(error=EauDuPicApiClientAuthenticationError("401")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], FLOW_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_reports_connection_error(hass):
    with _patch_flow_client(error=EauDuPicApiClientCommunicationError("timeout")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], FLOW_INPUT
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_aborts_on_duplicate_account(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        # Le config flow pose unique_id = slugify(login) : « marc.dupont » → « marc_dupont ».
        unique_id=slugify(TEST_LOGIN),
        data={CONF_LOGIN: TEST_LOGIN, CONF_PASSWORD: TEST_PASSWORD, CONF_AUTOLOGIN: TEST_TOKEN},
    )
    entry.add_to_hass(hass)

    with _patch_flow_client():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], FLOW_INPUT
        )

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_updates_entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_LOGIN,
        data={CONF_LOGIN: TEST_LOGIN, CONF_PASSWORD: "old", CONF_AUTOLOGIN: "old" * 8},
    )
    entry.add_to_hass(hass)

    with (
        _patch_flow_client(token="f" * 64) as flow_patch,
        _patch_setup_client() as setup_patch,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
                "title_placeholders": {CONF_LOGIN: TEST_LOGIN},
            },
            data=entry.data,
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new"}
        )
        await hass.async_block_till_done()

    assert flow_patch.called
    assert setup_patch.called
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "new"
    assert entry.data[CONF_AUTOLOGIN] == "f" * 64


async def test_reauth_flow_rejects_bad_password(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=TEST_LOGIN,
        data={CONF_LOGIN: TEST_LOGIN, CONF_PASSWORD: "old", CONF_AUTOLOGIN: "old" * 8},
    )
    entry.add_to_hass(hass)

    with _patch_flow_client(error=EauDuPicApiClientAuthenticationError("401")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
                "title_placeholders": {CONF_LOGIN: TEST_LOGIN},
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "wrong"}
        )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
