# Automation Specialist Agent

Agente Streamlit del team marketing Leone — wizard a 4 step che configura HubSpot per una campagna in un unico flusso lineare.

## Scope

Una sola cosa, fatta bene: per ogni nuova campagna del funnel Leone, l'agente crea su HubSpot **form di acquisizione + mail di conferma + sequenza nurturing**, legati da un **unico workflow v4 (Flows)** che parte dal form submission.

## Wizard a 4 step

1. **Form** — nome, `id_campagna_refresh` (hidden field), toggle telefono/cognome, submit label, success message / redirect URL
2. **Conferma** — picker unificato: scegli tra mail già esistenti su HubSpot (📚) o bozze del [copywriter-agent](https://copywriter-agent.streamlit.app) salvate su Supabase (✍️ — subtype `confirmation_mail`)
3. **Nurturing** — slider N step (1-8); per ogni step picker (📚 / ✍️ subtype `nurturing_sequence` / `nurturing_single`) + delay ore
4. **Pubblica** — riepilogo, sender (richiesto solo se ci sono ✍️ da importare), nome workflow, toggle "attiva subito" (default OFF), bottone unico

Al click di "Crea tutto" l'agente esegue in sequenza:

1. Verifica/crea la custom property `id_campagna_refresh` (idempotente)
2. Crea il form HubSpot Marketing v3
3. Importa le ✍️ scelte come Marketing Email DRAFT (cache per non duplicare)
4. Crea il workflow v4 unico: `FORM_SUBMITTED → delay 1min → conferma → delay → step 1 → delay → step 2 → …`

Se la v4 Flows API rifiuta la creazione (feature flag mancante sul portal), l'agente mostra **spec markdown + JSON** per ricostruire il workflow a mano in HubSpot UI.

## Setup locale

```bash
cd automation-specialist-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Compila: HUBSPOT_TOKEN, HUBSPOT_PORTAL_ID, SUPABASE_URL, SUPABASE_SECRET_KEY, APP_PASSWORD
streamlit run app.py
```

### Scope HubSpot richiesti

Private App Token con:
- `crm.objects.contacts.read` / `.write`
- `crm.schemas.contacts.read` / `.write`
- `forms` (read + write)
- `automation` (workflows v4)
- `content` (Marketing Emails)

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

Unit test su parsing, build payload del workflow unificato, placeholder swap copywriter → HubSpot.

## Limiti noti (HubSpot API)

- **Workflows v4 (Flows)** in beta su alcuni portal — se la POST `/automation/v4/flows` ritorna 400/501, l'app mostra la spec da ricreare in UI.
- **Marketing Email**: `fromEmail` deve essere un indirizzo verificato sul Marketing Hub. Se non lo è, le email vengono create in DRAFT ma non possono essere pubblicate fino alla verifica.
- **Placeholder copywriter**: `[Nome]` → `{{ contact.firstname }}` (e simili) traduzione automatica. `[LINK]` resta letterale: l'operatore lo sostituisce in HubSpot UI con il link reale.

## Pattern condivisi col team

Stesso scaffold di `copywriter-agent`, `graphic-designer-agent`, `media-buyer-agent`:
- Streamlit + Password gate `APP_PASSWORD`
- `_secret(key)` helper env → `st.secrets`
- `agent/store.py` (REST Supabase, no SDK) — qui solo lettura, niente scrittura
- Niente Anthropic/OpenAI: puramente operativo, come il media-buyer

## Struttura

```
app.py                 → Streamlit wizard a 4 step
agent/
  hubspot_api.py       → HubSpotClient REST (forms, emails, workflows, properties)
  properties.py        → ensure id_campagna_refresh (idempotente)
  forms.py             → build_form_payload (Marketing v3)
  emails.py            → import copy copywriter → Marketing Email + picker FlatDraft
  workflows.py         → build_funnel_workflow_payload (workflow unico)
  store.py             → SupabaseStore (REST, lettura output copywriter)
tests/                 → pytest sui builder e parsing
```
