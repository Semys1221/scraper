# Outreach System — Étapes du processus

## 1. Scraping (Engine)
- **Agent** : `engine.py`
- **Déclencheur** : cron Render `0 9 * * *` ou appel POST `/jobs/engine`
- **Action** : prend 1 campagne `pending` dans `campaign_queue`, crée la campagne Smartlead avec variantes A/B/C, lance le scrape Outscraper (`/maps/search-v2`) avec webhook callback vers cleaner_api, passe la campagne en `scraping`
- **Sortie** : webhook Outscraper POST vers cleaner_api

## 2. Cleaning (Cleaner API webhook)
- **Agent** : `cleaner_api.py` endpoint `/webhook/outscraper`
- **Déclencheur** : callback Outscraper (param `queue_id`)
- **Action** :
  - Parse le payload brut
  - Filtre emails génériques, déduplique par `place_id`/email
  - Extrait first_name depuis l’email
  - Construit `custom_fields` (intro personnalisée)
  - Upsert dans table `leads` (`status=cleaned`)
  - Push batch vers Smartlead (`/campaigns/{id}/leads`)
  - Met à jour campagne : `active` si import > 0, sinon `paused`
- **Sortie** : leads en base + Discord notification

## 3. Push Smartlead (intégré au webhook)
- **Agent** : `config.py` → `push_to_smartlead()`
- **Déclencheur** : après nettoyage, si `smartlead_campaign_id` existe
- **Action** : envoie `lead_list` à Smartlead, retourne `success_count` / `fail_count`
- **Sortie** : mise à jour `status=imported_smartlead` pour les succès

## 4. Judge audit
- **Agent** : `judge.py`
- **Déclencheur** : cron Render `30 10 * * *` ou appel POST `/jobs/judge`
- **Action** : pour chaque campagne `active`, récupère analytics Smartlead, calcule true reply rate (réponses totales - auto-réponses), compare à seuil 2 % et volume min 100. Si en dessous : pause Smartlead + status `killed`
- **Sortie** : Discord notification + update DB

## 5. Discord digest
- **Agent** : `digest.py`
- **Déclencheur** : cron Render `0 11 * * *` ou appel POST `/jobs/digest`
- **Action** : comptes sur dernières 24h : leads bruts, nettoyés, importés, campagnes pending/active/killed, stock total
- **Sortie** : message formaté vers webhook Discord

## 6. Orchestrateur (Cleaner API jobs)
- **Agent** : `cleaner_api.py` endpoints `/jobs/*`
- **Déclencheur** : Render Cron Jobs pointent vers ces endpoints
- **Action** : exécute `engine_main()` / `judge_main()` / `digest_main()` via HTTP POST protégé par `JOB_API_TOKEN`
- **Sortie** : `{"status":"done","job":"..."}`

## Services externes
- **Outscraper / Leadsscraper** : scraping Google Maps avec enrichment contacts
- **Smartlead** : gestion campagnes outbound, séquences A/B/C, analytics, pause
- **Supabase** : stockage leads + campagnes (`campaign_queue`, `leads`)
- **Discord** : notifications temps réel + digest quotidien
- **Render** : hébergement cleaner_api + scheduling cron

## États d’une campagne (`campaign_queue.status`)
- `pending` → en attente de traitement engine
- `scraping` → Outscraper en cours, webhook attendu
- `active` → leads poussés Smartlead, judge audit en cours
- `paused` → campagne créée mais 0 lead importé
- `killed` → tuée par judge (taux réponse trop bas)
