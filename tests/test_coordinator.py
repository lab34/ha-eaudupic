"""Tests du coordinator : fenêtre glissante, consolidation, intervalle dynamique."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eau_du_pic.api import (
    EauDuPicApiClientAuthenticationError,
    EauDuPicApiClientCommunicationError,
    EauDuPicApiClientError,
)
from custom_components.eau_du_pic.const import (
    DOMAIN,
    UPDATE_HOUR,
    UPDATE_JITTER_MAX_MINUTES,
    UPDATE_MINUTE,
    UPDATE_RETRY_DELAY,
)
from custom_components.eau_du_pic.coordinator import (
    EauDuPicCoordinator,
    build_reading,
    next_poll_interval,
    window_dates,
)
from custom_components.eau_du_pic.data import Contrat, TeleindexPoint
from tests.conftest import TEST_LOGIN, TEST_PASSWORD, TEST_TOKEN


def make_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Eau du Pic",
        data={
            "login": TEST_LOGIN,
            "password": TEST_PASSWORD,
            "autologin": TEST_TOKEN,
        },
    )


def make_coordinator(hass, client) -> EauDuPicCoordinator:
    entry = make_entry()
    entry.add_to_hass(hass)
    return EauDuPicCoordinator(hass, entry, client)


def local_time(*args) -> datetime:
    """Instant UTC à passer à freezer.move_to pour une heure locale donnée.

    freezer.move_to interprète toute chaîne comme UTC ; construire l'instant
    depuis DEFAULT_TIME_ZONE rend les tests indépendants du fuseau de la
    machine (la fenêtre de rattrapage porte sur l'heure locale).
    """
    return datetime(*args, tzinfo=dt_util.DEFAULT_TIME_ZONE).astimezone(UTC)


def test_window_dates_is_sliding_seven_days():
    debut, fin = window_dates(datetime(2026, 9, 24, 10, 30))
    assert (debut, fin) == (date(2026, 9, 17), date(2026, 9, 24))


def test_next_poll_interval_targets_0630_next_day():
    now = datetime(2026, 9, 24, 10, 0)
    interval = next_poll_interval(now, datetime(2026, 9, 23, 1, 0, 0))

    assert timedelta(hours=20, minutes=30) <= interval <= timedelta(hours=20, minutes=45)


def test_next_poll_interval_targets_0630_same_day():
    now = datetime(2026, 9, 24, 3, 0)
    interval = next_poll_interval(now, datetime(2026, 9, 23, 1, 0, 0))

    assert timedelta(hours=3, minutes=30) <= interval <= timedelta(hours=3, minutes=45)


def test_next_poll_interval_with_no_data_still_schedules_tomorrow():
    now = datetime(2026, 9, 24, 10, 0)
    interval = next_poll_interval(now, None)

    assert timedelta(hours=20, minutes=30) <= interval <= timedelta(hours=20, minutes=45)


def test_next_poll_interval_retries_when_reading_missing():
    now = datetime(2026, 9, 24, 6, 40)
    # Dernier relevé réel : avant-hier → celui d'hier manque encore.
    interval = next_poll_interval(now, datetime(2026, 9, 22, 1, 0, 0))

    assert interval == UPDATE_RETRY_DELAY


def test_next_poll_interval_retries_j2_morning_while_waiting():
    # Livraison J+2 : à 06h40 le point attendu (J-2, publié en cours de
    # matinée) n'est pas encore là → retry 2 h.
    now = datetime(2026, 9, 25, 6, 40)
    interval = next_poll_interval(now, datetime(2026, 9, 23, 1, 0, 0))

    assert interval == UPDATE_RETRY_DELAY


def test_next_poll_interval_stops_for_the_day_once_new_point_fetched():
    # Le point en retard J+2 vient d'être capturé : prochaine collecte
    # demain 06h30 (+ jitter), pas de nouveau retry dans la journée.
    now = datetime(2026, 9, 25, 10, 45)
    interval = next_poll_interval(
        now, datetime(2026, 9, 23, 1, 0, 0), fresh_pickup=True
    )

    assert timedelta(hours=19, minutes=45) <= interval <= timedelta(hours=20, minutes=0)


def test_next_poll_interval_no_retry_after_morning_window():
    # Passé 14 h les données du jour sont considérées tombées : on recale
    # demain 06h30, même si le dernier relevé reste en retard de 2 jours.
    now = datetime(2026, 9, 25, 14, 30)
    interval = next_poll_interval(now, datetime(2026, 9, 23, 1, 0, 0))

    assert timedelta(hours=16, minutes=0) <= interval <= timedelta(hours=16, minutes=15)


def test_next_poll_interval_never_polls_at_night():
    # 23h avec un retard J+2 : prochaine collecte demain 06h30, pas de
    # retry nocturne (le partenaire ne publie qu'une fois par jour).
    now = datetime(2026, 9, 25, 23, 0)
    interval = next_poll_interval(now, datetime(2026, 9, 23, 1, 0, 0))

    assert timedelta(hours=7, minutes=30) <= interval <= timedelta(hours=7, minutes=45)


def test_next_poll_interval_deterministic_with_seeded_rng():
    now = datetime(2026, 9, 24, 10, 0)
    interval_a = next_poll_interval(now, None, random.Random(42))
    interval_b = next_poll_interval(now, None, random.Random(42))

    assert interval_a == interval_b


def test_build_reading_uses_last_real_point():
    contrat = Contrat("12345", "340000001")
    points = [
        TeleindexPoint(datetime(2026, 9, 16, 1, 0, 0), 159057, 700),
        TeleindexPoint(datetime(2026, 9, 17, 1, 0, 0), 159874, 817, "AB01CD***123"),
    ]

    reading = build_reading(contrat, points, jours_completes=3)

    assert reading.contrat_id == "12345"
    assert reading.numcontrat == "340000001"
    assert reading.index_m3 == pytest.approx(159.874)
    assert reading.conso_l == 817
    assert reading.dateni == datetime(2026, 9, 17, 1, 0, 0)
    assert reading.numserie == "AB01CD***123"
    assert reading.estimated is False
    assert reading.jours_completes == 3


def test_build_reading_without_real_point():
    reading = build_reading(Contrat("12345", "340000001"), [], jours_completes=7)

    assert reading.index_m3 is None
    assert reading.conso_l is None
    assert reading.dateni is None
    assert reading.jours_completes == 7


async def test_coordinator_collects_all_contracts(hass, mock_client):
    coordinator = make_coordinator(hass, mock_client)
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert set(coordinator.data) == {"12345", "9001"}
    assert coordinator.data["12345"].index_m3 == pytest.approx(159.874)
    assert coordinator.data["12345"].conso_l == 817
    # Les deux contrats sont interrogés sur leur fenêtre propre.
    assert mock_client.async_get_teleindex.await_count == 2


async def test_coordinator_sets_dynamic_interval_after_refresh(hass, mock_client, freezer):
    # Heure figée : la prochaine collecte doit viser 06h30 (aujourd'hui ou demain) + jitter.
    freezer.move_to("2026-09-24T10:00:00+00:00")
    now = dt_util.now()
    coordinator = make_coordinator(hass, mock_client)
    await coordinator.async_refresh()

    target = now.replace(hour=UPDATE_HOUR, minute=UPDATE_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    assert target - now <= coordinator.update_interval <= target - now + timedelta(minutes=15)
    assert coordinator.update_interval != UPDATE_RETRY_DELAY


def stale_point() -> TeleindexPoint:
    """Relevé daté du 23/09 01h00 : J-2 dans le contexte des tests ci-dessous."""
    return TeleindexPoint(dateni=datetime(2026, 9, 23, 1, 0, 0), index_l=159874, conso_l=817)


async def test_coordinator_keeps_retrying_while_no_new_point(hass, mock_client, freezer):
    # Régime J+2 : le poll du matin (heure locale) ne rapporte rien de neuf
    # (le point du 24/09 n'est pas encore publié le 25) → retries 2 h.
    freezer.move_to(local_time(2026, 9, 24, 12, 0))
    mock_client.async_get_teleindex = AsyncMock(return_value=([stale_point()], 2))
    coordinator = make_coordinator(hass, mock_client)
    await coordinator.async_refresh()

    freezer.move_to(local_time(2026, 9, 25, 8, 40))
    await coordinator.async_refresh()

    assert coordinator.update_interval == UPDATE_RETRY_DELAY


async def test_coordinator_schedules_next_morning_once_new_point_fetched(
    hass, mock_client, freezer
):
    # Le point en retard arrive en cours de matinée : dès qu'il est capturé,
    # la collecte se recale au créneau 06h30 du lendemain.
    freezer.move_to(local_time(2026, 9, 24, 12, 0))
    mock_client.async_get_teleindex = AsyncMock(return_value=([stale_point()], 2))
    coordinator = make_coordinator(hass, mock_client)
    await coordinator.async_refresh()

    freezer.move_to(local_time(2026, 9, 25, 8, 40))
    new_point = TeleindexPoint(
        dateni=datetime(2026, 9, 24, 1, 0, 0), index_l=160000, conso_l=126
    )
    mock_client.async_get_teleindex = AsyncMock(return_value=([new_point], 2))
    await coordinator.async_refresh()

    now = dt_util.now()
    target = now.replace(hour=UPDATE_HOUR, minute=UPDATE_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    assert (
        target - now
        <= coordinator.update_interval
        <= target - now + timedelta(minutes=UPDATE_JITTER_MAX_MINUTES)
    )
    assert coordinator.update_interval != UPDATE_RETRY_DELAY


async def test_coordinator_retries_after_api_error(hass, mock_client, freezer):
    # Échec API après un succès : l'intervalle repasse à 2 h pour retenter
    # le jour même au lieu d'attendre le créneau de demain.
    freezer.move_to(local_time(2026, 9, 24, 12, 0))
    mock_client.async_get_teleindex = AsyncMock(return_value=([stale_point()], 2))
    coordinator = make_coordinator(hass, mock_client)
    await coordinator.async_refresh()
    assert coordinator.update_interval != UPDATE_RETRY_DELAY

    mock_client.async_get_contrats = AsyncMock(
        side_effect=EauDuPicApiClientCommunicationError("portail injoignable")
    )
    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert coordinator.update_interval == UPDATE_RETRY_DELAY


async def test_coordinator_maps_auth_error(hass, mock_client):
    mock_client.async_get_contrats = AsyncMock(
        side_effect=EauDuPicApiClientAuthenticationError("401")
    )
    coordinator = make_coordinator(hass, mock_client)

    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


async def test_coordinator_maps_api_error_to_update_failed(hass, mock_client):
    mock_client.async_get_contrats = AsyncMock(side_effect=EauDuPicApiClientError("500"))
    coordinator = make_coordinator(hass, mock_client)

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
