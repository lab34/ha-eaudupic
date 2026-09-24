"""Coordinator centralisant la collecte quotidienne Eau du Pic."""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EauDuPicApiClient, EauDuPicApiClientAuthenticationError, EauDuPicApiClientError
from .const import (
    DOMAIN,
    LITERS_PER_CUBIC_METER,
    UPDATE_HOUR,
    UPDATE_JITTER_MAX_MINUTES,
    UPDATE_MINUTE,
    UPDATE_RETRY_DELAY,
    WINDOW_DAYS,
)
from .data import ContractReading, Contrat, EauDuPicConfigEntry, TeleindexPoint

LOGGER = logging.getLogger(__package__)


def window_dates(now: datetime) -> tuple[date, date]:
    """Fenêtre glissante J-7 → J (bornes inclusives) demandée à l'API.

    Interroger plusieurs jours en arrière garantit qu'aucun relevé n'est
    raté après une interruption (portail indisponible, HA éteint la nuit…),
    le dernier point réel étant ensuite sélectionné par dateni.
    """
    today = now.date()
    return today - timedelta(days=WINDOW_DAYS), today


def next_poll_interval(
    now: datetime,
    last_dateni: datetime | None,
    rng: random.Random | None = None,
) -> timedelta:
    """Prochaine collecte : 06h30 (+ jitter 0-15 min), ou 2 h si donnée en retard.

    Le relevé partenaire tombe vers 01h00 ; si, passé 06h30, le dernier
    relevé réel date d'avant-hier ou plus, on retente toutes les 2 h plutôt
    que d'attendre le lendemain.
    """
    if last_dateni is not None:
        yesterday = now.date() - timedelta(days=1)
        if last_dateni.date() < yesterday:
            return UPDATE_RETRY_DELAY

    rng = rng or random
    target = now.replace(hour=UPDATE_HOUR, minute=UPDATE_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    target += timedelta(minutes=rng.randint(0, UPDATE_JITTER_MAX_MINUTES))
    return target - now


def build_reading(
    contrat: Contrat,
    points: list[TeleindexPoint],
    jours_completes: int,
) -> ContractReading:
    """Consolide les points d'une fenêtre en lecture courante pour un contrat."""
    if not points:
        return ContractReading(
            contrat_id=contrat.contrat_id,
            numcontrat=contrat.numcontrat,
            jours_completes=jours_completes,
        )
    # parse_teleindex_payload trie par dateni : le dernier point est le plus récent.
    last = points[-1]
    return ContractReading(
        contrat_id=contrat.contrat_id,
        numcontrat=contrat.numcontrat,
        index_m3=last.index_l / LITERS_PER_CUBIC_METER,
        conso_l=last.conso_l,
        dateni=last.dateni,
        numserie=last.numserie,
        estimated=last.estimated,
        jours_completes=jours_completes,
    )


class EauDuPicCoordinator(DataUpdateCoordinator[dict[str, ContractReading]]):
    """Collecte une fois par jour (après le relevé de ~01h00), pour tous les contrats."""

    config_entry: EauDuPicConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: EauDuPicConfigEntry,
        client: EauDuPicApiClient,
    ) -> None:
        """Initialise le coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            # Valeur initiale immédiatement remplacée par next_poll_interval
            # à la fin du premier cycle de collecte.
            update_interval=UPDATE_RETRY_DELAY,
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, ContractReading]:
        now = dt_util.now()
        debut, fin = window_dates(now)
        try:
            contrats = await self.client.async_get_contrats()
            readings: dict[str, ContractReading] = {}
            for contrat in contrats:
                points, jours_completes = await self.client.async_get_teleindex(
                    contrat.contrat_id, debut, fin
                )
                readings[contrat.contrat_id] = build_reading(contrat, points, jours_completes)
        except EauDuPicApiClientAuthenticationError as err:
            raise ConfigEntryAuthFailed(err) from err
        except EauDuPicApiClientError as err:
            raise UpdateFailed(err) from err

        last_dateni: datetime | None = max(
            (reading.dateni for reading in readings.values() if reading.dateni is not None),
            default=None,
        )
        self.update_interval = next_poll_interval(now, last_dateni)
        if LOGGER.isEnabledFor(logging.DEBUG):
            for reading in readings.values():
                LOGGER.debug(
                    "contrat %s : index=%s m³ (dateni=%s), conso=%s L, jours comblés=%s, "
                    "prochaine collecte dans %s",
                    reading.contrat_id,
                    reading.index_m3,
                    reading.dateni,
                    reading.conso_l,
                    reading.jours_completes,
                    self.update_interval,
                )
        return readings
