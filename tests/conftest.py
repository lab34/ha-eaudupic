"""Fixtures pytest pour les tests de l'intégration Eau du Pic."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.eau_du_pic.data import Contrat, TeleindexPoint

pytest_plugins = "pytest_homeassistant_custom_component"

TEST_LOGIN = "marc.dupont"
TEST_PASSWORD = "s3cr3t"
TEST_TOKEN = "a" * 64


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Charge les custom components dans l'instance hass de test."""
    return enable_custom_integrations


def yesterday_reading() -> TeleindexPoint:
    """Relevé réel daté d'hier 01h00 (comme le relevé partenaire Suez)."""
    dateni = dt_util.now().replace(tzinfo=None, hour=1, minute=0, second=0, microsecond=0)
    return TeleindexPoint(
        dateni=dateni - timedelta(days=1),
        index_l=159874,
        conso_l=817,
        numserie="AB01CD***123",
        estimated=False,
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Client API mocké : deux contrats, une fenêtre avec jours réels et comblés."""
    client = MagicMock()
    client.autologin = TEST_TOKEN
    client.async_get_contrats = AsyncMock(
        return_value=[Contrat("12345", "340000001"), Contrat("9001", "340000002")]
    )
    client.async_get_teleindex = AsyncMock(
        return_value=([yesterday_reading()], 2)
    )
    return client


def contrat_payload(*contrats: tuple[str, str]) -> dict[str, Any]:
    """Réponse JSON:API de GET /contrat."""
    return {
        "jsonapi": {"version": "1.0"},
        "data": [
            {"type": "POICL_Contrat", "id": cid, "attributes": {"numcontrat": num}}
            for cid, num in contrats
        ],
    }


def teleindex_entry(
    entry_id: str = "28afb4ab833e071b6857973e84241dca",
    *,
    dateni: str = "2026-09-17 01:00:00",
    ni: int = 159874,
    conso: int | None = 817,
    add: bool = False,
    estimated: bool = False,
    numserie: str | None = "AB01CD***123",
) -> dict[str, Any]:
    """Une entrée de réponse teleindex2, conforme au format du portail."""
    return {
        "type": "PORLV_Teleconso2",
        "id": entry_id,
        "attributes": {
            "partner": "suez",
            "numserie": numserie,
            "dateni": dateni,
            "ni": ni,
            "l": conso,
            "add": add,
            "estimated_consumption": estimated,
        },
    }


def teleindex_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Réponse JSON:API de GET /teleindex2."""
    return {
        "jsonapi": {"version": "1.0"},
        "meta": {"count": len(entries)},
        "data": entries,
    }
