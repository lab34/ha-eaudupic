"""Entité de base Eau du Pic : device par contrat + nommage par traductions."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EauDuPicCoordinator
from .data import ContractReading


class EauDuPicEntity(CoordinatorEntity[EauDuPicCoordinator]):
    """Entité rattachée au coordinator et au device du contrat."""

    _attr_has_entity_name = True
    _attr_attribution = "Données télérelève du portail Eau du Pic (CCG du Grand Pic Saint-Loup)"

    def __init__(
        self,
        coordinator: EauDuPicCoordinator,
        contrat_id: str,
        entity_suffix: str,
        numcontrat: str | None,
    ) -> None:
        """Initialise l'entité pour un contrat donné."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._contrat_id = contrat_id
        self._attr_unique_id = f"{entry.entry_id}_{contrat_id}_{entity_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}:{contrat_id}")},
            name=f"Eau du Pic ({numcontrat or contrat_id})",
            manufacturer="JVS-Mairistem / Suez",
            model="Télérelève compteur d'eau",
        )

    @property
    def reading(self) -> ContractReading | None:
        """Lecture courante du contrat, ou None si le contrat a disparu."""
        return self.coordinator.data.get(self._contrat_id)
