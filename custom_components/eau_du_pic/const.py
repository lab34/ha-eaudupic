"""Constantes de l'intégration Eau du Pic."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.const import Platform

# Identité de l'intégration
DOMAIN = "eau_du_pic"
PLATFORMS: list[Platform] = [Platform.SENSOR]

# Clés de configuration (config entry)
CONF_LOGIN = "login"
CONF_PASSWORD = "password"  # noqa: S105 - clé de config, pas un secret
CONF_AUTOLOGIN = "autologin"

# Réseau — portail iClients Eau du Pic (JVS-Mairistem), cf. flow.md
API_BASE_URL = "https://eaudupic.client.ccgpsl.fr"
API_ID = "d2e3b03552d0e10cfa2a5e1e9e3dc73b@iclients-35664-picsaintloup"
API_REFERER = "https://eaudupic.client.ccgpsl.fr/telereleves"
API_CONTENT_TYPE = "application/vnd.api+json"
API_TIMEOUT = 30

# Chemins d'API
API_PATH_SIGNIN = "/api/v1/iclients/signin"
API_PATH_CONTRAT = "/api/v1/iclients/contrat"
API_PATH_TELEINDEX = "/api/v1/iclients/teleindex2"

# Collecte : 1 relevé/jour côté partenaire (~01h00), disponible le matin.
# On cible 06h30 avec un léger jitter, et on réessaie 2 h plus tard si le
# relevé de la veille n'est pas encore arrivé.
UPDATE_HOUR = 6
UPDATE_MINUTE = 30
UPDATE_JITTER_MAX_MINUTES = 15
UPDATE_RETRY_DELAY = timedelta(hours=2)
WINDOW_DAYS = 7

# Unités : teleindex2 renvoie des litres ; le dashboard Énergie attend des m³.
LITERS_PER_CUBIC_METER = 1000.0
