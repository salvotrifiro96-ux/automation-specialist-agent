"""Automation Specialist Agent — Streamlit UI.

5 tab:
  - Setup: verifica connessione HubSpot + custom property + pool advisor
  - Forms: crea un nuovo form di acquisizione
  - Emails: importa copy del copywriter come Marketing Email draft
  - Workflows: crea workflow di assegnazione round-robin + sequenza nurturing
  - Stato: status report finale di cosa hai configurato in HubSpot
"""
from __future__ import annotations

import json
import os
import traceback
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from agent import emails as emails_mod
from agent import forms as forms_mod
from agent import owners as owners_mod
from agent import properties as props_mod
from agent import workflows as wf_mod
from agent.hubspot_api import HubSpotClient, HubSpotError
from agent.store import SupabaseStore


load_dotenv()


def _secret(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val:
        return val
    try:
        return st.secrets.get(key, default)
    except (FileNotFoundError, AttributeError):
        return default


APP_PASSWORD = _secret("APP_PASSWORD")
HUBSPOT_TOKEN = _secret("HUBSPOT_TOKEN")
HUBSPOT_PORTAL_ID = _secret("HUBSPOT_PORTAL_ID")

st.set_page_config(
    page_title="Automation Specialist Agent",
    layout="wide",
    page_icon="🔌",
)


# ── Password gate ──────────────────────────────────────────────────
def _password_gate() -> None:
    if not APP_PASSWORD:
        return
    if st.session_state.get("authed"):
        return
    st.title("🔌 Automation Specialist Agent")
    pw = st.text_input("Password", type="password", key="pw_input")
    if st.button("Entra"):
        if pw == APP_PASSWORD:
            st.session_state.authed = True
            st.rerun()
        else:
            st.error("Password errata")
    st.stop()


_password_gate()


# ── Session state ──────────────────────────────────────────────────
DEFAULT_STATE: dict[str, Any] = {
    "hub_client": None,
    "owner_pool": None,        # OwnerPool
    "property_status": None,   # PropertyStatus
    "last_form": None,         # dict response del form creato
    "last_emails": [],         # lista risposte create_marketing_email
    "last_workflows": [],      # lista risposte workflow create
}
for k, v in DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _hub() -> HubSpotClient | None:
    """Cache HubSpotClient in session_state."""
    if st.session_state.hub_client is not None:
        return st.session_state.hub_client
    if not HUBSPOT_TOKEN:
        return None
    try:
        client = HubSpotClient(HUBSPOT_TOKEN, HUBSPOT_PORTAL_ID)
        st.session_state.hub_client = client
        return client
    except Exception as e:
        st.error(f"Init HubSpot fallito: {e}")
        return None


def _store() -> SupabaseStore | None:
    if "_supabase_store" not in st.session_state:
        try:
            st.session_state._supabase_store = SupabaseStore.from_env()
        except Exception:
            st.session_state._supabase_store = None
    return st.session_state._supabase_store


# ── Sidebar ────────────────────────────────────────────────────────


def _sidebar() -> None:
    st.sidebar.header("🔌 Setup")

    if not HUBSPOT_TOKEN:
        st.sidebar.error("Manca `HUBSPOT_TOKEN`")
        return

    portal_label = HUBSPOT_PORTAL_ID or "?"
    st.sidebar.caption(f"Portal: `{portal_label}`")

    if not _store():
        st.sidebar.warning("Supabase non configurato (niente import copy).")

    # Custom property status
    if st.session_state.property_status is None:
        if st.sidebar.button("🧪 Verifica id_campagna_refresh", use_container_width=True):
            client = _hub()
            if client:
                try:
                    with st.spinner("Check property…"):
                        st.session_state.property_status = props_mod.ensure_refresh_property(client)
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Errore: {e}")
    else:
        ps = st.session_state.property_status
        if ps.created:
            st.sidebar.success(f"✓ property creata: `{ps.property.name}`")
        else:
            st.sidebar.success(f"✓ property esiste: `{ps.property.name}`")

    # Owner pool status
    if st.session_state.owner_pool is None:
        if st.sidebar.button("👥 Carica pool advisor", use_container_width=True):
            client = _hub()
            if client:
                try:
                    with st.spinner("Build pool…"):
                        st.session_state.owner_pool = owners_mod.build_owner_pool(client)
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Errore: {e}")
    else:
        pool = st.session_state.owner_pool
        matched = len(pool.matched_owner_ids)
        total = len(pool.matches)
        if matched == total:
            st.sidebar.success(f"✓ pool advisor: {matched}/{total}")
        else:
            st.sidebar.warning(f"⚠ pool advisor: {matched}/{total}")
            for m in pool.matches:
                if not m.is_matched:
                    st.sidebar.caption(f"  ✗ {m.advisor_name}")

    st.sidebar.divider()
    if st.sidebar.button("🔄 Reset tutto", use_container_width=True):
        for k in list(DEFAULT_STATE):
            st.session_state[k] = DEFAULT_STATE[k]
        st.rerun()


# ── Tab 1: Setup ───────────────────────────────────────────────────


def _render_setup_tab() -> None:
    st.subheader("⚙️ Setup iniziale")
    st.markdown(
        "L'agente parla con HubSpot. Prima di usare gli altri tab, "
        "verifica che:\n"
        "1. La connessione funziona (portal id `" + HUBSPOT_PORTAL_ID + "`)\n"
        "2. La custom property `id_campagna_refresh` esiste sui contatti\n"
        "3. I 10 advisor del team siano matchati come Owner HubSpot"
    )

    client = _hub()
    if client is None:
        st.error("Configura `HUBSPOT_TOKEN` nei secrets.")
        return

    # Verifica property
    st.markdown("### 1) Custom property `id_campagna_refresh`")
    if st.session_state.property_status is None:
        if st.button("🧪 Verifica / crea property", type="primary"):
            try:
                with st.spinner("Lookup HubSpot…"):
                    st.session_state.property_status = props_mod.ensure_refresh_property(client)
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")
    else:
        ps = st.session_state.property_status
        if ps.created:
            st.success(f"✅ Creata `{ps.property.name}` ({ps.property.field_type})")
        else:
            st.success(f"✅ Esiste già: `{ps.property.name}` ({ps.property.field_type})")
        with st.expander("Dettagli property"):
            st.json({
                "name": ps.property.name,
                "label": ps.property.label,
                "type": ps.property.type,
                "field_type": ps.property.field_type,
                "group": ps.property.group_name,
            })

    # Pool advisor
    st.markdown("### 2) Pool advisor round-robin")
    if st.session_state.owner_pool is None:
        if st.button("👥 Carica pool dei 10 advisor", type="primary"):
            try:
                with st.spinner("Lookup owner HubSpot…"):
                    st.session_state.owner_pool = owners_mod.build_owner_pool(client)
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")
    else:
        pool = st.session_state.owner_pool
        st.success(f"✅ Pool caricato: {len(pool.matched_owner_ids)}/{len(pool.matches)} advisor matchati")
        for m in pool.matches:
            if m.is_matched:
                st.markdown(
                    f"  - ✓ **{m.advisor_name}** -> "
                    f"`{m.owner.email}` (owner_id `{m.owner.id}`)"
                )
            else:
                st.markdown(f"  - ✗ **{m.advisor_name}** — NON trovato")


# ── Tab 2: Forms ───────────────────────────────────────────────────


def _render_forms_tab() -> None:
    st.subheader("📋 Crea form di acquisizione")
    st.caption(
        "Crea un form HubSpot nativo (embeddabile ovunque) con email + name "
        "+ telefono opzionali e `id_campagna_refresh` come hidden field."
    )

    client = _hub()
    if client is None:
        return

    with st.form("create_form"):
        cols = st.columns([2, 1])
        name = cols[0].text_input(
            "Nome del form (interno HubSpot)",
            placeholder="LP Dentisti — Liberati dalla poltrona",
        )
        default_campaign = cols[1].text_input(
            "Default id_campagna_refresh (opzionale)",
            placeholder="es. refresh_dentisti_2026_05",
            help=(
                "Se la landing carica una singola campagna, settalo qui. "
                "Altrimenti l'embed JS lo passera` come URL param."
            ),
        )

        cols2 = st.columns([1, 1])
        include_phone = cols2[0].checkbox("Includi campo telefono", value=True)
        include_lastname = cols2[1].checkbox("Includi campo cognome", value=True)

        submit_label = st.text_input("Testo bottone submit", value="Invia richiesta")
        success_message = st.text_area(
            "Messaggio post-submit (lascia vuoto se usi redirect URL)",
            value="Grazie! Ti contatteremo entro 24 ore.",
            height=70,
        )
        redirect_url = st.text_input(
            "Redirect URL (opzionale, ha precedenza sul messaggio)",
            placeholder="https://leonemasterschool.com/thanks",
        )

        submitted = st.form_submit_button("✨ Crea form HubSpot", type="primary")

    if not submitted:
        return
    if not name.strip():
        st.error("Devi dare un nome al form.")
        return

    payload = forms_mod.build_form_payload(
        name=name,
        submit_button_label=submit_label,
        success_message=success_message,
        redirect_url=redirect_url.strip(),
        include_phone=include_phone,
        include_lastname=include_lastname,
        default_campaign_id=default_campaign.strip(),
    )
    try:
        with st.spinner("Creazione form HubSpot…"):
            resp = client.create_form(payload)
        st.session_state.last_form = resp
        st.success(f"✅ Form creato! id = `{resp.get('id')}`")
    except HubSpotError as e:
        st.error(f"Errore HubSpot: {e}")
        st.code(json.dumps(payload, indent=2), language="json")
    except Exception:
        st.error(traceback.format_exc())

    if st.session_state.last_form:
        st.divider()
        st.markdown("**Ultimo form creato**")
        st.json(st.session_state.last_form, expanded=False)


# ── Tab 3: Emails ──────────────────────────────────────────────────


def _render_emails_tab() -> None:
    st.subheader("📧 Importa copy come Marketing Email")
    st.caption(
        "Sfoglia gli output del copywriter (conferma + nurturing) e crea "
        "i corrispondenti Marketing Email in HubSpot (stato DRAFT)."
    )

    client = _hub()
    store = _store()
    if not client or not store:
        st.warning("Servono HubSpot + Supabase configurati.")
        return

    with st.expander("👤 Sender (chi firma le email)", expanded=True):
        cols = st.columns(2)
        from_name = cols[0].text_input(
            "From name",
            value="Salvo Trifirò",
            key="email_from_name",
        )
        from_email = cols[1].text_input(
            "From email (deve essere verificata su HubSpot)",
            value="info@leonemasterschool.com",
            key="email_from_email",
        )
        reply_to = st.text_input("Reply-to (opzionale)", key="email_reply_to")

    try:
        plans = emails_mod.list_importable_outputs(store)
    except Exception as e:
        st.error(f"Lettura Supabase fallita: {e}")
        return

    if not plans:
        st.info(
            "Nessun output `confirmation_mail` / `nurturing_*` in Supabase. "
            "Genera prima qualcosa col copywriter."
        )
        return

    st.markdown(f"### {len(plans)} output disponibili")
    for plan in plans:
        with st.container(border=True):
            st.markdown(f"**{plan.output_title}**")
            st.caption(f"`{plan.subtype}` · {len(plan.drafts)} mail")

            with st.expander("Vedi le mail"):
                for d in plan.drafts:
                    st.markdown(f"**{d.name}**")
                    st.markdown(f"_Subject:_ {d.subject}")
                    st.markdown(f"_Preview:_ {d.preview}")
                    st.text(d.body_text[:500] + ("…" if len(d.body_text) > 500 else ""))
                    st.divider()

            if st.button(
                f"📥 Crea {len(plan.drafts)} draft in HubSpot",
                key=f"create_{plan.output_id}",
                type="primary",
            ):
                if not from_name.strip() or not from_email.strip():
                    st.error("Compila From name + From email")
                else:
                    try:
                        with st.spinner(f"Creo {len(plan.drafts)} email…"):
                            results = emails_mod.create_drafts(
                                client=client,
                                drafts=list(plan.drafts),
                                from_name=from_name,
                                from_email=from_email,
                                reply_to=reply_to or None,
                            )
                        st.session_state.last_emails.extend(results)
                        st.success(f"✅ Create {len(results)} email draft")
                        for r in results:
                            st.caption(f"  - id `{r.get('id')}` — {r.get('name')}")
                    except HubSpotError as e:
                        st.error(f"HubSpot error: {e}")
                    except Exception:
                        st.error(traceback.format_exc())


# ── Tab 4: Workflows ───────────────────────────────────────────────


def _render_workflows_tab() -> None:
    st.subheader("🔁 Crea workflow")
    st.caption(
        "Crea il workflow di assegnazione (round-robin advisor) e quello "
        "di nurturing (sequenza email) collegati a un form."
    )

    client = _hub()
    if client is None:
        return

    pool = st.session_state.owner_pool
    if pool is None:
        st.info("Carica prima il pool advisor (Setup tab).")
        return
    if not pool.matched_owner_ids:
        st.error("Pool advisor vuoto — non posso fare round-robin.")
        return

    # Pick form
    try:
        forms = client.list_forms()
    except Exception as e:
        st.error(f"Lettura forms fallita: {e}")
        return
    if not forms:
        st.warning("Nessun form trovato. Creane uno nel tab Forms.")
        return

    form_options = {f"{f.name} ({f.id})": f.id for f in forms if not f.archived}
    selected_form_label = st.selectbox(
        "Form trigger del workflow",
        options=list(form_options),
    )
    triggering_form_id = form_options[selected_form_label]

    # Pick confirmation email (optional)
    try:
        emails = client.list_marketing_emails(limit=100)
    except Exception as e:
        st.error(f"Lettura email fallita: {e}")
        emails = []
    email_options: dict[str, str] = {"— nessuna —": ""}
    for e in emails:
        eid = str(e.get("id", ""))
        nm = e.get("name", "")
        if eid and nm:
            email_options[f"{nm} ({eid})"] = eid

    # Workflow A: assegnazione + conferma
    st.markdown("### A) Assegnazione round-robin + conferma")
    with st.form("wf_assign"):
        wf_a_name = st.text_input(
            "Nome workflow",
            value=f"[AUTO] Assegnazione + conferma — {selected_form_label}",
        )
        chosen_conf_label = st.selectbox(
            "Email di conferma (opzionale)",
            options=list(email_options),
        )
        enabled = st.checkbox(
            "Attiva subito (consigliato lasciare disabilitato e rivedere in HubSpot)",
            value=False,
        )
        do_create_a = st.form_submit_button("✨ Crea workflow A", type="primary")

    if do_create_a:
        payload = wf_mod.build_assignment_workflow_payload(
            name=wf_a_name,
            triggering_form_id=triggering_form_id,
            owner_ids_round_robin=list(pool.matched_owner_ids),
            confirmation_email_id=email_options[chosen_conf_label] or None,
            enabled=enabled,
        )
        try:
            with st.spinner("Creazione workflow…"):
                resp = client.create_workflow(payload)
            st.success(f"✅ Workflow creato! id = `{resp.get('id')}`")
            st.session_state.last_workflows.append(resp)
        except HubSpotError as e:
            st.error(f"HubSpot rifiuta la creazione automatica: {e}")
            st.caption(
                "Probabile feature flag mancante sul portale. Sotto trovi la "
                "spec da ricreare manualmente in HubSpot Workflows UI."
            )
            st.markdown(wf_mod.render_workflow_spec_md(payload))
            with st.expander("JSON completo (per troubleshooting/import)"):
                st.code(json.dumps(payload, indent=2), language="json")

    # Workflow B: nurturing
    st.markdown("### B) Sequenza nurturing")
    if not emails:
        st.info("Per il workflow di nurturing servono email gia` create.")
        return

    n_steps = st.slider("Numero step nella sequenza", 1, 8, 4, key="wf_n_steps")
    sequence: list[dict[str, Any]] = []
    for i in range(n_steps):
        cols = st.columns([2, 1])
        elabel = cols[0].selectbox(
            f"Step {i + 1} — email",
            options=list(email_options),
            key=f"wf_step_email_{i}",
        )
        delay_h = cols[1].number_input(
            f"Step {i + 1} — delay (ore prima di mandare)",
            min_value=0,
            max_value=24 * 30,
            value=24 * (i + 1),
            key=f"wf_step_delay_{i}",
        )
        eid = email_options.get(elabel, "")
        if eid:
            sequence.append({"day": i + 1, "email_id": eid, "delay_hours": int(delay_h)})

    with st.form("wf_nurturing"):
        wf_b_name = st.text_input(
            "Nome workflow",
            value=f"[AUTO] Nurturing — {selected_form_label}",
            key="wf_b_name",
        )
        enabled_b = st.checkbox(
            "Attiva subito",
            value=False,
            key="wf_b_enabled",
        )
        do_create_b = st.form_submit_button("✨ Crea workflow B", type="primary")

    if do_create_b:
        if not sequence:
            st.error("Almeno UN step deve avere un'email valida.")
            return
        payload = wf_mod.build_nurturing_workflow_payload(
            name=wf_b_name,
            triggering_form_id=triggering_form_id,
            sequence=sequence,
            enabled=enabled_b,
        )
        try:
            with st.spinner("Creazione workflow…"):
                resp = client.create_workflow(payload)
            st.success(f"✅ Workflow creato! id = `{resp.get('id')}`")
            st.session_state.last_workflows.append(resp)
        except HubSpotError as e:
            st.error(f"HubSpot rifiuta la creazione automatica: {e}")
            st.markdown(wf_mod.render_workflow_spec_md(payload))
            with st.expander("JSON"):
                st.code(json.dumps(payload, indent=2), language="json")


# ── Tab 5: Stato ───────────────────────────────────────────────────


def _render_status_tab() -> None:
    st.subheader("📊 Status configurazione")

    ps = st.session_state.property_status
    if ps:
        st.success(f"Property `id_campagna_refresh` OK ({ps.property.field_type})")
    else:
        st.info("Property non ancora verificata.")

    pool = st.session_state.owner_pool
    if pool:
        matched = len(pool.matched_owner_ids)
        st.success(f"Pool advisor: {matched}/{len(pool.matches)} matchati")

    if st.session_state.last_form:
        st.info("Ultimo form creato:")
        st.json(st.session_state.last_form, expanded=False)

    if st.session_state.last_emails:
        st.info(f"Email create in questa sessione: {len(st.session_state.last_emails)}")
        for e in st.session_state.last_emails:
            st.caption(f"  - id `{e.get('id')}` — {e.get('name')}")

    if st.session_state.last_workflows:
        st.info(f"Workflow creati in questa sessione: {len(st.session_state.last_workflows)}")
        for w in st.session_state.last_workflows:
            st.caption(f"  - id `{w.get('id')}` — {w.get('name')}")


# ── Top-level ──────────────────────────────────────────────────────


def _main() -> None:
    _sidebar()

    st.title("🔌 Automation Specialist Agent")
    st.caption(
        "Configura HubSpot per il funnel Leone: custom property, forms, "
        "Marketing Email, workflow di assegnazione + nurturing. "
        "Stato sempre verificabile via API."
    )

    tab_setup, tab_forms, tab_emails, tab_wf, tab_status = st.tabs(
        ["⚙️ Setup", "📋 Forms", "📧 Emails", "🔁 Workflows", "📊 Stato"]
    )
    with tab_setup:
        _render_setup_tab()
    with tab_forms:
        _render_forms_tab()
    with tab_emails:
        _render_emails_tab()
    with tab_wf:
        _render_workflows_tab()
    with tab_status:
        _render_status_tab()


_main()
