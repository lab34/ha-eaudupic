# Eau du Pic pour Home Assistant

[![Validate](https://github.com/lab34/ha-eaudupic/actions/workflows/validate.yml/badge.svg)](https://github.com/lab34/ha-eaudupic/actions/workflows/validate.yml)
[![CI](https://github.com/lab34/ha-eaudupic/actions/workflows/ci.yml/badge.svg)](https://github.com/lab34/ha-eaudupic/actions/workflows/ci.yml)

Intégration Home Assistant (custom component HACS) qui récupère la **télérelève du
compteur d'eau** du portail abonnés [Eau du Pic](https://eaudupic.client.ccgpsl.fr)
(CCG du Grand Pic Saint-Loup, plateforme iClients de JVS-Mairistem, partenaire Suez).

Elle expose pour **chaque contrat d'eau** du compte :

- **Index du compteur** en m³ (`device_class: water`, `state_class: total_increasing`)
  → directement sélectionnable dans le **panneau Eau du dashboard Énergie** ;
- **Consommation d'hier** en litres (le relevé radio tombe vers 01h00) ;
- des **attributs de diagnostic** : date du relevé (`dateni`), numéro de série du
  compteur (`numserie`), `estimated_consumption`, nombre de jours sans relevé réel
  dans la fenêtre (`jours_completes`).

## Fonctionnement

- **Authentification par « autologin » (~1 an)** : l'intégration fait un
  `POST /signin` avec `remember: true` et réutilise le jeton long-lived renvoyé
  par le portail (`header autologin` → `header AutoLogin`). Pas de cookies ni de
  JWT à gérer, une connexion par an en régime normal.
- **Re-connexion transparente** : toute réponse 401 déclenche un nouveau
  `signin` puis le rejeu de la requête. Si les identifiants sont refusés
  (mot de passe changé), Home Assistant affiche automatiquement une carte de
  **re-authentification** (saisie du nouveau mot de passe).
- **Collecte quotidienne ciblée 06h30** (± 15 min) : le relevé partenaire tombe
  vers 01h00. Si le relevé d'hier manque encore (panne radio, portail en
  retard), nouvelle tentative toutes les **2 h**.
- **Fenêtre glissante J-7 → J** à chaque collecte : aucun relevé n'est raté
  après une interruption (HA éteint, portail indisponible). Seuls les
  **relevés réels** sont conservés — les jours « complétés » par le portail
  (`add: true`, index gelé) sont ignorés, sinon l'index stagne et des consos
  nulles parasites apparaissent.
- **Multi-contrats** : un appareil et ses deux capteurs sont créés par contrat
  trouvé via `GET /contrat`.

## Installation

### HACS (recommandé)

1. Ajouter ce dépôt comme dépôt personnalisé dans HACS :
   `HACS → ⋮ → Dépôts personnalisés → https://github.com/lab34/ha-eaudupic`
   (catégorie **Integration**).
2. Installer **Eau du Pic**, puis redémarrer Home Assistant.

### Manuel

Copier le dossier `custom_components/eau_du_pic/` dans
`<config>/custom_components/` de votre installation, puis redémarrer.

## Configuration

`Réglages → Appareils et services → Ajouter une intégration → Eau du Pic` :
saisir l'**identifiant** et le **mot de passe** du portail Eau du Pic. Les
capteurs apparaissent après la première collecte.

> Un seul compte par instance de Home Assistant (les doublons sont refusés).

## Dashboard Énergie (eau)

1. `Énergie → Ajouter une source d'eau` (Configuration du tableau de bord).
2. Choisir le capteur **Index du compteur** du contrat souhaité (unité m³).

La consommation journalière (litres) peut alimenter des `utility_meter` ou des
statistiques selon vos besoins.

## Développement

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

Structure : `api.py` (client HTTP aiohttp, sans dépendance Home Assistant),
`coordinator.py` (`DataUpdateCoordinator`, fenêtre glissante, intervalle
dynamique), `config_flow.py` (ajout + reauth), `sensor.py` (2 capteurs par
contrat), `const.py` (constantes réseau du portail).

## Limites connues & feuille de route

- **Pas de backfill historique** : à l'installation, seuls les 7 derniers jours
  sont visibles. L'API accepte une fenêtre de 365 jours en un appel — un
  backfill via les statistiques externes HA est prévu (v1.1).
- Les contrats ajoutés au compte **après** l'installation n'apparaissent qu'au
  prochain rechargement de l'intégration.
- Portails iClients d'autres régies (autre `Api-Id`, autre domaine) : non
  paramétrables pour l'instant, les constantes sont dans `const.py`.

## Avertissements

- **API non officielle** : cette intégration rejoue les requêtes du portail
  web, sans garantie de JVS-Mairistem ni de la régie. Un changement côté
  portail peut la casser.
- Le mot de passe est stocké dans la configuration de l'entrée (pratique
  standard pour ce type d'intégration, nécessaire au re-signin automatique) et
  le jeton autologin **vaut un mot de passe** (1 an) : ne partagez ni
  capture d'écran de la configuration ni export de votre `core.config_entries`.
- Usage à visée d'interopérabilité personnelle sur votre propre compte abonné.

## Licence

[MIT](LICENSE)
