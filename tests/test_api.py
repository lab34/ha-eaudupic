"""Tests du client API (voie AutoLogin) via aioclient_mock de HA."""

from __future__ import annotations

from datetime import date

import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.eau_du_pic.api import (
    EauDuPicApiClient,
    EauDuPicApiClientAuthenticationError,
    EauDuPicApiClientCommunicationError,
    EauDuPicApiClientError,
    parse_dateni,
)
from custom_components.eau_du_pic.const import (
    API_BASE_URL,
    API_ID,
    API_PATH_CONTRAT,
    API_PATH_SIGNIN,
    API_PATH_TELEINDEX,
    LITERS_PER_CUBIC_METER,
)
from tests.conftest import (
    TEST_LOGIN,
    TEST_PASSWORD,
    TEST_TOKEN,
    contrat_payload,
    teleindex_payload,
)

SIGNIN_URL = f"{API_BASE_URL}{API_PATH_SIGNIN}"
CONTRAT_URL = f"{API_BASE_URL}{API_PATH_CONTRAT}"


def teleindex_url(contrat_id: str, debut: date, fin: date) -> str:
    """URL exacte que le client construit pour teleindex2."""
    return (
        f"{API_BASE_URL}{API_PATH_TELEINDEX}/{contrat_id}/"
        f"{debut:%Y%m%d}/{fin:%Y%m%d}"
        "?option[sort]=asc&option[algorithm]=chronological"
    )


def make_client(hass) -> EauDuPicApiClient:
    return EauDuPicApiClient(TEST_LOGIN, TEST_PASSWORD, async_get_clientsession(hass))


async def test_signin_stores_autologin_token(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    client = make_client(hass)

    token = await client.async_signin()

    assert token == TEST_TOKEN
    assert client.autologin == TEST_TOKEN
    assert aioclient_mock.call_count == 1


async def test_signin_sends_required_headers_and_body(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    client = make_client(hass)

    await client.async_signin()

    method, _url, body, headers = aioclient_mock.mock_calls[0]
    assert method.upper() == "POST"
    assert headers["Api-Id"] == API_ID
    assert headers["content-type"] == "application/vnd.api+json"
    assert '"remember":true' in body.replace(" ", "")
    assert TEST_LOGIN in body
    assert TEST_PASSWORD in body


async def test_signin_invalid_credentials(hass, aioclient_mock):
    aioclient_mock.post(
        SIGNIN_URL,
        status=401,
        json={"errors": [{"code": 666013, "title": "not authenticated"}]},
    )
    client = make_client(hass)

    with pytest.raises(EauDuPicApiClientAuthenticationError):
        await client.async_signin()


async def test_signin_without_autologin_header(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, text="{}")
    client = make_client(hass)

    with pytest.raises(EauDuPicApiClientCommunicationError):
        await client.async_signin()


async def test_teleindex_filters_completed_days(hass, aioclient_mock):
    """Seuls les relevés réels (add=false, l non null) sont conservés."""
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    aioclient_mock.get(
        teleindex_url("12345", date(2026, 9, 11), date(2026, 9, 18)),
        status=200,
        json=teleindex_payload(
            [
                {"type": "x", "id": "recent", "attributes": {
                    "dateni": "2026-09-17 01:00:00", "ni": 159874, "l": 817,
                    "numserie": "AB01CD***123", "add": False,
                    "estimated_consumption": False,
                }},
                {"type": "x", "id": "completion_1", "attributes": {
                    "dateni": "2026-09-18", "ni": 159874, "l": 0,
                    "add": True, "estimated_consumption": True,
                }},
                {"type": "x", "id": "pre_activation", "attributes": {
                    "dateni": "2026-09-16 01:00:00", "ni": 159057, "l": None,
                    "add": False,
                }},
            ]
        ),
    )
    client = make_client(hass)

    points, jours_completes = await client.async_get_teleindex(
        "12345", date(2026, 9, 11), date(2026, 9, 18)
    )

    assert jours_completes == 1
    assert [p.dateni.strftime("%Y-%m-%d") for p in points] == ["2026-09-17"]
    assert points[0].index_l == 159874
    assert points[0].conso_l == 817
    assert points[0].numserie == "AB01CD***123"
    assert points[0].estimated is False


async def test_data_request_carries_autologin_and_referer(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    aioclient_mock.get(
        teleindex_url("12345", date(2026, 9, 11), date(2026, 9, 18)),
        status=200,
        json=teleindex_payload([]),
    )
    client = make_client(hass)

    await client.async_get_teleindex("12345", date(2026, 9, 11), date(2026, 9, 18))

    method, _url, _body, headers = aioclient_mock.mock_calls[-1]
    assert method.upper() == "GET"
    assert headers["AutoLogin"] == TEST_TOKEN
    assert headers["Referer"].startswith(API_BASE_URL)
    assert headers["Api-Id"] == API_ID


async def test_401_triggers_resignin_and_replay(hass, aioclient_mock):
    """Une 401 sur les données → re-signin puis rejeu unique de la requête."""
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    url = teleindex_url("12345", date(2026, 9, 11), date(2026, 9, 18))
    calls = {"get": 0}

    async def get_side_effect(method, req_url, data):
        calls["get"] += 1
        if calls["get"] == 1:
            return AiohttpClientMockResponse(method, req_url, status=401, text="Not authorized !")
        return AiohttpClientMockResponse(method, req_url, status=200, json=teleindex_payload([]))

    aioclient_mock.get(url, side_effect=get_side_effect)
    client = make_client(hass)

    points, _ = await client.async_get_teleindex("12345", date(2026, 9, 11), date(2026, 9, 18))

    assert points == []
    assert client.autologin == TEST_TOKEN
    signin_calls = [c for c in aioclient_mock.mock_calls if c[0].upper() == "POST"]
    assert len(signin_calls) == 2


async def test_persistent_401_raises_authentication_error(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    url = teleindex_url("12345", date(2026, 9, 11), date(2026, 9, 18))

    async def always_401(method, req_url, data):
        return AiohttpClientMockResponse(method, req_url, status=401, text="Not authorized !")

    aioclient_mock.get(url, side_effect=always_401)
    client = make_client(hass)

    with pytest.raises(EauDuPicApiClientAuthenticationError):
        await client.async_get_teleindex("12345", date(2026, 9, 11), date(2026, 9, 18))


async def test_server_error_raises_communication_error(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    aioclient_mock.get(
        teleindex_url("12345", date(2026, 9, 11), date(2026, 9, 18)),
        status=500,
        text="boom",
    )
    client = make_client(hass)

    with pytest.raises(EauDuPicApiClientCommunicationError):
        await client.async_get_teleindex("12345", date(2026, 9, 11), date(2026, 9, 18))


async def test_contrats_parsing(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    aioclient_mock.get(
        CONTRAT_URL,
        status=200,
        json=contrat_payload(("12345", "340000001"), ("9001", "340000002")),
    )
    client = make_client(hass)

    contrats = await client.async_get_contrats()

    assert [(c.contrat_id, c.numcontrat) for c in contrats] == [
        ("12345", "340000001"),
        ("9001", "340000002"),
    ]


async def test_empty_contrat_list_raises(hass, aioclient_mock):
    aioclient_mock.post(SIGNIN_URL, status=201, headers={"autologin": TEST_TOKEN}, text="{}")
    aioclient_mock.get(CONTRAT_URL, status=200, json={"data": []})
    client = make_client(hass)

    with pytest.raises(EauDuPicApiClientError, match="aucun contrat"):
        await client.async_get_contrats()


def test_index_conversion():
    assert pytest.approx(159.874) == 159874 / 1000
    assert pytest.approx(159874 / LITERS_PER_CUBIC_METER) == 159.874


def test_parse_dateni_supported_formats():
    assert parse_dateni("2026-09-17 01:00:00").strftime("%Y%m%d %H%M") == "20260917 0100"
    assert parse_dateni("2026-09-17").strftime("%Y%m%d") == "20260917"
    with pytest.raises(EauDuPicApiClientError):
        parse_dateni("17/09/2026")
