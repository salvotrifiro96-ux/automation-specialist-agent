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


# ── Tab 4: Workflows (con picker unificato HubSpot + copywriter) ────


_NO_EMAIL_KEY = "__none__"


def _build_email_picker_options(
    client: HubSpotClient,
    store: SupabaseStore | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, emails_mod.FlatDraft]]:
    """Costruisce le opzioni del picker email unificato.

    Ritorna:
      - options: dict label -> {"kind": "hubspot"|"copywriter"|"none", ...}
      - flats_by_key: cache delle FlatDraft del copywriter (key -> obj)
        per non doverle ricalcolare al submit.
    """
    options: dict[str, dict[str, Any]] = {
        "— nessuna —": {"kind": "none"},
    }

    # Email gia` in HubSpot
    try:
        existing = client.list_marketing_emails(limit=100)
    except Exception as e:
        st.warning(f"Lettura email HubSpot fallita: {e}")
        existing = []
    for e in existing:
        eid = str(e.get("id", ""))
        nm = (e.get("name") or "")
        if eid and nm:
            options[f"📚 HubSpot · {nm} ({eid})"] = {"kind": "hubspot", "id": eid}

    # Output copywriter (Supabase) — flat (1 entry per mail singola)
    flats_by_key: dict[str, emails_mod.FlatDraft] = {}
    if store:
        try:
            flats = emails_mod.list_individual_drafts(store, limit=50)
        except Exception as e:
            st.warning(f"Lettura copywriter Supabase fallita: {e}")
            flats = []
        for fd in flats:
            options[fd.picker_label] = {"kind": "copywriter", "key": fd.stable_key}
            flats_by_key[fd.stable_key] = fd

    return options, flats_by_key


def _resolve_email_choice(
    *,
    client: HubSpotClient,
    choice: dict[str, Any],
    flats_by_key: dict[str, emails_mod.FlatDraft],
    from_name: str,
    from_email: str,
    reply_to: str,
    created_cache: dict[str, str],
) -> str | None:
    """Da una scelta del picker, ritorna l'`email_id` HubSpot pronto da usare
    nel workflow. Se la scelta e` "copywriter", crea on-the-fly l'email
    in HubSpot e ritorna il nuovo id. `created_cache` evita di ricreare
    la stessa email piu` volte (es. stessa email in piu` step).
    """
    kind = choice.get("kind")
    if kind == "hubspot":
        return choice["id"]
    if kind != "copywriter":
        return None

    key = choice["key"]
    if key in created_cache:
        return created_cache[key]

    flat = flats_by_key.get(key)
    if flat is None:
        return None

    payload = emails_mod.build_email_payload(
        draft=flat.draft,
        from_name=from_name,
        from_email=from_email,
        reply_to=reply_to or None,
    )
    resp = client.create_marketing_email(payload)
    eid = str(resp.get("id", ""))
    if eid:
        created_cache[key] = eid
        st.session_state.last_emails.append(resp)
    return eid


def _render_workflows_tab() -> None:
    st.subheader("🔁 Crea workflow")
    st.caption(
        "Picker unificato: scegli email gia` in HubSpot (`📚`) oppure dei "
        "copy del copywriter (`✍️`). Le `✍️` vengono importate al volo "
        "come Marketing Email draft quando crei il workflow."
    )

    client = _hub()
    if client is None:
        return
    store = _store()

    pool = st.session_state.owner_pool
    if pool is None:
        st.info("Carica prima il pool advisor (Setup tab).")
        return
    if not pool.matched_owner_ids:
        st.error("Pool advisor vuoto — non posso fare round-robin.")
        return

    # Form trigger
    try:
        forms = client.list_forms()
    except Exception as e:
        st.error(f"Lettura forms fallita: {e}")
        return
    if not forms:
        st.warning("Nessun form trovato. Creane uno nel tab Forms.")
        return
    form_options = {f"{f.name} ({f.id})": f.id for f in forms if not f.archived}
    selected_form_label = st.selectbox("Form trigger del workflow", options=list(form_options))
    triggering_form_id = form_options[selected_form_label]

    # Picker email unificato (HubSpot + copywriter)
    email_options, flats_by_key = _build_email_picker_options(client, store)

    # Sender per email importate al volo
    with st.expander("👤 Sender (usato solo per le mail importate dal copywriter)", expanded=False):
        cols = st.columns(2)
        from_name = cols[0].text_input(
            "From name", value="Salvo Trifirò", key="wf_from_name",
        )
        from_email = cols[1].text_input(
            "From email (verificata su HubSpot)",
            value="info@leonemasterschool.com",
            key="wf_from_email",
        )
        reply_to = st.text_input("Reply-to (opzionale)", key="wf_reply_to")

    # ── Workflow A: trigger by property + assegnazione owner singolo ───
    st.markdown("### A) Assegnazione contatto + conferma")
    st.caption(
        "Scegli la condizione di ingresso (su qualunque property contact) e "
        "l'owner a cui assegnare. Opzionalmente invia un'email di conferma."
    )

    # Property list per il trigger
    try:
        properties = client.list_contact_properties()
    except Exception as e:
        st.error(f"Lettura properties fallita: {e}")
        return

    # Costruisco le opzioni property: preferisco mettere id_campagna_refresh
    # in cima per accesso rapido.
    sorted_props = sorted(
        properties,
        key=lambda p: (p.name != "id_campagna_refresh", p.label or p.name),
    )
    prop_options = {f"{p.label or p.name}  ({p.name})": p.name for p in sorted_props}

    # Owners list (tutti i 93 owner HubSpot, non solo i 10 advisor)
    try:
        all_owners = client.list_owners()
    except Exception as e:
        st.error(f"Lettura owners fallita: {e}")
        return
    owner_options = {
        f"{o.full_name or o.email}  ({o.email})  id={o.id}": o.id
        for o in all_owners
    }

    operator_options = {
        f"{label}  ({code})": code for code, label in wf_mod.PROPERTY_OPERATORS
    }

    with st.form("wf_assign_v2"):
        st.markdown("**Trigger** — il workflow parte quando un contatto matcha:")
        c1, c2 = st.columns([2, 2])
        prop_label = c1.selectbox("Property", options=list(prop_options))
        op_label = c2.selectbox("Operatore", options=list(operator_options))
        selected_operator = operator_options[op_label]
        value_needed = selected_operator not in wf_mod.OPERATORS_WITHOUT_VALUE
        trigger_value = st.text_input(
            "Valore da matchare",
            disabled=not value_needed,
            placeholder="es. refresh_dentisti_2026_05" if value_needed else "(non necessario)",
        )

        st.markdown("**Azione** — assegna il contatto a:")
        owner_label = st.selectbox(
            "Owner HubSpot",
            options=list(owner_options),
            help="Tutti gli owner del portal, non solo i 10 advisor del team.",
        )

        st.markdown("**Email di conferma** (opzionale)")
        chosen_conf_label = st.selectbox(
            "Email da inviare dopo l'assegnazione",
            options=list(email_options),
            help="📚 esistente in HubSpot · ✍️ da importare al volo dal copywriter",
        )

        cols = st.columns([3, 1])
        wf_a_name = cols[0].text_input(
            "Nome workflow",
            value="[AUTO] Assegnazione contatto",
        )
        delay_min = cols[1].number_input(
            "Delay iniziale (min)",
            min_value=0,
            max_value=60,
            value=1,
            help="Pausa prima dell'azione, utile per evitare race condition.",
        )
        enabled = st.checkbox(
            "Attiva subito (consigliato disabilitato — rivedi in HubSpot UI prima)",
            value=False,
        )

        do_create_a = st.form_submit_button("✨ Crea workflow A", type="primary")

    if do_create_a:
        if value_needed and not trigger_value.strip():
            st.error(f"L'operatore `{selected_operator}` richiede un valore.")
            return

        # Risolve email scelta (eventualmente importa dal copywriter)
        created_cache: dict[str, str] = {}
        try:
            with st.spinner("Preparazione email…"):
                conf_email_id = _resolve_email_choice(
                    client=client,
                    choice=email_options[chosen_conf_label],
                    flats_by_key=flats_by_key,
                    from_name=from_name,
                    from_email=from_email,
                    reply_to=reply_to,
                    created_cache=created_cache,
                )
        except HubSpotError as e:
            st.error(f"Import email dal copywriter fallito: {e}")
            return

        payload = wf_mod.build_assignment_v2_payload(
            name=wf_a_name,
            trigger_property_name=prop_options[prop_label],
            trigger_operator=selected_operator,
            trigger_value=trigger_value.strip(),
            target_owner_id=owner_options[owner_label],
            confirmation_email_id=conf_email_id or None,
            delay_minutes=int(delay_min),
            enabled=enabled,
        )
        if created_cache:
            st.info(f"Importate {len(created_cache)} email dal copywriter")
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
            with st.expander("JSON completo"):
                st.code(json.dumps(payload, indent=2), language="json")

    # ── Workflow B: sequenza nurturing ─────────────────────────────
    st.markdown("### B) Sequenza nurturing")
    n_steps = st.slider("Numero step nella sequenza", 1, 8, 4, key="wf_n_steps")

    step_choices: list[dict[str, Any]] = []
    step_delays: list[int] = []
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
        step_choices.append(email_options[elabel])
        step_delays.append(int(delay_h))

    with st.form("wf_nurturing"):
        wf_b_name = st.text_input(
            "Nome workflow",
            value=f"[AUTO] Nurturing — {selected_form_label}",
            key="wf_b_name",
        )
        enabled_b = st.checkbox("Attiva subito", value=False, key="wf_b_enabled")
        do_create_b = st.form_submit_button("✨ Crea workflow B", type="primary")

    if do_create_b:
        # Risolve ogni step in email_id (importa dal copywriter se serve)
        created_cache: dict[str, str] = {}
        sequence: list[dict[str, Any]] = []
        try:
            with st.spinner("Preparazione email della sequenza…"):
                for i, (choice, delay_h) in enumerate(zip(step_choices, step_delays)):
                    eid = _resolve_email_choice(
                        client=client,
                        choice=choice,
                        flats_by_key=flats_by_key,
                        from_name=from_name,
                        from_email=from_email,
                        reply_to=reply_to,
                        created_cache=created_cache,
                    )
                    if eid:
                        sequence.append(
                            {"day": i + 1, "email_id": eid, "delay_hours": delay_h}
                        )
        except HubSpotError as e:
            st.error(f"Import email dal copywriter fallito: {e}")
            return

        if not sequence:
            st.error("Almeno UN step deve avere un'email valida.")
            return
        if created_cache:
            st.info(f"Importate {len(created_cache)} email dal copywriter")

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
