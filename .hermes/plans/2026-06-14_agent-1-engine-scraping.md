# Plan — Agent 1 : Scraping (Engine)

**Slug** : agent-1-engine-scraping  
**Date** : 2026-06-14  
**Scope** : Implémentation et validation de l’agent Engine seul (pas de modification des autres agents).

## Contexte
- Repo : `Semys1221/scraper` (`/Users/evqn/Business/Github/Outreach_System`)
- Agent ciblé : `engine.py`
- Services utilisés :
  - Supabase (`campaign_queue`, `leads`)
  - Outscraper/Leadsscraper (`/maps/search-v2`)
  - Smartlead (`/campaigns`)
  - Discord (notification)
- Webhook cible : cleaner_api `/webhook/outscraper`

## Objectif
Agent 1 autonome :
1. Prendre 1 campagne `pending`
2. Créer campagne Smartlead (A/B/C)
3. Lancer scraping Outscraper avec callback webhook
4. Passer la campagne en `scraping`

## Fichiers impliqués
- `engine.py` (modifié si besoin pour robustesse/typing)
- `config.py` (inchangé pour l’instant)
- `email_templates.json` (injecté dans les variantes)
- `step.md` / `README.md` (docs à jour si changements)

## Plan détaillé

### 1. Audit code existant
- [x] Lire `engine.py`, `config.py`, `cleaner_api.py` (fait)
- [ ] Vérifier les champs obligatoires dans `email_templates.json`
- [ ] Lister les cas limites (rate limit 429, payload vide, webhook DOWN)

### 2. Robustesse minimale
- [ ] Ajouter `try/except` explicites sur chaque appel réseau
- [ ] Gérer 429 Outscraper : pause + Discord alerte + exit (déjà partiellement présent)
- [ ] Logger durée de chaque étape
- [ ] Vérifier que `webhook_url` est joignable avant lancement

### 3. Tests locaux
- [ ] `pytest` unitaire sur helpers (`_render_template`, `_load_templates`) si extraits
- [ ] Intégration manuelle :
  - Insérer une ligne `campaign_queue(status=pending)` en local
  - Lancer `engine.py` localement
  - Vérifier : création Smartlead OK, status passe à `scraping`, Discord notifié

### 4. Validation Render-ready
- [ ] Vérifier que `requirements.txt` contient `fastapi`, `pandas`, `supabase`, `requests` (OK)
- [ ] Confirmer la commande de run locale existante `python engine.py`

## Critères d’acceptation
- `engine.py` s’exécute sans erreur sur une campagne `pending`
- Création Smartlead réussie avec variantes
- Outscraper appelé avec `webhook=.../webhook/outscraper?queue_id=...`
-campagne en `scraping`
- Discord notifie “DÉBUT scraping”

## Risques
- Outscraper rate limiting fréquent : ajouter backoff exponentiel si nécessaire
- Webhook cible non joignable : ajouter check TCP avant lancement
- `email_templates.json` manquant : engine doit échouer proprement

## Open questions
- Faut-il ajouter un retry sur l’appel Outscraper ?
- Faut-il sérialiser l’engine via Render Cron direct plutôt que `/jobs/engine` ?
