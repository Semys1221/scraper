# Email Generator — Architecture & Workflow

## Concept

Un générateur de séquences d'emails multi-variantes (A/B/C) piloté par un fichier modèle + une table de variables par niche. Le CLI (l'IA) lit le modèle, résout les variables, génère les body finaux et push directement sur Smartlead.

## Architecture

```
email-generator/
├── email model.md              ← Source unique du template (prompt IA)
├── kinesitherapeute.md         ← Niche kinésithérapeutes
├── agent-immobilier.md         ← Niche agents immobiliers
├── conseiller-financier.md     ← Niche conseillers financiers
└── README.md                   ← Ce fichier
```

```
┌──────────────────────────────────────────────┐
│            email model.md                     │
│  Source unique de vérité pour la structure    │
│  (greeting, body, CTA, signature, sujets)     │
└────────────────────┬─────────────────────────┘
                     │ lit
                     ▼
┌──────────────────────────────────────────────┐
│  CLI (l'IA)                                  │
│                                              │
│  1. Parse le modèle .md                      │
│  2. Interroge niche_variable (Supabase)      │
│     pour résoudre les {variable}             │
│  3. Génère des variantes avec contraintes    │
│     (char count +20%/-0%, similar word count)│
│  4. Compose les body finaux                  │
│  5. Push → Smartlead                         │
└────────────────────┬─────────────────────────┘
                     │ push
                     ▼
┌──────────────────────────────────────────────┐
│  Smartlead                                   │
│  Stockage final des séquences rendues         │
│  + envoi des emails aux leads                │
└──────────────────────────────────────────────┘
```

## Tables Supabase

### `niche_variable` — 1 ligne = 1 niche, 1 colonne = 1 snippet

| Column | Type | Description |
|--------|------|-------------|
| `id` | `uuid` PK | |
| `niche` | `text` UNIQUE | Nom de la niche (ex: "agents immobiliers") |
| `niche_keyword_1` | `text` | Mot-clé sujet var. A |
| `niche_keyword_2` | `text` | Mot-clé sujet var. B |
| `niche_keyword_3` | `text` | Mot-clé sujet var. C |
| `niche_member` | `text` | Membre singulier (ex: "agent immobilier") |
| `objectif` | `text` | Objectif (ex: "réduire leurs impôts") |
| `pain_point` | `text` | Problème (ex: "perdent 30% de leur CA") |
| `methode` | `text` | Méthode (ex: "défiscalisation ciblée") |
| `timeline` | `text` | Durée (ex: "60 jours") |
| `created_at` | `timestamptz` | |
| `updated_at` | `timestamptz` | |

Les valeurs sont des **indicatifs** — le CLI produit des variantes avec un nombre de mots similaire.

### `campaign_settings` — Snapshot des configs Smartlead

| Column | Type | Description |
|--------|------|-------------|
| `smartlead_campaign_id` | `int` UNIQUE | ID Smartlead |
| `schedule` | `jsonb` | Créneau, timezone, limites |
| `settings` | `jsonb` | Tracking, stop, follow-up |
| `email_account_ids` | `int[]` | Comptes email liés |
| `raw` | `jsonb` | Snapshot brut |

## Variables résolues ailleurs

| Variable | Source |
|----------|--------|
| `{{phone_number}}` | Lead data (Smartlead natif) |
| `{{first_name}}` | Lead data (Smartlead natif) |
| `{{signature}}` | Compte email Smartlead (natif) |
| `demain` / `après-demain` | Date relative calculée |
| `[texte](url)` | Lien statique (engine-20m5.onrender.com) |

## Contraintes CLI

1. **Syntaxe globale** — la structure (greeting, body, CTA, signature) doit être préservée telle qu'écrite dans `email model.md`
2. **Character count** — chaque variante : tolérance **+20% max**, jamais en dessous (-0%)
3. **Word count similaire** — remplacer `pain_point` par des alternatives au même nombre de mots

## Workflow complet

```
1. L'utilisateur demande une séquence pour une niche
       │
2. CLI lit email model.md (le template)
       │
3. CLI interroge niche_variable WHERE niche = X
       │
4. CLI résout les {variable} → génère N variantes par email
       │
5. CLI push 1 campagne Smartlead avec les 7 steps :
       ├── Steps 1-2 : 3 variants (A/B/C)
       ├── Step 3 : 2 variants (A/B)
       └── Steps 4-7 : variant unique (A)
       │
6. CLI copie les settings + comptes email depuis la campagne source
       │
7. Mettre en pause la campagne après push
```

## Smartlead API — Format séquences

### Endpoint
```
POST /campaigns/{campaign_id}/sequences?api_key=KEY
```

### Format qui marche (Legacy API)

```json
{
  "sequences": [
    {
      "seq_number": 1,
      "seq_delay_details": { "delay_in_days": 0 },
      "subject": "Default subject",
      "email_body": "<p>Default body</p>",
      "seq_variants": [
        {
          "variant_label": "A",
          "subject": "Question {niche_keyword_1}",
          "email_body": "<p>Body variant A</p>"
        },
        {
          "variant_label": "B",
          "subject": "Question {niche_keyword_2}",
          "email_body": "<p>Body variant B</p>"
        },
        {
          "variant_label": "C",
          "subject": "Question {niche_keyword_3}",
          "email_body": "<p>Body variant C</p>"
        }
      ]
    }
  ]
}
```

### Règles
- wrapper obligatoire : `{"sequences": [...]}` (pas de tableau nu)
- clé des variantes : **`seq_variants`** (pas `variants`, pas `sequence_variants`)
- champs par variant : `variant_label`, `subject`, `email_body`
- pas de `variant_distribution_type` ni `distribution`
- `subject` et `email_body` requis au niveau sequence + dans chaque `seq_variants`

### Limitations de ce compte (Legacy API)
| Feature | Statut |
|---------|--------|
| `variants` (clé) | ❌ Utiliser `seq_variants` |
| Tableau nu `[...]` | ❌ Utiliser `{"sequences": [...]}` |
| `PATCH /settings` | ❌ Utiliser `POST /settings` |
| `parent_campaign_id` via API | ❌ Configurer dans le dashboard UI |
| PATCH/PUT `/status` | ❌ Utiliser `POST /status` avec `{"status": "PAUSED"}` |

## Structure campagne

Chaque génération crée **1 campagne Smartlead** avec les 7 steps séquentiels :

| Step | Day | Variantes |
|------|-----|-----------|
| 1 | J1 | A/B/C |
| 2 | J4 | A/B/C |
| 3 | J7 | A/B |
| 4 | J10 | A (unique) |
| 5 | J13 | A (unique) |
| 6 | J16 | A (unique) |
| 7 | J19 | A (unique) |

Settings copiés depuis la campagne source de référence (ID: 3441183) :
- fuseau : `Europe/Paris`, 7j/7, 08:00-18:00
- 10 min entre emails, 9000 leads/jour
- `stop_lead_settings: REPLY_TO_AN_EMAIL`
- `follow_up_percentage: 100`
- 30 email accounts liés

## Procédure UI : Ajouter des leads

Les leads sont ajoutés via l'API Smartlead ou manuellement dans le dashboard.

## Variables disponibles dans le modèle

### Custom (résolues via `niche_variable`)
- `{niche}` — nom de la niche
- `{niche_keyword_1}` / `{niche_keyword_2}` / `{niche_keyword_3}` — mots-clés sujet
- `{niche_member}` — membre singulier
- `{objectif}` — objectif
- `{pain_point}` — problème
- `{methode}` — méthode
- `{timeline}` — durée
- `(method_developped)` — description de la méthode

### Smartlead natives (résolues automatiquement)
- `{{phone_number}}` — téléphone du lead
- `{{first_name}}` — prénom du lead
- `{{signature}}` — signature configurée sur le compte email

## Campagnes actives

| Campagne | ID | Steps | Variants | Status |
|----------|----|-------|----------|--------|
| kinésithérapeute — Phase 1 | 3492797 | 7 steps (J1-J19) | ✅ A/B/C + A/B + A | PAUSED |
| agent immobilier — Phase 1 | 3492794 | 7 steps (J1-J19) | ✅ A/B/C + A/B + A | PAUSED |
| conseiller financier — Phase 1 | 3492795 | 7 steps (J1-J19) | ✅ A/B/C + A/B + A | PAUSED |
