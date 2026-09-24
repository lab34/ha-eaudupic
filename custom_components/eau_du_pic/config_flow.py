"""Config flow de l'intégration Eau du Pic (saisie des identifiants + reauth)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import slugify

from .api import (
    EauDuPicApiClient,
    EauDuPicApiClientAuthenticationError,
    EauDuPicApiClientCommunicationError,
)
from .const import CONF_AUTOLOGIN, CONF_LOGIN, CONF_PASSWORD, DOMAIN

_PASSWORD_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOGIN): str,
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)

STEP_REAUTH_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): _PASSWORD_SELECTOR,
    }
)


async def _async_fetch_autologin(hass: HomeAssistant, login: str, password: str) -> str:
    """Teste les identifiants en refaisant un signin et renvoie le token AutoLogin."""
    client = EauDuPicApiClient(login, password, async_get_clientsession(hass))
    return await client.async_signin()


class EauDuPicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gère l'ajout initial et la re-authentification du compte Eau du Pic."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Étape initiale : identifiant + mot de passe du portail."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token: str | None = None
            try:
                token = await _async_fetch_autologin(
                    self.hass, user_input[CONF_LOGIN], user_input[CONF_PASSWORD]
                )
            except EauDuPicApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except EauDuPicApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                # Un seul compte par installation.
                await self.async_set_unique_id(slugify(user_input[CONF_LOGIN]))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Eau du Pic ({user_input[CONF_LOGIN]})",
                    data={
                        CONF_LOGIN: user_input[CONF_LOGIN],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_AUTOLOGIN: token,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Démarre le flow de re-authentification (token expiré/mot de passe changé)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Demande le nouveau mot de passe, valide puis met à jour l'entry."""
        errors: dict[str, str] = {}
        reauth_entry = self._get_reauth_entry()
        login: str = reauth_entry.data[CONF_LOGIN]
        if user_input is not None:
            token: str | None = None
            try:
                token = await _async_fetch_autologin(
                    self.hass, login, user_input[CONF_PASSWORD]
                )
            except EauDuPicApiClientAuthenticationError:
                errors["base"] = "invalid_auth"
            except EauDuPicApiClientCommunicationError:
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data={
                        CONF_LOGIN: login,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_AUTOLOGIN: token,
                    },
                )

        self.context["title_placeholders"] = {CONF_LOGIN: login}
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            errors=errors,
            description_placeholders={CONF_LOGIN: login},
        )
