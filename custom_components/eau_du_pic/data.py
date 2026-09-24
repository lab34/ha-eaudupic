"""Types et données partagés de l'intégration Eau du Pic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry

if TYPE_CHECKING:
    from .coordinator import EauDuPicCoordinator

type EauDuPicConfigEntry = ConfigEntry[EauDuPicCoordinator]


@dataclass(slots=True)
class Contrat:
    """Un contrat d'eau rattaché au compte (GET /contrat)."""

    contrat_id: str
    numcontrat: str | None = None


@dataclass(slots=True)
class TeleindexPoint:
    """Un point de télérelève réel (attributes.add == False).

    dateni est en heure locale du portail (Europe/Paris), format
    « YYYY-MM-DD HH:MM:SS ». Les jours « comblés » (add == True) ne sont
    jamais représentés ici : ils sont filtrés en amont.
    """

    dateni: datetime
    index_l: int
    conso_l: int
    numserie: str | None = None
    estimated: bool = False


@dataclass(slots=True)
class ContractReading:
    """Dernière lecture consolidée d'un contrat, exposée par le coordinator."""

    contrat_id: str
    numcontrat: str | None = None
    index_m3: float | None = None
    conso_l: float | None = None
    dateni: datetime | None = None
    numserie: str | None = None
    estimated: bool | None = None
    jours_completes: int = 0
