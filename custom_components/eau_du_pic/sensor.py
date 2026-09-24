"""Capteurs Eau du Pic : index du compteur (m³) et consommation d'hier (L)."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import EauDuPicCoordinator
from .data import EauDuPicConfigEntry
from .entity import EauDuPicEntity

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="index",
        translation_key="eau_index",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=3,
    ),
    SensorEntityDescription(
        key="conso_hier",
        translation_key="eau_conso_hier",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=UnitOfVolume.LITERS,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EauDuPicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crée deux capteurs par contrat découvert lors de la première collecte."""
    coordinator: EauDuPicCoordinator = entry.runtime_data
    async_add_entities(
        EauDuPicSensor(coordinator, contrat_id, description, reading.numcontrat)
        for contrat_id, reading in sorted(coordinator.data.items())
        for description in SENSOR_DESCRIPTIONS
    )


class EauDuPicSensor(EauDuPicEntity, SensorEntity):
    """Capteur d'eau alimenté par le coordinator."""

    def __init__(
        self,
        coordinator: EauDuPicCoordinator,
        contrat_id: str,
        description: SensorEntityDescription,
        numcontrat: str | None,
    ) -> None:
        """Initialise un capteur pour une description donnée (index ou conso)."""
        super().__init__(coordinator, contrat_id, description.key, numcontrat)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Valeur du dernier relevé réel (jours comblés exclus)."""
        reading = self.reading
        if reading is None:
            return None
        if self.entity_description.key == "index":
            return reading.index_m3
        return reading.conso_l

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Attributs de diagnostic issus du portail."""
        reading = self.reading
        if reading is None:
            return {}
        attrs: dict[str, object] = {
            "contrat_id": reading.contrat_id,
            "jours_completes": reading.jours_completes,
        }
        if reading.numcontrat is not None:
            attrs["numcontrat"] = reading.numcontrat
        if reading.dateni is not None:
            attrs["dateni"] = reading.dateni.isoformat()
        if reading.numserie is not None:
            attrs["numserie"] = reading.numserie
        if reading.estimated is not None:
            attrs["estimated_consumption"] = reading.estimated
        return attrs
