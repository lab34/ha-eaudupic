"""Intégration Eau du Pic : télérelève du compteur d'eau (portail iClients)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EauDuPicApiClient
from .const import CONF_LOGIN, CONF_PASSWORD, PLATFORMS
from .coordinator import EauDuPicCoordinator
from .data import EauDuPicConfigEntry


async def async_setup_entry(hass: HomeAssistant, entry: EauDuPicConfigEntry) -> bool:
    """Crée le client API, fait la première collecte puis expose les capteurs."""
    client = EauDuPicApiClient(
        login=entry.data[CONF_LOGIN],
        password=entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )
    coordinator = EauDuPicCoordinator(hass, entry, client)

    # Lève ConfigEntryAuthFailed si les identifiants sont refusés dès l'installation :
    # Home Assistant affiche alors la carte de re-authentification.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: EauDuPicConfigEntry) -> bool:
    """Décharge les plateformes lors du retrait/rechargement de l'intégration."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
