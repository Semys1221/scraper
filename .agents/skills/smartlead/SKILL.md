---
name: smartlead
description: "Smartlead cold email platform API. Use whenever the user asks about Smartlead, creating/managing campaigns, importing leads, fetching analytics, managing email accounts, sequences, webhooks, or any integration with Smartlead's API. Trigger on keywords: Smartlead API, campaign analytics, push leads, email accounts, warmup, sequences, webhook, cold email, outreach automation."
---

# Smartlead API

Smartlead is a cold email outreach platform. The API lets you automate campaign creation, lead management, email accounts, sequences, and analytics.

## Base URL & Auth

```
https://server.smartlead.ai/api/v1
```

Pass API key as query param on every request:
```
?api_key=YOUR_API_KEY
```

Rate limits vary by plan. On `429` implement exponential backoff.

---

## Quick Reference: All Endpoints

### Campaigns

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/campaigns/create` | Create campaign (starts DRAFTED) |
| GET | `/campaigns/` | List all campaigns |
| GET | `/campaigns/{id}` | Get campaign by ID |
| PATCH | `/campaigns/{id}/status` | Update status (START/PAUSED/STOPPED) |
| POST | `/campaigns/{id}/schedule` | Set sending schedule |
| POST | `/campaigns/{id}/settings` | Update general settings |
| GET | `/campaigns/{id}/sequences` | Fetch sequences |
| POST | `/campaigns/{id}/sequences` | Save sequences |
| DELETE | `/campaigns/{id}` | Delete campaign |
| GET | `/campaigns/{id}/email-accounts` | List email accounts per campaign |
| POST | `/campaigns/{id}/email-accounts` | Add email accounts to campaign |
| DELETE | `/campaigns/{id}/email-accounts` | Remove email accounts from campaign |

### Leads

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/campaigns/{id}/leads` | List leads by campaign |
| POST | `/campaigns/{id}/leads` | Add leads (max 400/req) |
| POST | `/campaigns/{id}/leads/{lead_id}` | Update lead |
| DELETE | `/campaigns/{id}/leads/{lead_id}` | Delete lead |
| POST | `/campaigns/{id}/leads/{lead_id}/pause` | Pause lead |
| POST | `/campaigns/{id}/leads/{lead_id}/resume` | Resume lead |
| POST | `/campaigns/{id}/leads/{lead_id}/unsubscribe` | Unsubscribe from campaign |
| POST | `/leads/{lead_id}/unsubscribe` | Unsubscribe globally |
| POST | `/leads/add-domain-block-list` | Block email or domain |
| GET | `/leads/` | Fetch lead by email (`?email=`) |
| GET | `/leads/{lead_id}/campaigns` | Campaigns by lead ID |
| GET | `/campaigns/{id}/leads/{lead_id}/message-history` | Message thread |
| POST | `/campaigns/{id}/reply-email-thread` | Reply to lead |
| GET | `/campaigns/{id}/leads-export` | Export leads CSV |

### Email Accounts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/email-accounts/` | List all email accounts |
| POST | `/email-accounts/save` | Create email account |
| POST | `/email-accounts/{id}` | Update email account |
| GET | `/email-accounts/{id}/` | Get by ID |
| POST | `/email-accounts/{id}/warmup` | Configure warmup |
| GET | `/email-accounts/{id}/warmup-stats` | Warmup stats (last 7 days) |

### Analytics

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/campaigns/{id}/analytics` | Top-level campaign analytics |
| GET | `/campaigns/{id}/statistics` | Detailed email-level stats |
| GET | `/campaigns/{id}/analytics-by-date` | Analytics by date range (max 30 days) |
| GET | `/analytics/overview` | Global analytics across all campaigns |

### Webhooks

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/webhooks` | Create webhook |
| GET | `/webhooks` | List webhooks |
| PUT | `/api/v1/webhook/update/:webhook_id` | Update webhook |
| DELETE | `/webhooks/{id}` | Delete webhook |

---

## Endpoint Details

### Campaign Management

#### Create Campaign
```
POST /campaigns/create?api_key=YOUR_API_KEY
```
Body:
```json
{ "name": "Q1 Cold Outreach", "client_id": null }
```
Creates in `DRAFTED` status. Returns `{ "ok": true, "id": 125, "name": "...", "created_at": "..." }`.

**Next steps:** Add sequences → email accounts → leads → schedule → settings → start.

#### List Campaigns
```
GET /campaigns/?api_key=YOUR_API_KEY&include_tags=true&client_id=123
```
Returns direct array of campaign objects (not wrapped). Optional filters: `client_id`, `include_tags`.

#### Get Campaign by ID
```
GET /campaigns/{campaign_id}?api_key=YOUR_API_KEY
```
Returns full campaign config.

#### Update Campaign Status
```
PATCH /campaigns/{campaign_id}/status?api_key=YOUR_API_KEY
Body: { "status": "START" }
```
Valid values: `START` (activate/resume), `PAUSED`, `STOPPED` (permanent).

**Campaign statuses:** `ACTIVE`, `PAUSED`, `STOPPED`, `ARCHIVED`, `DRAFTED`.

#### Update Campaign Schedule
```
POST /campaigns/{campaign_id}/schedule?api_key=YOUR_API_KEY
Body: {
  "timezone": "America/New_York",
  "days_of_the_week": [1,2,3,4,5],
  "start_hour": "09:00",
  "end_hour": "19:00",
  "min_time_btw_emails": 24,
  "max_leads_per_day": 100
}
```

#### Update Campaign Settings
```
POST /campaigns/{campaign_id}/settings?api_key=YOUR_API_KEY
Body: {
  "track_settings": [],
  "stop_lead_settings": "REPLY_TO_AN_EMAIL",
  "unsubscribe_text": "...",
  "send_as_plain_text": false,
  "follow_up_percentage": 20,
  "enable_ai_esp_matching": true,
  "client_id": null
}
```

#### Save Sequences
```
POST /campaigns/{campaign_id}/sequences?api_key=YOUR_API_KEY
Body: [
  {
    "seq_number": 1,
    "seq_delay_details": { "delay_in_days": 0 },
    "variant_distribution_type": "MANUALLY_EQUAL",
    "variants": [
      {
        "subject": "Quick question, {{first_name}}",
        "email_body": "<p>Hi {{first_name}},</p><p>...</p>",
        "variant_label": "A"
      }
    ]
  }
]
```

#### Add Email Accounts to Campaign
```
POST /campaigns/{campaign_id}/email-accounts?api_key=YOUR_API_KEY
Body: { "email_account_ids": [456, 457, 458] }
```

---

### Lead Management

#### Add Leads to Campaign (max 400/req)
```
POST /campaigns/{campaign_id}/leads?api_key=YOUR_API_KEY
Body: {
  "lead_list": [
    {
      "email": "john@example.com",
      "first_name": "John",
      "last_name": "Smith",
      "company_name": "Acme Corp",
      "phone_number": "+1234567890",
      "website": "https://acme.com",
      "location": "New York, USA",
      "linkedin_profile": "https://linkedin.com/in/johnsmith",
      "company_url": "https://acme.com",
      "custom_fields": { "job_title": "VP of Sales", "industry": "SaaS" }
    }
  ],
  "settings": {
    "ignore_global_block_list": false,
    "ignore_unsubscribe_list": false,
    "ignore_community_bounce_list": false,
    "ignore_duplicate_leads_in_other_campaign": false
  }
}
```

Line breaks are supported in email bodies.

#### Lead Statuses
`STARTED` — scheduled to begin; `INPROGRESS` — received at least one email; `COMPLETED` — received all emails; `BLOCKED` — bounced or blocklisted.

#### List Leads by Campaign
```
GET /campaigns/{campaign_id}/leads?api_key=YOUR_API_KEY&offset=0&limit=100
```

#### Export Campaign Leads to CSV
```
GET /campaigns/{campaign_id}/leads-export?api_key=YOUR_API_KEY
```
CSV columns: `id`, `campaign_lead_map_id`, `status`, `created_at`, `first_name`, `last_name`, `email`, `phone_number`, `company_name`, `website`, `location`, `custom_fields`, `linkedin_profile`, `company_url`, `is_unsubscribed`, `last_email_sequence_sent`, `is_interested`, `open_count`, `click_count`, `reply_count`.

---

### Email Accounts

#### Create Email Account
```
POST /email-accounts/save?api_key=YOUR_API_KEY
Body: {
  "from_name": "John Smith",
  "from_email": "john@gmail.com",
  "username": "john@gmail.com",
  "password": "app_password",
  "smtp_host": "smtp.gmail.com",
  "smtp_port": 587,
  "smtp_port_type": "TLS",
  "imap_host": "imap.gmail.com",
  "imap_port": 993,
  "max_email_per_day": 50,
  "custom_tracking_url": null,
  "bcc": null,
  "signature": null
}
```

#### Configure Warmup
```
POST /email-accounts/{email_account_id}/warmup?api_key=YOUR_API_KEY
Body: {
  "warmup_enabled": true,
  "total_warmup_per_day": 20,
  "daily_rampup": 2,
  "reply_rate_percentage": 30
}
```

#### Get Warmup Stats
```
GET /email-accounts/{email_account_id}/warmup-stats?api_key=YOUR_API_KEY
```
Returns last 7 days: sent count, spam placement, inbox placement.

---

### Analytics

#### Get Campaign Analytics (top-level)
```
GET /campaigns/{campaign_id}/analytics?api_key=YOUR_API_KEY
```
Response:
```json
{
  "campaign_id": 123,
  "campaign_name": "Q1 Outreach",
  "total_sent": 1000,
  "total_opened": 450,
  "total_clicked": 120,
  "total_replied": 85,
  "open_rate": 45.0,
  "click_rate": 12.0,
  "reply_rate": 8.5,
  "bounce_rate": 2.0,
  "unsubscribe_rate": 0.5
}
```

The legacy endpoint (used in this codebase) also returns `total_replies`, `auto_replies`, plus additional fields.

#### Get Campaign Statistics (detailed)
```
GET /campaigns/{campaign_id}/statistics?api_key=YOUR_API_KEY&offset=0&limit=100
```
Optional filters: `email_sequence_number` (1-20), `email_status` (opened/clicked/replied/bounced), `sent_time_start_date`, `sent_time_end_date`.

Aggregated response:
```json
{
  "success": true,
  "data": {
    "campaign_id": 123,
    "total_leads": 5240,
    "contacted": 4128,
    "opened": 1236,
    "clicked": 412,
    "replied": 312,
    "bounced": 58,
    "unsubscribed": 24,
    "open_rate": 29.9,
    "click_rate": 9.98,
    "reply_rate": 7.56
  }
}
```

#### Analytics by Date Range (max 30 days)
```
GET /campaigns/{campaign_id}/analytics-by-date?api_key=YOUR_API_KEY&start_date=2024-01-01&end_date=2024-01-30
```

#### Global Analytics Overview
```
GET /analytics/overview?api_key=YOUR_API_KEY
```
Across all campaigns: aggregate sent/open/click/reply counts, sentiment breakdown, domain health, provider comparison.

---

### Webhooks

```
POST /webhooks  — Create webhook
GET /webhooks   — List webhooks
PUT /api/v1/webhook/update/:webhook_id  — Update webhook
DELETE /webhooks/{webhook_id}  — Delete webhook
```

Common events: email reply received, email bounced, lead unsubscribed, campaign completed, lead status changed.

---

## Error Handling

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request — check body/params |
| 401 | Unauthorized — bad API key |
| 404 | Resource not found |
| 422 | Validation error — check parameter types |
| 429 | Rate limit exceeded — backoff and retry |
| 500 | Server error — retry after delay |
| 503 | Service unavailable — retry after delay |

On `429`, wait at least 2 seconds before retrying. Use exponential backoff.

---

## Integration in this Codebase

The Outreach System uses the following Smartlead API functions (in `config.py`):

- **`create_smartlead_campaign(name, variants)`** — POST `/campaigns/create`, then POST `/campaigns/{id}/sequences`
- **`push_to_smartlead(campaign_id, leads)`** — POST `/campaigns/{campaign_id}/leads` (max 400 leads/req)
- **`get_smartlead_analytics(campaign_id)`** — GET `/campaigns/{campaign_id}/analytics`
- **`pause_smartlead_campaign(campaign_id)`** — PATCH `/campaigns/{campaign_id}/status` with `{"status": "pause"}`

The `campaign_analytics` Supabase table stores snapshot data from `get_smartlead_analytics()` for historical tracking.
