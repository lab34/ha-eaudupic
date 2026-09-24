"""Client API asynchrone du portail Eau du Pic (iClients / JVS-Mairistem).

Ce module est volontairement indépendant de Home Assistant (aucun import du
paquet homeassistant) : la logique HTTP vit ici, la logique d'intégration
dans le coordinator. Les échanges reproduits sont documentés dans une analyse
réseau du portail, rejouée et validée en live (vérifiée le 2026-09-24).

Points clés du protocole :
- chaque requête doit porter le header statique « Api-Id » ;
- l'authentification retenue est la voie « AutoLogin » : POST /signin avec
  remember=true, le token (hex 64) est renvoyé dans le header de réponse
  « autologin » et se réutilise tel quel dans le header « AutoLogin »
  (durée de vie ~1 an, pas besoin de cookies ni de JWT) ;
- les GET de données exigent un « Referer » du même domaine (403 sinon) ;
- une 401 se traite par un nouveau signin puis un unique rejeu de la requête.
"""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import date, datetime
from typing import Any

import aiohttp

from .const import (
    API_BASE_URL,
    API_CONTENT_TYPE,
    API_ID,
    API_PATH_CONTRAT,
    API_PATH_SIGNIN,
    API_PATH_TELEINDEX,
    API_REFERER,
    API_TIMEOUT,
    LITERS_PER_CUBIC_METER,
)
from .data import Contrat, TeleindexPoint

_DATENI_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


class EauDuPicApiClientError(Exception):
    """Erreur de base du client API Eau du Pic."""


class EauDuPicApiClientAuthenticationError(EauDuPicApiClientError):
    """Identifiants refusés, ou token définitivement invalide."""


class EauDuPicApiClientCommunicationError(EauDuPicApiClientError):
    """Erreur réseau, timeout ou réponse serveur inattendue."""


def parse_dateni(value: str) -> datetime:
    """Convertit une date de relevé API en datetime naïf (heure locale du portail)."""
    for fmt in _DATENI_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    msg = f"format de date de relevé inattendu : {value!r}"
    raise EauDuPicApiClientError(msg)


def parse_teleindex_payload(payload: dict[str, Any]) -> tuple[list[TeleindexPoint], int]:
    """Extrait les relevés réels d'une réponse teleindex2.

    Renvoie (points triés par dateni, nombre de jours « comblés » vus dans
    la fenêtre). Filtre impératif (cf. flow.md) : ne garder que les relevés
    réels add == False avec index et conso non nuls — les jours comblés ont
    un index gelé et des consos nulles parasites, les points sans conso
    précèdent l'activation de la télérelève.
    """
    points: list[TeleindexPoint] = []
    jours_completes = 0
    for item in payload.get("data") or []:
        attrs = item.get("attributes") or {}
        if attrs.get("add") is True:
            jours_completes += 1
            continue
        if attrs.get("ni") is None or attrs.get("l") is None or attrs.get("dateni") is None:
            continue
        points.append(
            TeleindexPoint(
                dateni=parse_dateni(attrs["dateni"]),
                index_l=int(attrs["ni"]),
                conso_l=int(attrs["l"]),
                numserie=attrs.get("numserie"),
                estimated=bool(attrs.get("estimated_consumption", False)),
            )
        )
    points.sort(key=lambda point: point.dateni)
    return points, jours_completes


def index_to_m3(index_l: int) -> float:
    """Convertit un index litres en m³ (unité attendue par le dashboard Énergie)."""
    return index_l / LITERS_PER_CUBIC_METER


class EauDuPicApiClient:
    """Client HTTP du portail Eau du Pic (voie AutoLogin)."""

    def __init__(
        self,
        login: str,
        password: str,
        session: aiohttp.ClientSession,
    ) -> None:
        """Initialise le client avec les identifiants du portail."""
        self._login = login
        self._password = password
        self._session = session
        self._autologin: str | None = None

    @property
    def autologin(self) -> str | None:
        """Token AutoLogin courant (hex64), ou None tant que non connecté."""
        return self._autologin

    def _headers(self, *, authorized: bool = False, with_body: bool = False) -> dict[str, str]:
        headers = {"accept": API_CONTENT_TYPE, "Api-Id": API_ID}
        if with_body:
            headers["content-type"] = API_CONTENT_TYPE
        if authorized:
            headers["Referer"] = API_REFERER
            if self._autologin is not None:
                headers["AutoLogin"] = self._autologin
        return headers

    async def async_signin(self) -> str:
        """Ouvre une session et stocke le token AutoLogin (~1 an)."""
        body = json.dumps(
            {
                "data": {
                    "type": "POICL_Signin",
                    "id": "",
                    "attributes": {
                        "login": self._login,
                        "password": self._password,
                        "remember": True,
                    },
                }
            }
        )
        try:
            async with asyncio.timeout(API_TIMEOUT):
                async with self._session.post(
                    f"{API_BASE_URL}{API_PATH_SIGNIN}",
                    data=body,
                    headers=self._headers(with_body=True),
                ) as resp:
                    if resp.status in (401, 403):
                        raise EauDuPicApiClientAuthenticationError(
                            "identifiants refusés par le portail (code 666013 attendu)"
                        )
                    if resp.status != 201:
                        msg = f"réponse signin inattendue : HTTP {resp.status}"
                        raise EauDuPicApiClientCommunicationError(msg)
                    token = resp.headers.get("autologin")
        except EauDuPicApiClientError:
            raise
        except (TimeoutError, aiohttp.ClientError, socket.gaierror) as err:
            msg = "portail injoignable pendant le signin"
            raise EauDuPicApiClientCommunicationError(msg) from err

        if not token:
            msg = "réponse signin sans header autologin"
            raise EauDuPicApiClientCommunicationError(msg)
        self._autologin = token
        return token

    async def async_get_contrats(self) -> list[Contrat]:
        """Liste les contrats d'eau rattachés au compte."""
        payload = await self._authorized_get(API_PATH_CONTRAT)
        contrats = [
            Contrat(
                contrat_id=str(item["id"]),
                numcontrat=(item.get("attributes") or {}).get("numcontrat"),
            )
            for item in payload.get("data") or []
            if item.get("id") is not None
        ]
        if not contrats:
            msg = "aucun contrat d'eau rattaché à ce compte"
            raise EauDuPicApiClientError(msg)
        return contrats

    async def async_get_teleindex(
        self, contrat_id: str, debut: date, fin: date
    ) -> tuple[list[TeleindexPoint], int]:
        """Récupère la télérelève d'un contrat entre deux dates (bornes inclusives)."""
        path = (
            f"{API_PATH_TELEINDEX}/{contrat_id}/{debut:%Y%m%d}/{fin:%Y%m%d}"
            "?option[sort]=asc&option[algorithm]=chronological"
        )
        payload = await self._authorized_get(path)
        return parse_teleindex_payload(payload)

    async def _authorized_get(self, path: str) -> dict[str, Any]:
        """GET authentifié : re-signin puis un seul rejeu en cas de 401."""
        if self._autologin is None:
            await self.async_signin()
        try:
            return await self._get(path)
        except EauDuPicApiClientAuthenticationError:
            await self.async_signin()
            return await self._get(path)

    async def _get(self, path: str) -> dict[str, Any]:
        url = f"{API_BASE_URL}{path}"
        try:
            async with asyncio.timeout(API_TIMEOUT):
                async with self._session.get(url, headers=self._headers(authorized=True)) as resp:
                    if resp.status in (401, 403):
                        msg = f"requête refusée par la gateway (HTTP {resp.status}) sur {path}"
                        raise EauDuPicApiClientAuthenticationError(msg)
                    if resp.status >= 400:
                        msg = f"réponse inattendue (HTTP {resp.status}) sur {path}"
                        raise EauDuPicApiClientCommunicationError(msg)
                    # content_type=None : l'API répond en application/vnd.api+json,
                    # que aiohttp n'accepte pas par défaut.
                    return await resp.json(content_type=None)
        except EauDuPicApiClientError:
            raise
        except (TimeoutError, aiohttp.ClientError, socket.gaierror) as err:
            msg = f"erreur réseau sur {path}"
            raise EauDuPicApiClientCommunicationError(msg) from err
