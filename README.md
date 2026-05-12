# Automation Specialist Agent

Agente Streamlit del team marketing Leone — configura HubSpot a partire dagli output prodotti dagli altri agenti.

## Capabilities

- **⚙️ Setup**: verifica/crea la custom property `id_campagna_refresh` sui contatti + matcha i 10 advisor del team (Marvin/Domenico/...) con gli Owner HubSpot
- **📋 Forms**: crea un form HubSpot nativo con email + first/lastname + telefono + `id_campagna_refresh` hidden (valorizzato dal media-buyer / embed JS)
- **📧 Marketing Emails**: importa gli output del `copywriter-agent` (subtype `confirmation_mail`, `nurturing_sequence`, `nurturing_single`) come Marketing Email draft, traducendo i placeholder (`[Nome]` → `{{ contact.firstname }}`, ecc.)
- **🔁 Workflows v4**: crea due workflow
  - **A**: form submission → delay 1min → assegnazione round-robin tra advisor → invio email di conferma
  - **B**: form submission → sequenza nurturing (delay + email × N step)
- **📊 Stato**: report di tutto cio` che e` stato configurato in HubSpot dalla sessione

## Setup

```bash
cd automation-specialist-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Compila .env con HUBSPOT_TOKEN, SUPABASE_*, APP_PASSWORD
streamlit run app.py
```

### Scope HubSpot richiesti
Private App Token con:
- `crm.objects.contacts.read` / `.write`
- `crm.schemas.contacts.read` / `.write`
- `crm.objects.owners.read`
- `forms` (read + write)
- `automation` (per workflows v4)
- `content` (per Marketing Emails)

### Streamlit Cloud Secrets

```toml
APP_PASSWORD = "faraone.92"
HUBSPOT_TOKEN = "pat-na2-..."
HUBSPOT_PORTAL_ID = "140603915"
SUPABASE_URL = "https://fmzunwsrpgdexlwmkruy.supabase.co"
SUPABASE_SECRET_KEY = "sb_secret_..."
```

## Test

```bash
pytest
```

34 unit test su parsing, build payload, round-robin, placeholder swap.

## Pattern condivisi col team

- Stesso scaffold (Streamlit + python-dotenv + requests)
- Stessa password gate (`APP_PASSWORD`)
- Riusa `agent/store.py` (duplicato dai 3 agenti che scrivono — qui solo lettura)
- Niente Claude/OpenAI (puramente operativo come il media-buyer)

## Limiti noti (HubSpot API)

- **Workflows v4 (Flows) creation** e` parzialmente in beta. Se la POST `/automation/v4/flows` ritorna 400/501 per feature flag mancanti, l'app mostra la spec markdown + JSON pronti per configurazione manuale in HubSpot UI.
- **Marketing Email** creation richiede che `fromEmail` sia un indirizzo verificato sul Marketing Hub HubSpot. Se non lo e`, l'email viene creata in DRAFT ma non potra` essere pubblicata fino alla verifica del mittente.
- **Round-robin** non e` una action atomica HubSpot — usiamo `ROTATE_RECORD_TO_OWNER` con `staffIds` come pool.

## Struttura

```
app.py                 → Streamlit (5 tab)
agent/
  hubspot_api.py       → HubSpotClient (REST puro, no SDK)
  properties.py        → ensure id_campagna_refresh
  forms.py             → build_form_payload (v3 forms)
  owners.py            → match team Leone -> hubspot owner_id
  emails.py            → import copy copywriter -> marketing email
  workflows.py         → build_assignment / build_nurturing payload v4
  store.py             → SupabaseStore (riuso pattern)
tests/                 → pytest, 34 test
```
