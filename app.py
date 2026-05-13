"""Automation Specialist Agent — wizard a 4 step.

Configura HubSpot per il funnel Leone:
  Step 1 · Form        -> crea form Marketing v3 con id_campagna_refresh hidden
  Step 2 · Conferma    -> picker (HubSpot esistenti / copywriter Supabase)
  Step 3 · Nurturing   -> sequenza N step, picker per ognuno
  Step 4 · Pubblica    -> ensure property, crea form, importa email
                          dal copywriter, crea workflow unico v4.
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
    "step": "form",
    "form_data": None,          # dict raccolto nello step 1
    "confirmation_choice": None,  # dict {kind, id|key, label}
    "nurturing_steps": [],       # list[dict {choice, delay_hours}]
    "sender": {"from_name": "", "from_email": "", "reply_to": ""},
    "result": None,              # dict popolato dopo publish
    "error": None,
}
for k, v in DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v


def _set_step(s: str) -> None:
    st.session_state.step = s
    st.session_state.error = None


def _reset_wizard() -> None:
    for k, v in DEFAULT_STATE.items():
        # deep copy implicito sui dict/list mutabili
        st.session_state[k] = (
            v.copy() if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)
        )


# ── Resources cached in session ────────────────────────────────────


def _hub() -> HubSpotClient | None:
    if "_hub_client" in st.session_state:
        return st.session_state._hub_client
    if not HUBSPOT_TOKEN:
        return None
    try:
        client = HubSpotClient(HUBSPOT_TOKEN, HUBSPOT_PORTAL_ID)
        st.session_state._hub_client = client
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


# ── Email picker (HubSpot + copywriter, unificato) ─────────────────


_NO_EMAIL_KEY = "— nessuna —"


def _build_email_picker(
    *,
    client: HubSpotClient,
    store: SupabaseStore | None,
    allow_none: bool,
    subtype_filter: tuple[str, ...],
) -> tuple[dict[str, dict[str, Any]], dict[str, emails_mod.FlatDraft]]:
    """Costruisce le opzioni del picker email unificato.

    Args:
        allow_none: se True include l'opzione "— nessuna —" (utile per la
            conferma quando l'operatore vuole saltarla)
        subtype_filter: tupla dei subtype copywriter da includere
            (es. ("confirmation_mail",) per lo step 2; ("nurturing_sequence",
            "nurturing_single") per lo step 3)

    Returns:
        (options, flats_by_key) — options chiave-valore label->scelta;
        flats_by_key cache delle FlatDraft del copywriter.
    """
    options: dict[str, dict[str, Any]] = {}
    if allow_none:
        options[_NO_EMAIL_KEY] = {"kind": "none"}

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

    # Output copywriter (Supabase) filtrati per subtype
    flats_by_key: dict[str, emails_mod.FlatDraft] = {}
    if store:
        try:
            flats = emails_mod.list_individual_drafts(store, limit=50)
        except Exception as e:
            st.warning(f"Lettura copywriter Supabase fallita: {e}")
            flats = []
        for fd in flats:
            if fd.plan_subtype not in subtype_filter:
                continue
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
    """Da una scelta del picker, ritorna l'email_id HubSpot pronto da usare.

    Se la scelta e` "copywriter", crea on-the-fly l'email in HubSpot e
    ritorna il nuovo id. ``created_cache`` evita di ricreare la stessa
    email piu` volte (es. stessa email in piu` step nurturing).
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
    return eid


def _has_copywriter_choices() -> bool:
    """True se qualunque scelta nel wizard richiede un sender (✍️ copywriter)."""
    conf = st.session_state.confirmation_choice
    if conf and conf.get("kind") == "copywriter":
        return True
    for s in st.session_state.nurturing_steps:
        if (s.get("choice") or {}).get("kind") == "copywriter":
            return True
    return False


def _draft_preview(flat: emails_mod.FlatDraft) -> None:
    """Mostra preview body / subject di una ✍️ scelta."""
    d = flat.draft
    st.caption(f"_Subject:_ {d.subject}")
    if d.preview:
        st.caption(f"_Preview:_ {d.preview}")
    st.text(d.body_text[:600] + ("…" if len(d.body_text) > 600 else ""))
    if d.signature:
        st.caption(f"_Signature:_ {d.signature}")


# ── Top bar progress ───────────────────────────────────────────────


_STEPS = [
    ("form", "1 · Form"),
    ("confirmation", "2 · Conferma"),
    ("nurturing", "3 · Nurturing"),
    ("publish", "4 · Pubblica"),
]


def _render_progress() -> None:
    current = st.session_state.step
    bits: list[str] = []
    for code, label in _STEPS:
        if code == current:
            bits.append(f"**▸ {label}**")
        else:
            bits.append(f"  {label}")
    st.caption("  →  ".join(bits))


# ── Step 1: Form ───────────────────────────────────────────────────


def _step_form() -> None:
    st.subheader("Step 1 · Form di acquisizione")
    st.caption(
        "Crea il form HubSpot nativo per questa campagna. Il valore di "
        "`id_campagna_refresh` che inserisci qui sara` salvato come hidden "
        "field del form: quando un contatto si iscrive, HubSpot setta "
        "automaticamente questa property e il workflow dello step 4 "
        "scattera`."
    )

    fd = st.session_state.form_data or {}

    with st.form("form_step"):
        name = st.text_input(
            "Nome del form (interno HubSpot)",
            value=fd.get("name", ""),
            placeholder="LP Dentisti — Liberati dalla poltrona",
        )
        campaign_id = st.text_input(
            "id_campagna_refresh per questa campagna",
            value=fd.get("default_campaign_id", ""),
            placeholder="es. refresh_dentisti_2026_05",
            help=(
                "Identificatore univoco della campagna. Viene salvato come "
                "hidden field del form e usato come segmentazione nei workflow."
            ),
        )

        cols = st.columns(2)
        include_lastname = cols[0].checkbox(
            "Includi campo cognome",
            value=fd.get("include_lastname", True),
        )
        include_phone = cols[1].checkbox(
            "Includi campo telefono",
            value=fd.get("include_phone", True),
        )

        submit_label = st.text_input(
            "Testo bottone submit",
            value=fd.get("submit_button_label", "Invia richiesta"),
        )
        success_message = st.text_area(
            "Messaggio post-submit (lascia vuoto se usi redirect URL)",
            value=fd.get("success_message", "Grazie! Ti contatteremo entro 24 ore."),
            height=70,
        )
        redirect_url = st.text_input(
            "Redirect URL (opzionale — ha precedenza sul messaggio)",
            value=fd.get("redirect_url", ""),
            placeholder="https://leonemasterschool.com/thanks",
        )

        submitted = st.form_submit_button("Avanti →", type="primary")

    if not submitted:
        return

    missing = [k for k, v in {"Nome": name, "id_campagna_refresh": campaign_id}.items() if not v.strip()]
    if missing:
        st.error(f"Mancano: {', '.join(missing)}")
        return

    st.session_state.form_data = {
        "name": name.strip(),
        "default_campaign_id": campaign_id.strip(),
        "include_lastname": include_lastname,
        "include_phone": include_phone,
        "submit_button_label": submit_label.strip() or "Invia richiesta",
        "success_message": success_message.strip(),
        "redirect_url": redirect_url.strip(),
    }
    _set_step("confirmation")
    st.rerun()


# ── Step 2: Conferma ───────────────────────────────────────────────


def _step_confirmation() -> None:
    st.subheader("Step 2 · Mail di conferma")
    st.caption(
        "Scegli la mail che il contatto ricevera` subito dopo l'iscrizione. "
        "Puoi prendere una mail gia` presente in HubSpot (📚) oppure una "
        "bozza prodotta dal copywriter-agent (✍️) — quest'ultima viene "
        "importata come Marketing Email DRAFT al momento della pubblicazione."
    )

    client = _hub()
    if client is None:
        st.error("Configura `HUBSPOT_TOKEN`.")
        return
    store = _store()

    options, flats_by_key = _build_email_picker(
        client=client,
        store=store,
        allow_none=True,
        subtype_filter=("confirmation_mail",),
    )

    # Trova la label attualmente selezionata (per round-trip)
    current = st.session_state.confirmation_choice
    default_index = 0
    if current:
        for i, label in enumerate(options):
            opt = options[label]
            if opt.get("kind") == current.get("kind") and (
                opt.get("id") == current.get("id") or opt.get("key") == current.get("key")
            ):
                default_index = i
                break

    chosen_label = st.selectbox(
        "Mail di conferma",
        options=list(options),
        index=default_index,
        help="📚 = gia` in HubSpot · ✍️ = bozza dal copywriter da importare",
    )
    choice = dict(options[chosen_label])
    choice["label"] = chosen_label

    # Preview se ✍️
    if choice.get("kind") == "copywriter":
        flat = flats_by_key.get(choice["key"])
        if flat:
            with st.expander("Anteprima mail copywriter", expanded=True):
                _draft_preview(flat)

    cols = st.columns([1, 1, 4])
    if cols[0].button("← Indietro"):
        _set_step("form")
        st.rerun()
    if cols[1].button("Avanti →", type="primary"):
        st.session_state.confirmation_choice = choice
        _set_step("nurturing")
        st.rerun()


# ── Step 3: Nurturing ──────────────────────────────────────────────


def _step_nurturing() -> None:
    st.subheader("Step 3 · Sequenza nurturing")
    st.caption(
        "Costruisci la sequenza di mail che parte dopo la conferma. "
        "Ogni step pesca da HubSpot (📚) o dalle bozze del copywriter (✍️). "
        "Il delay e` rispetto allo step precedente (in ore)."
    )

    client = _hub()
    if client is None:
        st.error("Configura `HUBSPOT_TOKEN`.")
        return
    store = _store()

    options, flats_by_key = _build_email_picker(
        client=client,
        store=store,
        allow_none=True,
        subtype_filter=("nurturing_sequence", "nurturing_single"),
    )

    current_steps = st.session_state.nurturing_steps or []
    default_n = max(1, len(current_steps)) if current_steps else 4
    n_steps = st.slider(
        "Numero di step nella sequenza",
        min_value=1,
        max_value=8,
        value=default_n,
        key="wf_n_steps",
    )

    new_steps: list[dict[str, Any]] = []
    for i in range(n_steps):
        with st.container(border=True):
            st.markdown(f"**Step {i + 1}**")
            prev = current_steps[i] if i < len(current_steps) else {}

            # Default index del picker per round-trip
            default_index = 0
            prev_choice = prev.get("choice") or {}
            if prev_choice:
                for idx, label in enumerate(options):
                    opt = options[label]
                    if opt.get("kind") == prev_choice.get("kind") and (
                        opt.get("id") == prev_choice.get("id")
                        or opt.get("key") == prev_choice.get("key")
                    ):
                        default_index = idx
                        break

            cols = st.columns([3, 1])
            chosen_label = cols[0].selectbox(
                f"Mail · Step {i + 1}",
                options=list(options),
                index=default_index,
                key=f"wf_step_email_{i}",
                label_visibility="collapsed",
            )
            delay_h = cols[1].number_input(
                "Delay (ore)",
                min_value=0,
                max_value=24 * 30,
                value=int(prev.get("delay_hours", 24 * (i + 1))),
                key=f"wf_step_delay_{i}",
            )
            choice = dict(options[chosen_label])
            choice["label"] = chosen_label

            if choice.get("kind") == "copywriter":
                flat = flats_by_key.get(choice["key"])
                if flat:
                    with st.expander("Anteprima mail copywriter"):
                        _draft_preview(flat)

            new_steps.append({"choice": choice, "delay_hours": int(delay_h)})

    st.session_state.nurturing_steps = new_steps

    n_valid = sum(1 for s in new_steps if (s["choice"]).get("kind") != "none")
    if n_valid == 0:
        st.info(
            "Tutti gli step sono '— nessuna —'. Puoi proseguire: il workflow "
            "avra` solo la mail di conferma, niente sequenza nurturing."
        )

    cols = st.columns([1, 1, 4])
    if cols[0].button("← Indietro"):
        _set_step("confirmation")
        st.rerun()
    if cols[1].button("Avanti →", type="primary"):
        _set_step("publish")
        st.rerun()


# ── Step 4: Pubblica ───────────────────────────────────────────────


def _step_publish() -> None:
    st.subheader("Step 4 · Riepilogo e pubblica")

    fd = st.session_state.form_data or {}
    conf = st.session_state.confirmation_choice or {"kind": "none", "label": _NO_EMAIL_KEY}
    nurt_steps = st.session_state.nurturing_steps or []

    # Riepilogo
    with st.container(border=True):
        st.markdown(f"**Form**: `{fd.get('name', '?')}`")
        st.markdown(f"**id_campagna_refresh**: `{fd.get('default_campaign_id', '?')}`")
        campi = ["email", "firstname"]
        if fd.get("include_lastname"):
            campi.append("lastname")
        if fd.get("include_phone"):
            campi.append("phone")
        campi.append(f"{props_mod.REFRESH_PROPERTY_NAME} (hidden)")
        st.caption("Campi del form: " + ", ".join(f"`{c}`" for c in campi))

    with st.container(border=True):
        st.markdown(f"**Mail di conferma**: {conf.get('label', '—')}")

    with st.container(border=True):
        valid = [s for s in nurt_steps if (s["choice"]).get("kind") != "none"]
        st.markdown(f"**Sequenza nurturing**: {len(valid)} mail")
        for i, s in enumerate(nurt_steps, 1):
            label = (s["choice"]).get("label", "—")
            st.caption(f"  Step {i}: {label} — delay {s['delay_hours']}h")

    needs_sender = _has_copywriter_choices()
    sender = dict(st.session_state.sender)

    if needs_sender:
        st.markdown("### Sender (per le mail ✍️ importate dal copywriter)")
        cols = st.columns(2)
        sender["from_name"] = cols[0].text_input(
            "From name",
            value=sender.get("from_name", ""),
            placeholder="Es. Salvo Trifirò",
        )
        sender["from_email"] = cols[1].text_input(
            "From email (verificata su HubSpot)",
            value=sender.get("from_email", ""),
            placeholder="info@leonemasterschool.com",
        )
        sender["reply_to"] = st.text_input(
            "Reply-to (opzionale)",
            value=sender.get("reply_to", ""),
        )
        st.session_state.sender = sender

    # Workflow
    st.markdown("### Workflow HubSpot")
    cols = st.columns([3, 1])
    workflow_name = cols[0].text_input(
        "Nome workflow",
        value=f"[AUTO] {fd.get('name', 'Funnel')}",
    )
    enabled = cols[1].checkbox(
        "Attiva subito",
        value=False,
        help="Consigliato OFF: rivedi il workflow in HubSpot UI prima di attivare.",
    )

    if st.session_state.error:
        st.error(st.session_state.error)

    cols = st.columns([1, 1, 4])
    if cols[0].button("← Indietro"):
        _set_step("nurturing")
        st.rerun()
    if cols[1].button("🚀 Crea tutto", type="primary"):
        if needs_sender and (not sender.get("from_name") or not sender.get("from_email")):
            st.error("Sender obbligatorio (from_name + from_email) per importare le mail dal copywriter.")
            return
        _do_publish(
            client=_hub(),  # type: ignore[arg-type]
            workflow_name=workflow_name.strip() or f"[AUTO] {fd.get('name', 'Funnel')}",
            enabled=enabled,
            sender=sender,
        )


def _do_publish(
    *,
    client: HubSpotClient,
    workflow_name: str,
    enabled: bool,
    sender: dict[str, str],
) -> None:
    fd = st.session_state.form_data or {}
    conf = st.session_state.confirmation_choice or {}
    nurt_steps = st.session_state.nurturing_steps or []

    result: dict[str, Any] = {
        "property": None,
        "form": None,
        "imported_emails": [],
        "workflow": None,
        "workflow_fallback_md": None,
    }

    try:
        # 1) ensure property (silenzioso al boot — qui safety net)
        with st.spinner("Verifico property `id_campagna_refresh`…"):
            ps = props_mod.ensure_refresh_property(client)
            result["property"] = {"name": ps.property.name, "created": ps.created}

        # 2) crea form
        with st.spinner("Creo il form HubSpot…"):
            form_payload = forms_mod.build_form_payload(
                name=fd["name"],
                submit_button_label=fd["submit_button_label"],
                success_message=fd["success_message"],
                redirect_url=fd["redirect_url"],
                include_phone=fd["include_phone"],
                include_lastname=fd["include_lastname"],
                default_campaign_id=fd["default_campaign_id"],
            )
            form_resp = client.create_form(form_payload)
            result["form"] = form_resp
            form_id = str(form_resp.get("id", ""))
            if not form_id:
                raise RuntimeError("Form creato ma id mancante nella risposta HubSpot.")

        # 3) risolvi conferma + nurturing → email_id HubSpot
        store = _store()
        # Ricostruisco i flats per la risoluzione (un solo call, niente picker UI)
        _, conf_flats = _build_email_picker(
            client=client, store=store, allow_none=True,
            subtype_filter=("confirmation_mail",),
        )
        _, nurt_flats = _build_email_picker(
            client=client, store=store, allow_none=True,
            subtype_filter=("nurturing_sequence", "nurturing_single"),
        )
        flats_all: dict[str, emails_mod.FlatDraft] = {**conf_flats, **nurt_flats}

        created_cache: dict[str, str] = {}

        with st.spinner("Importo eventuali mail dal copywriter…"):
            confirmation_email_id = _resolve_email_choice(
                client=client,
                choice=conf,
                flats_by_key=flats_all,
                from_name=sender.get("from_name", ""),
                from_email=sender.get("from_email", ""),
                reply_to=sender.get("reply_to", ""),
                created_cache=created_cache,
            )

            nurturing_sequence: list[dict[str, Any]] = []
            for i, step in enumerate(nurt_steps, 1):
                eid = _resolve_email_choice(
                    client=client,
                    choice=step["choice"],
                    flats_by_key=flats_all,
                    from_name=sender.get("from_name", ""),
                    from_email=sender.get("from_email", ""),
                    reply_to=sender.get("reply_to", ""),
                    created_cache=created_cache,
                )
                if eid:
                    nurturing_sequence.append({
                        "day": i,
                        "email_id": eid,
                        "delay_hours": int(step.get("delay_hours", 24)),
                    })

        result["imported_emails"] = [
            {"copywriter_key": k, "hubspot_id": v} for k, v in created_cache.items()
        ]

        # 4) crea workflow unico
        wf_payload = wf_mod.build_funnel_workflow_payload(
            name=workflow_name,
            triggering_form_id=form_id,
            confirmation_email_id=confirmation_email_id,
            nurturing_sequence=nurturing_sequence,
            enabled=enabled,
        )

        with st.spinner("Creo il workflow HubSpot…"):
            try:
                wf_resp = client.create_workflow(wf_payload)
                result["workflow"] = wf_resp
            except HubSpotError as e:
                # Fallback markdown + JSON per ricreazione manuale
                result["workflow_fallback_md"] = wf_mod.render_workflow_spec_md(wf_payload)
                result["workflow_fallback_json"] = wf_payload
                result["workflow_error"] = str(e)

        st.session_state.result = result
        _set_step("done")
        st.rerun()

    except HubSpotError as e:
        st.session_state.error = f"HubSpot error: {e}"
    except Exception:
        st.session_state.error = traceback.format_exc()


# ── Step done: risultato ───────────────────────────────────────────


def _step_done() -> None:
    st.subheader("✅ Fatto")
    r = st.session_state.result or {}

    ps = r.get("property")
    if ps:
        verb = "Creata" if ps.get("created") else "Verificata"
        st.success(f"{verb} property `{ps.get('name')}`")

    form = r.get("form")
    if form:
        st.success(f"Form creato — id `{form.get('id')}` · `{form.get('name')}`")
        if HUBSPOT_PORTAL_ID:
            url = f"https://app.hubspot.com/forms/{HUBSPOT_PORTAL_ID}/editor/{form.get('id')}/edit/form"
            st.markdown(f"[Apri form in HubSpot]({url})")

    imported = r.get("imported_emails") or []
    if imported:
        st.success(f"Importate {len(imported)} mail dal copywriter (stato DRAFT)")
        for m in imported:
            st.caption(f"  - HubSpot id `{m['hubspot_id']}`")

    wf = r.get("workflow")
    if wf:
        st.success(f"Workflow creato — id `{wf.get('id')}` · `{wf.get('name')}`")
        if HUBSPOT_PORTAL_ID:
            url = f"https://app.hubspot.com/workflows/{HUBSPOT_PORTAL_ID}/platform/flow/{wf.get('id')}"
            st.markdown(f"[Apri workflow in HubSpot]({url})")
    elif r.get("workflow_fallback_md"):
        st.warning(
            "HubSpot ha rifiutato la creazione automatica del workflow "
            "(probabile feature flag mancante). Sotto trovi la spec da "
            "ricreare manualmente in HubSpot UI."
        )
        st.caption(f"Errore HubSpot: `{r.get('workflow_error')}`")
        st.markdown(r["workflow_fallback_md"])
        with st.expander("JSON payload completo"):
            st.code(json.dumps(r["workflow_fallback_json"], indent=2), language="json")

    st.divider()
    if st.button("🔄 Nuovo wizard", type="primary"):
        _reset_wizard()
        st.rerun()


# ── Routing ────────────────────────────────────────────────────────


def _main() -> None:
    st.title("🔌 Automation Specialist Agent")
    st.caption(
        "Configura HubSpot per una campagna Leone: form di acquisizione + "
        "mail di conferma + sequenza nurturing, in un unico workflow."
    )
    _render_progress()
    st.divider()

    step = st.session_state.step
    if step == "form":
        _step_form()
    elif step == "confirmation":
        _step_confirmation()
    elif step == "nurturing":
        _step_nurturing()
    elif step == "publish":
        _step_publish()
    elif step == "done":
        _step_done()
    else:
        st.error(f"Stato sconosciuto: {step}")


_main()
