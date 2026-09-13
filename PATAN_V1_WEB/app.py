from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
import base64

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import database as db
from engine import case_hitos, evaluate_case, parse_date
from styles import global_css, login_css, splash_css
from deadline_engine import COMARB_CALENDAR_URL, proposed_notification_date, add_business_days, business_days_remaining
from graphic_report import build_report_image, png_to_pdf
from version import APP_VERSION

BASE_DIR = Path(__file__).resolve().parent
ASSETS = BASE_DIR / "assets"
LOGIN_IMAGE = ASSETS / "patan_login_v4.png"
SPLASH_IMAGE = ASSETS / "patan_portada.png"

st.set_page_config(page_title="PATÁN · Control de Gestión", page_icon="🐾", layout="wide", initial_sidebar_state="expanded")
db.init_db()
db.refresh_overdue_tasks()
db.backup_database()


def fmt_date(v: str | None) -> str:
    d = parse_date(v)
    return d.strftime("%d/%m/%Y") if d else "—"


def money(v: float | int | None) -> str:
    return f"$ {float(v or 0):,.0f}".replace(",", ".")


def splash() -> None:
    """Primera puerta de PATÁN: identifica un usuario activo, sin pedir PIN todavía."""
    st.markdown(splash_css(SPLASH_IMAGE), unsafe_allow_html=True)
    st.markdown('<div class="patan-splash-mask"></div>', unsafe_allow_html=True)

    username = st.text_input(
        "Usuario autorizado", placeholder="Usuario autorizado", label_visibility="collapsed",
        autocomplete="username", key="patan_splash_username_input"
    )
    enter = st.button("→", key="patan_splash_continue", type="primary")

    if enter:
        wanted = (username or "").strip().lower()
        active_users = db.list_users(active_only=True)
        enabled = next((u for u in active_users if str(u.get("username") or "").strip().lower() == wanted), None)
        if enabled:
            st.session_state.splash_passed = True
            st.session_state.splash_username = enabled.get("username")
            st.rerun()
        else:
            st.session_state.splash_error = True

    if st.session_state.pop("splash_error", False):
        st.markdown('<div class="splash-error">Usuario no habilitado</div>', unsafe_allow_html=True)


def login() -> None:
    """Segunda puerta: el usuario ya fue validado en portada; aquí se solicita solo la clave."""
    st.markdown(login_css(LOGIN_IMAGE), unsafe_allow_html=True)

    username = st.session_state.get("splash_username")
    if not username:
        st.session_state.pop("splash_passed", None)
        st.rerun()

    with st.form("patan_login_form", clear_on_submit=False):
        pin = st.text_input(
            "PIN", type="password", max_chars=20, placeholder="PIN / clave",
            label_visibility="collapsed", autocomplete="current-password",
            key="patan_second_gate_pin",
        )
        enter = st.form_submit_button("→", type="primary")

    if enter:
        user = db.authenticate(str(username), pin)
        if user:
            st.session_state.auth = True
            st.session_state.user = user
            st.session_state.session_version = int(user.get("session_version") or 1)
            st.rerun()
        else:
            st.session_state.login_error = True

    if st.session_state.pop("login_error", False):
        st.markdown('<div class="login-error">PIN incorrecto</div>', unsafe_allow_html=True)


# Doble puerta: 1) portada valida usuario, 2) segunda puerta solicita únicamente PIN/clave.
if not st.session_state.get("splash_passed"):
    splash()
    st.stop()

if not st.session_state.get("auth") or not st.session_state.get("user"):
    login()
    st.stop()

current_user = st.session_state["user"]
# Valida sesión persistente: el administrador puede cerrar sesiones remotas incrementando session_version.
fresh_user = db.get_user(int(current_user["id"]))
if not fresh_user or int(fresh_user.get("active") or 0) != 1 or int(fresh_user.get("session_version") or 1) != int(st.session_state.get("session_version") or 1):
    for k in ["auth", "user", "session_version", "selected_case_id", "case_mode", "splash_passed", "splash_username"]:
        st.session_state.pop(k, None)
    st.warning("La sesión fue cerrada o el usuario ya no está activo.")
    st.rerun()
current_user.update(fresh_user)
prev_login=current_user.get("_previous_last_login_at")
if prev_login:
    try:
        prev_dt=datetime.fromisoformat(str(prev_login).replace("Z",""))
        if (datetime.now()-prev_dt).days >= int(db.fetch_settings().get("inactive_user_alert_days",90)):
            st.warning(f"⚠ Este usuario llevaba {(datetime.now()-prev_dt).days} días sin ingresar a PATÁN.")
    except Exception:
        pass
# Expiración por inactividad (60 minutos).
now_ts = datetime.now().timestamp()
last_ts = float(st.session_state.get("last_activity_ts") or now_ts)
if now_ts - last_ts > 60 * 60:
    for k in ["auth", "user", "session_version", "last_activity_ts", "selected_case_id", "case_mode", "splash_passed", "splash_username"]:
        st.session_state.pop(k, None)
    st.warning("Sesión vencida por inactividad.")
    st.rerun()
st.session_state["last_activity_ts"] = now_ts
role = current_user.get("role") or "USUARIO"
is_admin = role == "ADMIN"
is_supervisor = role == "SUPERVISOR"
can_edit = True

# Seguridad v12: clave inicial y renovación cada 90 días.
security_settings = db.fetch_settings()
ps = db.password_status(current_user, int(security_settings.get("password_expiry_days",90)), int(security_settings.get("inactive_user_alert_days",90)))
if ps["must_change"] or ps["password_expired"]:
    st.markdown(global_css(), unsafe_allow_html=True)
    st.markdown("## 🔐 Cambio de clave obligatorio")
    st.info("La clave inicial debe cambiarse en el primer ingreso. Luego PATÁN solicita renovación cada 90 días.")
    with st.form("force_password_change"):
        old_pin=st.text_input("Clave actual",type="password",max_chars=20,help="Si el usuario es nuevo, la clave inicial es 1234.")
        new_pin=st.text_input("Nueva clave",type="password",max_chars=20,help="Entre 4 y 20 caracteres.")
        rep_pin=st.text_input("Repetir nueva clave",type="password",max_chars=20)
        if st.form_submit_button("CAMBIAR CLAVE",use_container_width=False,type="primary"):
            if new_pin!=rep_pin: st.error("Las nuevas claves no coinciden.")
            else:
                try:
                    db.change_password(int(current_user["id"]),old_pin,new_pin)
                    fresh=db.get_user(int(current_user["id"])); fresh.pop("pin_hash",None) if fresh and "pin_hash" in fresh else None
                    st.session_state["user"].update(fresh or {})
                    st.success("Clave actualizada."); st.rerun()
                except Exception as e: st.error(str(e))
    st.stop()

st.markdown(global_css(), unsafe_allow_html=True)

with st.sidebar:
    paw_b64 = base64.b64encode((ASSETS / 'logo_pata.png').read_bytes()).decode('ascii')
    sol_b64 = base64.b64encode((ASSETS / 'sol_sidebar.png').read_bytes()).decode('ascii')
    st.markdown(f'<div class="patan-brand-paw" title="PATÁN"><img src="data:image/png;base64,{paw_b64}" alt="Logo PATÁN"></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="patan-sol" title="SOL DE MAYO · IDENTIDAD ARGENTINA"><img src="data:image/png;base64,{sol_b64}" alt="Sol de Mayo"></div>', unsafe_allow_html=True)
    st.markdown(f"**{current_user['display_name']}**")
    st.caption(f"{(current_user.get('jurisdiction') or 'SISTEMA').upper()}")
    st.markdown(f'<div class="patan-sidebar-version"><span>VERSIÓN</span><b>{APP_VERSION}</b></div>', unsafe_allow_html=True)
    unread_news=db.unread_news_count(int(current_user["id"]))
    new_suggestions=db.unread_suggestion_count() if is_admin else 0
    if unread_news:
        st.markdown(f'<div class="patan-blink patan-alert-blue">🔔 NOVEDADES · {unread_news} SIN LEER</div>',unsafe_allow_html=True)
    if is_admin and new_suggestions:
        st.markdown(f'<div class="patan-blink patan-alert-yellow">💡 SUGERENCIAS · {new_suggestions} NUEVAS</div>',unsafe_allow_html=True)
    nav = ["CONTROL DE GESTIÓN", "REPORTE DE GESTIÓN", "TRABAJOS", "TAREAS", "NUEVA ACTUACIÓN", "HISTÓRICO", "REUNIONES", "💡 SUGERENCIAS", "🔔 NOVEDADES"]
    if is_admin or is_supervisor:
        nav += ["AGENTES"]
    if is_admin:
        nav += ["USUARIOS", "SEGURIDAD", "PARÁMETROS"]
    page = st.radio("Navegación", nav, label_visibility="collapsed")
    st.divider()
    if st.button("Cerrar sesión", use_container_width=True):
        for k in ["auth", "user", "session_version", "last_activity_ts", "selected_case_id", "case_mode", "splash_passed", "splash_username"]:
            st.session_state.pop(k, None)
        st.rerun()

settings = db.fetch_settings()
visible_user_ids = db.visible_user_ids(current_user)
all_cases = db.list_cases_for_users(visible_user_ids, include_closed=False)
# Los suspendidos se conservan en CASOS pero no disparan el semáforo activo.
case_states = {c["id"]: evaluate_case(c, settings) for c in all_cases}
users_catalog = db.list_users(active_only=True)
if is_admin:
    active_users = users_catalog
elif is_supervisor:
    active_users = [u for u in users_catalog if visible_user_ids is None or int(u["id"]) in visible_user_ids]
else:
    active_users = [current_user]
user_by_id = {u["id"]: u for u in active_users}
all_tasks = db.list_tasks([c["id"] for c in all_cases], include_done=True)
open_tasks = [t for t in all_tasks if t["status"] not in ("CUMPLIDA", "CANCELADA")]


def header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="patan-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="patan-sub">{subtitle}</div>', unsafe_allow_html=True)
    st.write("")


def card(label: str, value: str, cls: str = "") -> None:
    st.markdown(f'<div class="metric-card {cls}"><div class="metric-value">{value}</div><div class="metric-label">{label}</div></div>', unsafe_allow_html=True)


def manual_activity_widget(case: dict, key_prefix: str = "case") -> None:
    """Carga manual de la última actividad. Al guardar, MOVIMIENTOS y el tablero se actualizan solos."""
    if not can_edit:
        st.info("Perfil de solo lectura: no puede registrar actuaciones.")
        return
    case_id = int(case["id"])
    fresh_cases = db.list_cases_for_users(visible_user_ids)
    fresh = next((c for c in fresh_cases if c["id"] == case_id), case)
    state = evaluate_case(fresh, db.fetch_settings())

    m1, m2, m3 = st.columns(3)
    m1.metric("Estado", state.icon + " " + state.label)
    m2.metric("Último movimiento", fmt_date(fresh.get("last_movement")))
    m3.metric("Días sin actividad", state.days_without_activity if state.days_without_activity is not None else "—")

    activity_types = [r["name"] for r in db.list_activity_types(active_only=True)]
    selector = activity_types + ["＋ Agregar tipo personalizado"]

    st.markdown("#### Cargar última actividad")
    with st.form(f"manual_activity_{key_prefix}_{case_id}", clear_on_submit=True):
        c1, c2 = st.columns([1, 1.5])
        movement_date = c1.date_input("Fecha", value=date.today())
        action = c2.selectbox("Acción", selector)

        custom_name = ""
        if action == "＋ Agregar tipo personalizado":
            custom_name = st.text_input("Nombre de la nueva acción", placeholder="Ej.: Vista previa, Pedido de antecedentes…")

        reference = st.text_input(
            "Número / referencia (opcional)",
            placeholder="Ej.: 1547/2026, Acta 23, Cédula 08/26…",
        )
        description = st.text_area("Observación", height=85, placeholder="Detalle breve del movimiento, si corresponde")
        useful = st.checkbox("Computar como actividad para el semáforo", value=True)
        sign_activity = st.checkbox("Firmar actividad", value=False, help="Firma: confirmo que la actuación fue revisada. Si no se firma, queda como BORRADOR.")

        save = st.form_submit_button("GUARDAR ACTIVIDAD", use_container_width=False, type="primary")

    if save:
        try:
            final_action = action
            if action == "＋ Agregar tipo personalizado":
                final_action = custom_name.strip()
                if not final_action:
                    st.error("Ingresá el nombre de la acción personalizada.")
                    return
                db.add_activity_type(final_action)

            label = final_action.strip() or "Actuación"
            if reference.strip():
                label = f"{label} N° {reference.strip()}"

            movement_id = db.add_movement({
                "case_id": case_id,
                "movement_date": movement_date.isoformat(),
                "movement_type": label,
                "description": description.strip(),
                "useful_activity": int(useful),
                "is_progress_report": int(final_action.lower().strip() == "informe de avance"),
                "record_status": "BORRADOR",
            })
            if sign_activity: db.sign_record("movement",movement_id,int(current_user["id"]))
            db.log_audit(int(current_user["id"]), "CREATE", "movement", movement_id, details=f"{case.get('case_number')} · {label}")
            st.success("Actividad registrada. Último movimiento y Control de Gestión actualizados automáticamente.")
            st.rerun()
        except Exception as e:
            st.error(f"No se pudo guardar la actividad: {e}")


def task_badge(task: dict) -> str:
    status = task.get("status") or "PENDIENTE"
    if status == "VENCIDA": return "🔴 VENCIDA"
    if status == "CUMPLIDA": return "✅ CUMPLIDA"
    if status == "CANCELADA": return "⚪ CANCELADA"
    due = parse_date(task.get("due_date"))
    if due:
        d=(due-date.today()).days
        if d <= 2: return "🟡 PRÓXIMA"
    return "🟢 PENDIENTE"


def next_task_for_case(case_id: int):
    tasks=[t for t in open_tasks if int(t["case_id"])==int(case_id)]
    return sorted(tasks, key=lambda t: (t.get("due_date") or "9999-12-31", t["id"]))[0] if tasks else None



TASK_TYPES = ["Nota", "Requerimiento", "Intimación", "Cédula", "Pedido a tercero", "Otro"]

def task_state_label(t: dict) -> str:
    if t.get("status") == "CUMPLIDA": return "✅ CUMPLIDA"
    if t.get("status") == "CANCELADA": return "⚪ CANCELADA"
    due=parse_date(t.get("due_date"))
    if due and due < date.today(): return "🔴 VENCIDA"
    if due:
        rem=business_days_remaining(due)
        if rem <= 2: return f"🟡 VENCE EN {rem} D.H."
        return f"🟢 EN TÉRMINO · {rem} D.H."
    return "🟢 PENDIENTE"


def task_title(task_type: str, reference: str, recipient: str) -> str:
    base = task_type.strip()
    if reference.strip(): base += f" {reference.strip()}"
    if recipient.strip(): base += f" · {recipient.strip()}"
    return base


def render_new_tracking_task(case: dict, key_prefix: str):
    st.markdown("#### Nueva tarea / actuación con vencimiento")
    st.caption("La fecha de notificación se propone automáticamente como el primer martes o viernes posterior al envío. El resultado queda editable. Los vencimientos se computan en días hábiles.")
    st.markdown(f"**Fuente de referencia para calendario:** [Calendario oficial COMARB]({COMARB_CALENDAR_URL})")
    k=f"{key_prefix}_{case['id']}"
    c1,c2,c3=st.columns([1.1,1,1.4])
    typ=c1.selectbox("Actuación",TASK_TYPES,key=f"typ_{k}")
    ref=c2.text_input("N.º / referencia",placeholder="Ej. 120-26",key=f"ref_{k}")
    rec=c3.text_input("Destinatario",placeholder="Persona / tercero",key=f"rec_{k}")
    c4,c5,c6=st.columns(3)
    sent=c4.date_input("Fecha de envío",value=date.today(),key=f"sent_{k}")
    proposed=proposed_notification_date(sent)
    notif=c5.date_input("Fecha de notificación",value=proposed,key=f"notif_{k}",help="PATÁN propone martes o viernes posterior al envío. Editable.")
    term=int(c6.number_input("Plazo otorgado (días hábiles)",min_value=1,max_value=120,value=10,step=1,key=f"term_{k}"))
    due=add_business_days(notif,term)
    c7,c8,c9=st.columns(3)
    due_edit=c7.date_input("Vencimiento",value=due,key=f"due_{k}",help="Calculado en días hábiles; queda editable.")
    prio=c8.selectbox("Prioridad",["ALTA","MEDIA","BAJA"],index=1,key=f"prio_{k}")
    ownermap={u["display_name"]:u["id"] for u in active_users if int(u.get("is_agent") or 0)==1}
    default_owner=next((n for n,uid in ownermap.items() if uid==case.get("responsible_user_id")),list(ownermap.keys())[0] if ownermap else "")
    owner=c9.selectbox("Agente",list(ownermap.keys()),index=list(ownermap.keys()).index(default_owner) if default_owner in ownermap else 0,key=f"owner_{k}") if ownermap else None
    notes=st.text_area("Observaciones",height=70,key=f"notes_{k}")
    sign_task=st.checkbox("Firmar tarea al crear",value=False,key=f"sign_{k}",help="Si no se firma, queda como BORRADOR y puede corregirse. Firmada, cualquier cambio exige rectificación.")
    st.info(f"Notificación propuesta: **{proposed.strftime('%d/%m/%Y')}** · Vencimiento calculado: **{due.strftime('%d/%m/%Y')}** · Vencimiento elegido: **{due_edit.strftime('%d/%m/%Y')}**")
    if st.button("AGREGAR A TAREAS",use_container_width=False,type="primary",key=f"add_{k}"):
        title=task_title(typ,ref,rec)
        tid=db.add_task(int(case["id"]),title,due_edit.isoformat(),prio,ownermap.get(owner) if ownermap else None,notes,int(current_user["id"]),task_type=typ,reference_number=ref,recipient=rec,sent_date=sent.isoformat(),notification_date=notif.isoformat(),term_days=term,jurisdiction=case.get("jurisdiction") or current_user.get("jurisdiction"),record_status="BORRADOR")
        mid=db.add_movement({"case_id":int(case["id"]),"movement_date":sent.isoformat(),"movement_type":typ,"description":f"{title}. Envío {sent.strftime('%d/%m/%Y')}; notificación {notif.strftime('%d/%m/%Y')}; vence {due_edit.strftime('%d/%m/%Y')}.","useful_activity":1,"is_progress_report":0,"record_status":"BORRADOR"})
        if sign_task:
            db.sign_record("task",tid,int(current_user["id"])); db.sign_record("movement",mid,int(current_user["id"]))
        st.success("Tarea cargada y movimiento del trabajo actualizado.")
        st.rerun()


def render_task_actions(tasks: list[dict], key_prefix: str):
    pending=[t for t in tasks if t.get("status") not in ("CUMPLIDA","CANCELADA")]
    if not pending: return
    labels={f"{t['case_number']} · {t['title']} · {fmt_date(t.get('due_date'))}":t for t in pending}
    chosen=st.selectbox("Gestionar tarea",list(labels.keys()),key=f"manage_{key_prefix}")
    t=labels[chosen]
    st.caption(f"Envío: {fmt_date(t.get('sent_date'))} · Notificación: {fmt_date(t.get('notification_date'))} · Vencimiento vigente: {fmt_date(t.get('due_date'))} · {'🔒 FIRMADO' if t.get('record_status')=='FIRMADO' else '✎ BORRADOR'}")
    with st.expander("EDITAR / FIRMAR TAREA"):
        signed=t.get("record_status")=="FIRMADO"
        rectify=st.checkbox("Rectificar tarea firmada",value=False,disabled=not signed,key=f"trect_{key_prefix}_{t['id']}",help="La rectificación conserva trazabilidad y exige motivo.")
        reason=st.text_input("Motivo de rectificación",disabled=not rectify,key=f"treason_{key_prefix}_{t['id']}")
        locked=signed and not rectify
        e1,e2,e3=st.columns(3)
        etype=e1.selectbox("Actuación",TASK_TYPES,index=TASK_TYPES.index(t.get('task_type')) if t.get('task_type') in TASK_TYPES else 0,disabled=locked,key=f"etype_{key_prefix}_{t['id']}")
        eref=e2.text_input("N.º / referencia",value=t.get('reference_number') or '',disabled=locked,key=f"eref_{key_prefix}_{t['id']}")
        erec=e3.text_input("Destinatario",value=t.get('recipient') or '',disabled=locked,key=f"erec_{key_prefix}_{t['id']}")
        e4,e5,e6=st.columns(3)
        esent=e4.date_input("Envío",value=parse_date(t.get('sent_date')) or date.today(),disabled=locked,key=f"esent_{key_prefix}_{t['id']}")
        enotif=e5.date_input("Notificación",value=parse_date(t.get('notification_date')) or date.today(),disabled=locked,key=f"enotif_{key_prefix}_{t['id']}")
        eterm=int(e6.number_input("Plazo d.h.",min_value=1,max_value=120,value=int(t.get('term_days') or 10),disabled=locked,key=f"eterm_{key_prefix}_{t['id']}"))
        edue=st.date_input("Vencimiento",value=parse_date(t.get('due_date')) or add_business_days(enotif,eterm),disabled=locked,key=f"edue_{key_prefix}_{t['id']}")
        enotes=st.text_area("Observaciones",value=t.get('notes') or '',height=65,disabled=locked,key=f"enotes_{key_prefix}_{t['id']}")
        b1,b2=st.columns(2)
        if b1.button("GUARDAR EDICIÓN",use_container_width=True,disabled=locked,key=f"tsave_{key_prefix}_{t['id']}"):
            try:
                db.update_task(int(t['id']),{"task_type":etype,"reference_number":eref,"recipient":erec,"sent_date":esent.isoformat(),"notification_date":enotif.isoformat(),"term_days":eterm,"due_date":edue.isoformat(),"notes":enotes,"priority":t.get('priority') or 'MEDIA'},int(current_user['id']),reason if signed else None)
                st.success("Tarea actualizada."); st.rerun()
            except Exception as e: st.error(str(e))
        if b2.button("🔒 FIRMAR REGISTRO",use_container_width=True,disabled=signed,key=f"tsign_{key_prefix}_{t['id']}"):
            db.sign_record("task",int(t['id']),int(current_user['id'])); st.rerun()
    a1,a2=st.columns(2)
    response=a1.date_input("Fecha de respuesta / cumplimiento",value=date.today(),key=f"resp_{key_prefix}_{t['id']}")
    if a2.button("✅ MARCAR REALIZADA",use_container_width=True,key=f"done_{key_prefix}_{t['id']}"):
        db.complete_task(int(t["id"]),response.isoformat(),int(current_user["id"]))
        db.add_movement({"case_id":int(t["case_id"]),"movement_date":response.isoformat(),"movement_type":"Respuesta / cumplimiento","description":f"Cumplida: {t['title']}.","useful_activity":1,"is_progress_report":0})
        st.rerun()
    with st.expander("OTORGAR PRÓRROGA"):
        p1,p2,p3=st.columns(3)
        req=p1.date_input("Pedido de prórroga",value=date.today(),key=f"preq_{key_prefix}_{t['id']}")
        granted=p2.date_input("Fecha en que se otorga",value=date.today(),key=f"pgrant_{key_prefix}_{t['id']}")
        days=int(p3.number_input("Días hábiles otorgados",min_value=1,max_value=120,value=5,step=1,key=f"pdays_{key_prefix}_{t['id']}"))
        base=parse_date(t.get("due_date")) or granted
        new_due=add_business_days(base,days)
        new_due_edit=st.date_input("Nuevo vencimiento",value=new_due,key=f"pdue_{key_prefix}_{t['id']}",help="La prórroga se computa como acto nuevo desde el vencimiento vigente. Editable.")
        st.info(f"Vencimiento anterior: **{fmt_date(t.get('due_date'))}** → nuevo vencimiento: **{new_due_edit.strftime('%d/%m/%Y')}**")
        if st.button("CONFIRMAR PRÓRROGA",use_container_width=False,key=f"pext_{key_prefix}_{t['id']}"):
            db.grant_task_extension(int(t["id"]),req.isoformat(),granted.isoformat(),days,new_due_edit.isoformat(),int(current_user["id"]))
            db.add_movement({"case_id":int(t["case_id"]),"movement_date":granted.isoformat(),"movement_type":"Prórroga","description":f"Prórroga de {days} días hábiles para {t['title']}. Nuevo vencimiento {new_due_edit.strftime('%d/%m/%Y')}.","useful_activity":1,"is_progress_report":0})
            st.rerun()


def task_rows(tasks: list[dict]):
    return [{"Estado":task_state_label(t),"Trabajo":t.get("case_number"),"Actuación":t.get("task_type") or t.get("title"),"N.º":t.get("reference_number") or "—","Destinatario":t.get("recipient") or "—","Envío":fmt_date(t.get("sent_date")),"Notificación":fmt_date(t.get("notification_date")),"Vence":fmt_date(t.get("due_date")),"Respuesta":fmt_date(t.get("response_date")),"Prórroga":(f"{t.get('extension_days')} d.h. → {fmt_date(t.get('extension_due_date'))}" if t.get("extension_days") else "—"),"Firma":("🔒 FIRMADO" if t.get("record_status")=="FIRMADO" else "✎ BORRADOR"),"Jurisdicción":t.get("jurisdiction") or "—","Agente":t.get("owner_name") or "—"} for t in tasks]

if page == "CONTROL DE GESTIÓN":
    # V16 · misma composición original, ajustada únicamente a la altura de pantalla.
    st.markdown("""
    <style>
      /* Sólo CONTROL DE GESTIÓN: conserva la composición y la escala para entrar sin scroll. */
      div[data-testid="stMainBlockContainer"] {
        zoom: 0.78;
        width: 100% !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        padding-top: 0.45rem !important;
        padding-bottom: 0.25rem !important;
      }
      div[data-testid="stMain"] {
        overflow-x: hidden !important;
        overflow-y: hidden !important;
      }
      /* Mantiene el encuadre V18, pero recupera tamaño visual de títulos y KPIs. */
      div[data-testid="stMainBlockContainer"] .patan-title { font-size:2.63rem !important; }
      div[data-testid="stMainBlockContainer"] .patan-sub { font-size:1rem !important; }
      div[data-testid="stMainBlockContainer"] .metric-value { font-size:2.56rem !important; }
      div[data-testid="stMainBlockContainer"] .metric-label { font-size:.97rem !important; }
      div[data-testid="stMainBlockContainer"] h3 { font-size:1.72rem !important; margin-top:.18rem !important; margin-bottom:.22rem !important; }
      div[data-testid="stMainBlockContainer"] [data-testid="stMetricLabel"] p { font-size:1rem !important; }
      div[data-testid="stMainBlockContainer"] [data-testid="stMetricValue"] { font-size:2.5rem !important; }
    </style>
    """, unsafe_allow_html=True)
    header("CONTROL DE GESTIÓN")

    overdue_tasks = [t for t in open_tasks if t.get("status") == "VENCIDA"]
    due_soon = [t for t in open_tasks if t.get("status") == "PENDIENTE" and parse_date(t.get("due_date")) and 0 <= (parse_date(t.get("due_date")) - date.today()).days <= 5]
    unassigned = [c for c in all_cases if not c.get("responsible_user_id")]
    a1,a2,a3 = st.columns(3)
    a1.metric("Tareas vencidas", len(overdue_tasks))
    a2.metric("Vencen ≤ 5 días", len(due_soon))
    a3.metric("Sin agente", len(unassigned))
    if overdue_tasks or due_soon or unassigned:
        with st.expander("⚠ ALERTAS DE GESTIÓN", expanded=True):
            for t in overdue_tasks[:8]: st.error(f"{t['case_number']} · tarea vencida: {t['title']} · {fmt_date(t.get('due_date'))}")
            for t in due_soon[:8]: st.warning(f"{t['case_number']} · próxima: {t['title']} · {fmt_date(t.get('due_date'))}")
            for c in unassigned[:8]: st.error(f"{c['case_number']} · trabajo activo sin agente asignado")

    counts = {k: 0 for k in ["VERDE", "AMARILLO", "ROJO"]}
    for state in case_states.values():
        counts[state.label] = counts.get(state.label, 0) + 1

    c1, c2, c3, c4 = st.columns(4)
    with c1: card("Trabajos activos", str(len(all_cases)))
    with c2: card("En término", f"🟢 {counts['VERDE']}", "status-green")
    with c3: card("Seguimiento", f"🟡 {counts['AMARILLO']}", "status-yellow")
    with c4: card("Críticos", f"🔴 {counts['ROJO']}", "status-red")

    st.write("")
    left, right = st.columns([1.9, 0.95], gap="small")
    with left:
        st.subheader("Trabajos que requieren atención")
        rows = []
        for c in all_cases:
            s = case_states[c["id"]]
            if s.label in ("ROJO", "AMARILLO"):
                rows.append({
                    "Estado": s.icon + " " + s.label,
                    "Trabajo": c["case_number"],
                    "Persona / asunto": c.get("taxpayer_name") or c.get("title") or "—",
                    "Último movimiento": fmt_date(c.get("last_movement")),
                    "Días sin actividad": s.days_without_activity,
                    "% plazo": round(s.objective_pct or 0, 1),
                    "Motivo": s.reason,
                })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=430)
        else:
            st.success("No hay trabajos amarillos o rojos.")

    with right:
        st.subheader("Distribución")
        chart_df = pd.DataFrame({"Estado": ["VERDE", "AMARILLO", "ROJO"], "Trabajos": [counts["VERDE"], counts["AMARILLO"], counts["ROJO"]]}).set_index("Estado")
        st.bar_chart(chart_df)
        st.subheader("Resultados acumulados")
        determined = sum(float(c.get("amount_determined") or 0) for c in all_cases)
        confirmed = sum(float(c.get("amount_confirmed") or 0) for c in all_cases)
        x, y = st.columns(2)
        x.metric("Determinado", money(determined))
        y.metric("Conformado", money(confirmed))

    if is_admin or is_supervisor:
        st.subheader("Gestión por agente")
        agent_rows=[]
        for u in active_users:
            if int(u.get("is_agent") or 0)!=1:
                continue
            uc=[c for c in all_cases if c.get("responsible_user_id")==u["id"]]
            ut=[t for t in open_tasks if t.get("owner_user_id")==u["id"]]
            agent_rows.append({"Agente":u["display_name"],"Activos":len(uc),"🟢":sum(case_states[c["id"]].label=="VERDE" for c in uc),"🟡":sum(case_states[c["id"]].label=="AMARILLO" for c in uc),"🔴":sum(case_states[c["id"]].label=="ROJO" for c in uc),"Tareas vencidas":sum(t["status"]=="VENCIDA" for t in ut)})
        if agent_rows: st.dataframe(pd.DataFrame(agent_rows),use_container_width=True,hide_index=True)

    st.subheader("Próximos hitos")
    upcoming = []
    today = date.today()
    for c in all_cases:
        for name, d in case_hitos(c, settings).items():
            if d:
                delta = (d - today).days
                if -10 <= delta <= 30:
                    upcoming.append({"Trabajo": c["case_number"], "Hito": name.replace("_", " ").title(), "Fecha": d.strftime("%d/%m/%Y"), "Días": delta})
    if upcoming:
        st.dataframe(pd.DataFrame(sorted(upcoming, key=lambda x: x["Días"])), use_container_width=True, hide_index=True)
    else:
        st.caption("Sin hitos dentro de la ventana de 30 días.")

elif page == "REPORTE DE GESTIÓN":
    header("REPORTE DE GESTIÓN", "Tablero visual por agente y jurisdicción")

    # El usuario común informa sobre sí mismo; supervisor/administrador pueden elegir agente visible.
    agent_candidates=[u for u in active_users if int(u.get("is_agent") or 0)==1]
    if not agent_candidates and int(current_user.get("is_agent") or 0)==1:
        agent_candidates=[current_user]
    if is_admin or is_supervisor:
        amap={f"{u['display_name']} · {u.get('jurisdiction') or 'Sin jurisdicción'}":u for u in agent_candidates}
        alabel=st.selectbox("Agente del informe",list(amap.keys()),help="El reporte se emite para un agente y su jurisdicción.") if amap else None
        report_user=amap.get(alabel) if alabel else current_user
    else:
        report_user=current_user
        st.markdown(f"### {current_user['display_name'].upper()}")
    report_jurisdiction=report_user.get('jurisdiction') or 'Sin jurisdicción'
    st.markdown(f"**{report_jurisdiction.upper()}**")

    report_cases=[c for c in all_cases if int(c.get('responsible_user_id') or 0)==int(report_user['id'])]
    report_states={c['id']:evaluate_case(c,settings) for c in report_cases}
    report_tasks=db.list_tasks([c['id'] for c in report_cases],include_done=True) if report_cases else []
    report_rows=[]
    for c in report_cases:
        s0=report_states[c['id']]
        assigned=parse_date(c.get('date_assigned'))
        days_from_assignment=(date.today()-assigned).days if assigned else None
        remaining=(s0.objective_days-s0.elapsed_days) if s0.objective_days is not None and s0.elapsed_days is not None else None
        report_rows.append({
            "Semáforo":s0.icon+" "+s0.label,"Trabajo":c.get('case_number') or '—',
            "Agente":c.get('responsible_display') or c.get('responsible') or '—',"Jurisdicción":c.get('jurisdiction') or report_jurisdiction,
            "Tipo":c.get('case_type') or '—',"Clasificación":"COMPLEJO" if str(c.get('complexity') or '').upper().startswith('COMP') else 'ESTÁNDAR',
            "Asignación":fmt_date(c.get('date_assigned')),"Días desde asignación":days_from_assignment if days_from_assignment is not None else '—',
            "Último movimiento":fmt_date(c.get('last_movement')),"Días sin actividad":s0.days_without_activity if s0.days_without_activity is not None else '—',
            "Plazo objetivo":s0.objective_days if s0.objective_days is not None else '—',"% consumido":round(s0.objective_pct,1) if s0.objective_pct is not None else '—',
            "Días restantes":remaining if remaining is not None else '—',"Motivo":s0.reason,
        })
    counts={"VERDE":0,"AMARILLO":0,"ROJO":0}
    for st0 in report_states.values():
        if st0.label in counts: counts[st0.label]+=1
    task_open=[t for t in report_tasks if t.get('status') not in ('CUMPLIDA','CANCELADA')]
    task_over=sum(1 for t in task_open if t.get('status')=='VENCIDA')
    k1,k2,k3,k4,k5,k6=st.columns(6)
    k1.metric("Trabajos",len(report_rows)); k2.metric("🟢 En término",counts['VERDE']); k3.metric("🟡 Atención",counts['AMARILLO'])
    k4.metric("🔴 Críticos",counts['ROJO']); k5.metric("Tareas abiertas",len(task_open)); k6.metric("Tareas vencidas",task_over)

    # V13.3: tablero compacto y simétrico, pensado para entrar completo en una pantalla de escritorio.
    total_cases = max(len(report_rows), 1)
    chart_values=[]
    for k,v in counts.items():
        pct=(v/total_cases*100) if report_rows else 0
        chart_values.append({"Estado":k,"Trabajos":v,"Porcentaje":round(pct,1),"Etiqueta":f"{pct:.0f}%"})

    st.markdown("### 📊 TABLERO INTERACTIVO")
    st.caption("RESUMEN EN PANTALLA · LA VISTA PREVIA GRÁFICA SE ABRE AL EXPORTAR.")

    left,right=st.columns([0.82,2.18], gap="large")
    with left:
        st.markdown("#### Semáforo")
        st.vega_lite_chart({
            "data":{"values":chart_values},
            "layer":[
                {
                    "mark":{"type":"bar","cornerRadiusEnd":8,"height":24},
                    "encoding":{
                        "y":{"field":"Estado","type":"nominal","sort":["VERDE","AMARILLO","ROJO"],"axis":{"title":None,"labelFontSize":12,"labelColor":"#d9e7f2","labelPadding":8}},
                        "x":{"field":"Trabajos","type":"quantitative","axis":None,"scale":{"domain":[0,max(1,max(counts.values()))]}},
                        "color":{"field":"Estado","type":"nominal","scale":{"domain":["VERDE","AMARILLO","ROJO"],"range":["#35d07f","#f2c94c","#ff5b5b"]},"legend":None},
                        "tooltip":[{"field":"Estado"},{"field":"Trabajos"},{"field":"Porcentaje","title":"%","format":".1f"}]
                    }
                },
                {
                    "mark":{"type":"text","align":"left","baseline":"middle","dx":8,"fontSize":14,"fontWeight":"bold","color":"white"},
                    "encoding":{
                        "y":{"field":"Estado","type":"nominal","sort":["VERDE","AMARILLO","ROJO"]},
                        "x":{"field":"Trabajos","type":"quantitative"},
                        "text":{"field":"Trabajos","type":"quantitative"}
                    }
                }
            ],
            "height":145,
            "padding":{"top":8,"bottom":8,"left":5,"right":28},
            "autosize":{"type":"fit","contains":"padding"}
        },use_container_width=True)
        pv=(counts['VERDE']/total_cases*100 if report_rows else 0)
        pa=(counts['AMARILLO']/total_cases*100 if report_rows else 0)
        pr=(counts['ROJO']/total_cases*100 if report_rows else 0)
        st.markdown(
            f"""<div class='patan-pct-strip'>
            <span><i class='patan-dot green'></i><b>{pv:.0f}%</b><small>VERDE</small></span>
            <span><i class='patan-dot yellow'></i><b>{pa:.0f}%</b><small>AMARILLO</small></span>
            <span><i class='patan-dot red'></i><b>{pr:.0f}%</b><small>ROJO</small></span>
            </div>""", unsafe_allow_html=True
        )

        cc={"ESTÁNDAR":0,"COMPLEJO":0}
        for c in report_cases:
            cc["COMPLEJO" if str(c.get('complexity') or '').upper().startswith('COMP') else "ESTÁNDAR"]+=1
        st.markdown(
            f"<div class='patan-class-strip'><span><b>ESTÁNDAR</b> {cc['ESTÁNDAR']}</span><span><b>COMPLEJO</b> {cc['COMPLEJO']}</span></div>",
            unsafe_allow_html=True,
        )

    with right:
        st.markdown("#### Detalle del informe")
        if report_rows:
            compact_cols=["Semáforo","Trabajo","Tipo","Clasificación","Asignación","Días sin actividad","% consumido","Días restantes","Motivo"]
            compact_df=pd.DataFrame(report_rows)
            compact_df=compact_df[[c for c in compact_cols if c in compact_df.columns]]
            st.dataframe(compact_df,use_container_width=True,hide_index=True,height=338)
        else:
            st.info("El agente no tiene trabajos activos.")

    if report_tasks:
        with st.expander(f"TAREAS DEL AGENTE · {len(report_tasks)}",expanded=False):
            st.dataframe(pd.DataFrame(task_rows(report_tasks)),use_container_width=True,hide_index=True,height=220)

    @st.dialog(" ", width="large")
    def preview_report_graphic(png_data: bytes, pdf_data: bytes, pdf_name: str) -> None:
        import base64

        # V13.2: el informe se escala contra la ALTURA y el ANCHO disponibles.
        # Así la lámina completa entra en pantalla sin scroll, manteniendo su proporción.
        encoded = base64.b64encode(png_data).decode("ascii")
        st.markdown("""
        <style>
        div[role="dialog"] {
            position: fixed !important;
            inset: 0 !important;
            width: 100vw !important;
            max-width: 100vw !important;
            height: 100vh !important;
            max-height: 100vh !important;
            border-radius: 0 !important;
            overflow: hidden !important;
        }
        div[role="dialog"] [data-testid="stDialogBody"] {
            max-width: none !important;
            overflow: hidden !important;
            padding-top: .25rem !important;
            padding-bottom: .25rem !important;
        }
        /* Encabezado compacto: título a la izquierda y descargas a la derecha. */
        div[role="dialog"] [data-testid="stHorizontalBlock"]:first-of-type {
            align-items: center !important;
            margin-top: -1.7rem !important;
            margin-bottom: .35rem !important;
        }
        div[role="dialog"] .stDownloadButton > button {
            min-height: 34px !important;
            height: 34px !important;
            padding: 0 .75rem !important;
            border-radius: 9px !important;
            font-size: .78rem !important;
            font-weight: 700 !important;
            border: 1px solid rgba(70,190,255,.55) !important;
            background: rgba(8,34,55,.92) !important;
            color: #f4f8ff !important;
        }
        div[role="dialog"] .stDownloadButton > button:hover {
            border-color: #49d7ff !important;
            background: rgba(12,55,82,.98) !important;
        }
        /* V1 · ocultar la X nativa y usar controles explícitos del reporte. */
        div[role="dialog"] button[aria-label="Close"],
        div[role="dialog"] button[aria-label="Cerrar"],
        [data-testid="stDialog"] [data-testid="stDialogCloseButton"],
        [data-testid="stDialog"] button[data-testid="stBaseButton-headerNoPadding"] {
            display:none !important;
        }
        /* CERRAR rojo · PNG celeste · PDF verde. */
        div[role="dialog"] [data-testid="stHorizontalBlock"]:first-of-type > div:nth-child(2) button {
            background:linear-gradient(90deg,#b83232 0%,#df4b4b 100%) !important;
            border:1px solid rgba(255,125,125,.78) !important;
            color:#fff !important;
            box-shadow:0 7px 18px rgba(160,35,35,.22) !important;
        }
        div[role="dialog"] [data-testid="stHorizontalBlock"]:first-of-type > div:nth-child(3) button {
            background:linear-gradient(90deg,#0d86bd 0%,#18a9c5 100%) !important;
            border:1px solid rgba(102,226,255,.72) !important;
            color:#fff !important;
        }
        div[role="dialog"] [data-testid="stHorizontalBlock"]:first-of-type > div:nth-child(4) button {
            background:linear-gradient(90deg,#198754 0%,#24a76a 100%) !important;
            border:1px solid rgba(105,225,155,.72) !important;
            color:#fff !important;
            box-shadow:0 7px 18px rgba(24,135,84,.22) !important;
        }
        .patan-preview-title {
            font-size: 1.18rem;
            line-height: 1.1;
            font-weight: 800;
            letter-spacing: .02em;
            color: #f5f7fb;
            white-space: nowrap;
        }
        .patan-preview-wrap {
            width: 100%;
            height: calc(100vh - 72px);
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }
        .patan-preview-wrap img {
            display: block;
            max-width: 100%;
            max-height: 100%;
            width: auto;
            height: auto;
            object-fit: contain;
            border-radius: 12px;
            box-shadow: 0 0 0 1px rgba(80,190,255,.22), 0 18px 45px rgba(0,0,0,.28);
        }
        </style>
        """, unsafe_allow_html=True)

        h1,h2,h3,h4 = st.columns([7.75,0.75,0.75,0.75], gap="small")
        with h1:
            st.markdown('<div class="patan-preview-title">VISTA PREVIA · REPORTE DE GESTIÓN</div>', unsafe_allow_html=True)
        with h2:
            if st.button("CERRAR", key="preview_close", use_container_width=True, help="Cerrar la vista previa"):
                st.rerun()
        with h3:
            st.download_button(
                "PNG",
                png_data,
                file_name=pdf_name.replace('.pdf','.png'),
                mime="image/png",
                use_container_width=True,
                help="Guardar la misma lámina de la vista previa en PNG",
                key="preview_download_png",
            )
        with h4:
            st.download_button(
                "PDF",
                pdf_data,
                file_name=pdf_name,
                mime="application/pdf",
                use_container_width=True,
                help="Guardar esta misma lámina como PDF",
                key="preview_download_pdf",
            )

        st.markdown(
            f'<div class="patan-preview-wrap"><img src="data:image/png;base64,{encoded}" alt="Vista previa del reporte de gestión"></div>',
            unsafe_allow_html=True,
        )

    report_filename=f"PATAN_Reporte_{report_user['username']}_{date.today().isoformat()}.pdf"
    ex1,ex2,ex3=st.columns([7.7,1.6,.7])
    with ex2:
        st.markdown("<div class='patan-export-label'>EXPORTACIÓN</div>",unsafe_allow_html=True)
        if st.button("VISTA PREVIA",use_container_width=False,type="primary",key="open_report_preview",help="Abrir la lámina completa y elegir PNG o PDF"):
            # V17: generar la lámina sólo cuando el usuario abre la vista previa.
            # Evita bloquear el cambio de página CONTROL → REPORTE con un render gráfico innecesario.
            report_png = build_report_image(report_user['display_name'], report_jurisdiction, report_rows, report_tasks, ASSETS, APP_VERSION)
            report_pdf = png_to_pdf(report_png)
            preview_report_graphic(report_png, report_pdf, report_filename)

elif page == "TRABAJOS":
    header("TRABAJOS")

    # KPIs de la propia bandeja
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Trabajos", len(all_cases))
    k2.metric("Trabajos", sum(1 for c in all_cases if c.get("case_type") == "Trabajo"))
    k3.metric("Notas / otros", sum(1 for c in all_cases if c.get("case_type") != "Trabajo"))
    k4.metric("Con movimiento", sum(1 for c in all_cases if c.get("last_movement")))

    st.write("")
    f1, f2, f3, f4 = st.columns([1, 1.2, 2.4, .8])
    status_filter = f1.selectbox("Estado", ["TODOS", "ROJO", "AMARILLO", "VERDE"], key="cases_status")
    type_values = sorted({c.get("case_type") or "Sin tipo" for c in all_cases})
    type_filter = f2.selectbox("Tipo", ["TODOS"] + type_values, key="cases_type")
    q = f3.text_input("Buscar", placeholder="N° trabajo, identificador, persona, asunto, trámite o agente…", key="cases_search")
    if f4.button("＋ NUEVO", use_container_width=True, type="primary", disabled=not can_edit):
        st.session_state.case_mode = "Nuevo trabajo"
        st.session_state.selected_case_id = None
        st.rerun()

    # El botón + NUEVO abre el alta inmediatamente aquí, arriba de la bandeja.
    # Así el usuario no tiene que buscar un formulario al final de la página.
    # Alta de caso nueva en un expander para no ensuciar la bandeja.
    with st.expander("＋ ALTA DE NUEVO TRABAJO", expanded=st.session_state.get("case_mode") == "Nuevo trabajo"):
        with st.form("new_case_form", clear_on_submit=True):
            c1, c2 = st.columns([1, 1.4])
            case_number = c1.text_input("N° trabajo / documento")
            case_type = c2.selectbox("Tipo de trabajo", ["Trabajo", "Nota electrónica", "Verificación", "Otro"])
            taxpayer = st.text_input("Persona / interesado")
            cuit = st.text_input("CUIT")
            title = st.text_area("Asunto", height=80)
            c3, c4 = st.columns(2)
            task = c3.text_input("Tarea", value="Revisión, Tratamiento y/o Autorización")
            procedure = c4.text_input("Trámite", value="Trabajo")
            c5, c6 = st.columns(2)
            if is_admin or is_supervisor:
                assignable_new = {u["display_name"]: u["id"] for u in active_users if u.get("role") in ("USUARIO","SUPERVISOR") and int(u.get("is_agent") or 0)==1}
                responsible_label_new = c5.selectbox("Agente", list(assignable_new.keys()), key="new_case_responsible")
                responsible_user_id_new = assignable_new.get(responsible_label_new)
                responsible = responsible_label_new
            else:
                responsible_user_id_new = int(current_user["id"])
                responsible = current_user["display_name"]
                c5.text_input("Agente", value=responsible, disabled=True)
            supervisor = c6.text_input("Supervisor")
            c7, c8, c9 = st.columns(3)
            received = c7.date_input("Fecha entrada", value=date.today())
            assigned = c8.date_input("Asignación", value=date.today())
            registered = c9.date_input("Registro orden", value=date.today())
            c10, c11 = st.columns(2)
            complexity = c10.selectbox("Clasificación", ["ESTANDAR", "COMPLEJO"], format_func=lambda x: "ESTÁNDAR" if x == "ESTANDAR" else "COMPLEJO")
            c11.text_input("Semáforo", value="ACTIVO", disabled=True)
            memo_applies = True
            selected_agent = next((u for u in active_users if int(u["id"])==int(responsible_user_id_new or 0)), current_user)
            jurisdiction_new = st.text_input("Jurisdicción", value=selected_agent.get("jurisdiction") or current_user.get("jurisdiction") or "RIO GRANDE", help="Se hereda de la jurisdicción del agente. Puede corregirse antes de firmar.")
            notes = st.text_area("Notas", height=70)
            sign_new = st.checkbox("Firmar registro al crear", value=False, help="Firma: confirmo que los datos fueron revisados. Si no se firma, queda como BORRADOR y puede editarse libremente.")
            if st.form_submit_button("CREAR TRABAJO", use_container_width=False, type="primary", disabled=not can_edit):
                if not case_number.strip():
                    st.error("Ingresá el número de trabajo/documento.")
                elif not responsible_user_id_new:
                    st.error("Todo trabajo activo debe tener un agente asignado.")
                else:
                    try:
                        new_id = db.upsert_case({
                            "case_number": case_number.strip().upper(), "case_type": case_type,
                            "taxpayer_name": taxpayer.strip(), "cuit": cuit.strip(), "title": title.strip(),
                            "task": task.strip(), "procedure": procedure.strip(), "responsible": responsible.strip(),
                            "responsible_user_id": responsible_user_id_new, "supervisor": supervisor.strip(), "date_received": received.isoformat(),
                            "date_assigned": assigned.isoformat(), "date_registered": registered.isoformat(),
                            "complexity": complexity, "memo_applies": int(memo_applies), "notes": notes.strip(),
                            "jurisdiction": jurisdiction_new.strip(), "record_status": "BORRADOR",
                        })
                        if sign_new: db.sign_record("case",new_id,int(current_user["id"]))
                        db.log_audit(int(current_user["id"]), "CREATE", "case", new_id, details=case_number.strip().upper())
                        st.session_state.selected_case_id = new_id
                        st.session_state.case_mode = case_number.strip().upper()
                        st.success("Trabajo creado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"No se pudo crear: {e}")

    filtered = []
    for c in all_cases:
        s0 = case_states[c["id"]]
        hay = " ".join(str(c.get(k) or "") for k in ["case_number", "cuit", "taxpayer_name", "title", "procedure", "responsible"]).lower()
        if status_filter != "TODOS" and s0.label != status_filter:
            continue
        if type_filter != "TODOS" and (c.get("case_type") or "Sin tipo") != type_filter:
            continue
        if q and q.lower() not in hay:
            continue
        filtered.append(c)

    table = []
    for c in filtered:
        s0 = case_states[c["id"]]
        table.append({
            "": s0.icon,
            "N° Doc. / Trabajo": c["case_number"],
            "Último movimiento": fmt_date(c.get("last_movement")),
            "Días": s0.days_without_activity if s0.days_without_activity is not None else "—",
            "Clasificación": "COMPLEJO" if str(c.get("complexity") or "").upper().startswith("COMP") else "ESTÁNDAR",
            "Plazo": s0.objective_days if s0.objective_days is not None else "—",
            "% consumido": round(s0.objective_pct, 1) if s0.objective_pct is not None else "—",
            "Restan": (s0.objective_days - s0.elapsed_days) if s0.objective_days is not None and s0.elapsed_days is not None else "—",
            "Próxima tarea": (next_task_for_case(c["id"]) or {}).get("title") or "—",
            "Vence": fmt_date((next_task_for_case(c["id"]) or {}).get("due_date")),
            "Tarea": c.get("task") or "Revisión, Tratamiento y/o Autorización",
            "Asunto": c.get("taxpayer_name") or c.get("title") or "—",
            "Trámite": c.get("procedure") or c.get("case_type") or "—",
            "Agente": c.get("responsible_display") or c.get("responsible") or "—",
            "Fecha entrada": fmt_date(c.get("date_received")),
            "Estado": s0.label,
        })

    df_cases = pd.DataFrame(table)
    selected_case_id = st.session_state.get("selected_case_id")
    if df_cases.empty:
        st.info("No hay trabajos que coincidan con los filtros.")
    else:
        # Selección directa de fila cuando la versión de Streamlit lo soporta.
        try:
            event = st.dataframe(
                df_cases,
                use_container_width=True,
                hide_index=True,
                height=390,
                on_select="rerun",
                selection_mode="single-row",
                key="cases_grid",
            )
            rows_sel = event.selection.rows if event and hasattr(event, "selection") else []
            if rows_sel:
                selected_case_id = filtered[rows_sel[0]]["id"]
                st.session_state.selected_case_id = selected_case_id
                st.session_state.case_mode = filtered[rows_sel[0]]["case_number"]
        except TypeError:
            st.dataframe(df_cases, use_container_width=True, hide_index=True, height=390)

    st.caption("Seleccioná una fila para abrir el trabajo. TRABAJOS es la fuente operativa; CONTROL DE GESTIÓN se recalcula automáticamente.")
    st.divider()

    # Selector de respaldo + ficha
    labels = {f"{c['case_number']} · {c.get('taxpayer_name') or c.get('title') or ''}": c["id"] for c in filtered}
    if labels:
        ids = list(labels.values())
        if selected_case_id not in ids:
            selected_case_id = ids[0]
        default_idx = ids.index(selected_case_id)
        select_label = st.selectbox("Trabajo abierto", list(labels.keys()), index=default_idx, key="case_open_select")
        selected_case_id = labels[select_label]
        st.session_state.selected_case_id = selected_case_id
        case = next(c for c in all_cases if c["id"] == selected_case_id)
        state = case_states[selected_case_id]

        h1, h2, h3, h4, h5 = st.columns([2.2, 1.1, 1.1, 1.1, 1.1])
        h1.markdown(f"### {state.icon} {case['case_number']}")
        h1.caption(case.get("taxpayer_name") or case.get("title") or "Sin asunto")
        h2.metric("Estado", state.label)
        h3.metric("Último movimiento", fmt_date(case.get("last_movement")))
        h4.metric("Días", state.days_without_activity if state.days_without_activity is not None else "—")
        h5.metric("Plazo", f"{state.objective_pct:.0f}%" if state.objective_pct is not None else "—")
        st.caption(state.reason)

        tab1, tab2, tab_tasks, tab3 = st.tabs(["📁 FICHA", "🕒 MOVIMIENTOS", "✅ TAREAS", "✚ ÚLTIMA ACTIVIDAD"])

        with tab1:
            left, right = st.columns([1.5, 1])
            with left:
                st.markdown("#### Datos del trabajo")
                case_types = ["Trabajo", "Nota electrónica", "Verificación", "Otro"]
                current_type = case.get("case_type") if case.get("case_type") in case_types else "Otro"
                signed_case = case.get("record_status") == "FIRMADO"
                rectify_case = st.checkbox("Rectificar registro firmado", value=False, disabled=not signed_case, key=f"rectify_case_{selected_case_id}", help="Una rectificación no borra la firma anterior: registra quién cambió qué, cuándo y por qué.")
                rect_reason = st.text_input("Motivo de rectificación", key=f"rect_reason_{selected_case_id}", disabled=not rectify_case, placeholder="Ej.: corrección de nombre cargado por error")
                edit_locked = signed_case and not rectify_case
                st.caption("🔒 FIRMADO" if signed_case else "✎ BORRADOR · editable hasta firmar")
                with st.form(f"edit_case_{selected_case_id}"):
                    r1, r2 = st.columns([1, 1.3])
                    case_number = r1.text_input("N° trabajo", value=case.get("case_number") or "")
                    case_type = r2.selectbox("Tipo", case_types, index=case_types.index(current_type))
                    taxpayer = st.text_input("Persona / interesado", value=case.get("taxpayer_name") or "")
                    cuit = st.text_input("CUIT", value=case.get("cuit") or "")
                    title = st.text_area("Asunto", value=case.get("title") or "", height=80)
                    task = st.text_input("Tarea", value=case.get("task") or "Revisión, Tratamiento y/o Autorización")
                    procedure = st.text_input("Trámite", value=case.get("procedure") or case_type)
                    r3, r4 = st.columns(2)
                    if is_admin or is_supervisor:
                        assignable = {u["display_name"]: u["id"] for u in active_users if u.get("role") in ("USUARIO","SUPERVISOR") and int(u.get("is_agent") or 0)==1}
                        assign_labels = list(assignable.keys())
                        current_uid = case.get("responsible_user_id")
                        current_label = next((n for n, uid in assignable.items() if uid == current_uid), assign_labels[0] if assign_labels else "")
                        responsible_label = r3.selectbox("Agente", assign_labels, index=assign_labels.index(current_label), key=f"responsible_{selected_case_id}")
                        responsible_user_id = assignable.get(responsible_label)
                        responsible = responsible_label
                    else:
                        responsible_user_id = int(current_user["id"])
                        responsible = current_user["display_name"]
                        r3.text_input("Agente", value=responsible, disabled=True)
                    supervisor = r4.text_input("Supervisor", value=case.get("supervisor") or "")
                    r5, r6, r7 = st.columns(3)
                    received = r5.date_input("Fecha entrada", value=parse_date(case.get("date_received")) or date.today())
                    assigned = r6.date_input("Asignación", value=parse_date(case.get("date_assigned")) or received)
                    registered = r7.date_input("Registro orden", value=parse_date(case.get("date_registered")) or received)
                    r8, r9 = st.columns(2)
                    complexity = r8.selectbox("Clasificación", ["ESTANDAR", "COMPLEJO"], index=1 if str(case.get("complexity") or "").upper().startswith("COMP") else 0, format_func=lambda x: "ESTÁNDAR" if x == "ESTANDAR" else "COMPLEJO")
                    r9.text_input("Semáforo", value="ACTIVO", disabled=True)
                    memo_applies = True
                    jurisdiction_edit = st.text_input("Jurisdicción", value=case.get("jurisdiction") or current_user.get("jurisdiction") or "", disabled=edit_locked, help="Todos los trabajos y tareas del agente heredan esta jurisdicción.")
                    notes = st.text_area("Notas", value=case.get("notes") or "", height=75, disabled=edit_locked)
                    sign_case_now = st.checkbox("Firmar después de guardar", value=False, disabled=signed_case, help="Al firmar, el registro queda fijo. Las correcciones posteriores requieren rectificación trazable.")
                    if st.form_submit_button("GUARDAR CAMBIOS", use_container_width=False, type="primary", disabled=not can_edit or edit_locked):
                        try:
                            db.upsert_case({
                                "case_number": case_number.strip().upper(), "case_type": case_type,
                                "taxpayer_name": taxpayer.strip(), "cuit": cuit.strip(), "title": title.strip(),
                                "task": task.strip(), "procedure": procedure.strip(), "responsible": responsible.strip(),
                                "responsible_user_id": responsible_user_id, "supervisor": supervisor.strip(), "date_received": received.isoformat(),
                                "date_assigned": assigned.isoformat(), "date_registered": registered.isoformat(),
                                "complexity": complexity, "memo_applies": int(memo_applies), "notes": notes.strip(), "jurisdiction": jurisdiction_edit.strip(),
                            }, selected_case_id)
                            if signed_case and rectify_case: db.rectify_record("case",selected_case_id,int(current_user["id"]),rect_reason or "Rectificación")
                            if sign_case_now: db.sign_record("case",selected_case_id,int(current_user["id"]))
                            db.log_audit(int(current_user["id"]), "UPDATE", "case", selected_case_id, details=case_number.strip().upper())
                            st.success("Trabajo actualizado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"No se pudo guardar: {e}")
            with right:
                st.markdown("#### Control automático")
                st.info(state.reason)
                st.write(f"**Clasificación:** {'COMPLEJO' if str(case.get('complexity') or '').upper().startswith('COMP') else 'ESTÁNDAR'}")
                st.write(f"**Plazo objetivo:** {state.objective_days or '—'} días")
                st.write(f"**Transcurridos:** {state.elapsed_days if state.elapsed_days is not None else '—'} días")
                st.write(f"**Último informe:** {fmt_date(case.get('last_progress_report'))}")
                st.write(f"**Días desde informe:** {state.days_since_progress if state.days_since_progress is not None else '—'}")
                hitos = case_hitos(case, settings)
                st.markdown("##### Hitos")
                for name, dt in hitos.items():
                    st.write(f"**{name.replace('_',' ').title()}:** {dt.strftime('%d/%m/%Y') if dt else '—'}")

                st.divider()
                st.markdown("#### Estado y cierre")
                if can_edit:
                    b1,b2=st.columns(2)
                    if case.get("status_stage") == "SUSPENDIDO":
                        if b1.button("▶ REANUDAR TRABAJO",use_container_width=True,key=f"resume_{selected_case_id}"):
                            db.resume_case(selected_case_id,int(current_user["id"])); st.rerun()
                    else:
                        if b1.button("⏸ SUSPENDER TRABAJO",use_container_width=True,key=f"suspend_{selected_case_id}"):
                            db.suspend_case(selected_case_id,int(current_user["id"])); st.rerun()
                with st.form(f"close_case_{selected_case_id}"):
                    result = st.text_input("Resultado final", placeholder="Ej.: ajuste conformado, sin ajustes, derivado…")
                    close_reason = st.text_area("Motivo de cierre", height=65)
                    close_notes = st.text_area("Observación final", height=65)
                    doc_ok = st.checkbox("Estado documental completo")
                    confirm_close = st.checkbox("Confirmo cerrar y pasar a HISTÓRICO")
                    submitted=st.form_submit_button("CERRAR Y PASAR A HISTÓRICO", use_container_width=False, disabled=not can_edit)
                    if submitted:
                        if not confirm_close: st.warning("Marcá la confirmación de cierre.")
                        else:
                            try:
                                db.close_case_checked(selected_case_id,int(current_user["id"]),close_reason,result,close_notes,doc_ok)
                                st.session_state.pop("selected_case_id",None); st.success("Trabajo cerrado y enviado a HISTÓRICO."); st.rerun()
                            except Exception as e: st.error(str(e))

        with tab2:
            movements = db.list_movements(selected_case_id)
            if movements:
                mdf = pd.DataFrame([{
                    "Fecha": fmt_date(m["movement_date"]),
                    "Acción": m["movement_type"],
                    "Computa semáforo": "Sí" if m["useful_activity"] else "No",
                    "Informe avance": "Sí" if m["is_progress_report"] else "No",
                    "Firma": "🔒 FIRMADO" if m.get("record_status")=="FIRMADO" else "✎ BORRADOR",
                    "Observación": m.get("description") or "",
                } for m in movements])
                st.dataframe(mdf, use_container_width=True, hide_index=True, height=340)
                st.caption("El último movimiento del trabajo se obtiene automáticamente de la actividad más reciente cargada.")
            else:
                st.info("Todavía no hay movimientos cargados.")

        with tab_tasks:
            st.markdown("#### Tracking de actuaciones y vencimientos")
            ctasks=db.list_tasks([selected_case_id],include_done=True)
            active_ct=[t for t in ctasks if t.get("status") not in ("CUMPLIDA","CANCELADA")]
            hist_ct=[t for t in ctasks if t.get("status") in ("CUMPLIDA","CANCELADA")]
            ta,tb=st.tabs([f"ACTIVAS ({len(active_ct)})",f"HISTÓRICO ({len(hist_ct)})"])
            with ta:
                if active_ct: st.dataframe(pd.DataFrame(task_rows(active_ct)),use_container_width=True,hide_index=True,height=300)
                else: st.info("Sin tareas activas.")
                if can_edit:
                    render_task_actions(active_ct,f"case_{selected_case_id}")
                    st.divider()
                    render_new_tracking_task(case,f"case_new_{selected_case_id}")
            with tb:
                if hist_ct: st.dataframe(pd.DataFrame(task_rows(hist_ct)),use_container_width=True,hide_index=True,height=320)
                else: st.info("Todavía no hay tareas finalizadas.")

        with tab3:
            manual_activity_widget(case, "casos")


elif page == "HISTÓRICO":
    header("HISTÓRICO", "Trabajos cerrados · conservados con todo su historial de movimientos")
    closed_cases = db.list_closed_cases_for_users(visible_user_ids)
    if not closed_cases:
        st.info("Todavía no hay trabajos cerrados.")
    else:
        hrows = []
        for c in closed_cases:
            hrows.append({
                "N° trabajo": c["case_number"],
                "Persona / asunto": c.get("taxpayer_name") or c.get("title") or "—",
                "Agente": c.get("responsible_display") or c.get("responsible") or "—",
                "Último movimiento": fmt_date(c.get("last_movement")),
                "Cerrado": fmt_date(c.get("closed_at")),
                "Resultado": c.get("closure_result") or "—",
                "Motivo": c.get("closed_reason") or "—",
            })
        st.dataframe(pd.DataFrame(hrows), use_container_width=True, hide_index=True, height=360)
        labels_h = {f"{c['case_number']} · {c.get('taxpayer_name') or c.get('title') or ''}": c for c in closed_cases}
        chosen_h = st.selectbox("Ver trabajo cerrado", list(labels_h.keys()), key="historic_case_select")
        hc = labels_h[chosen_h]
        st.markdown(f"### {hc['case_number']}")
        st.caption(hc.get("taxpayer_name") or hc.get("title") or "")
        c1, c2, c3 = st.columns(3)
        c1.metric("Fecha de cierre", fmt_date(hc.get("closed_at")))
        c2.metric("Último movimiento", fmt_date(hc.get("last_movement")))
        c3.metric("Agente", hc.get("responsible_display") or hc.get("responsible") or "—")
        if hc.get("closed_reason"):
            st.info(hc["closed_reason"])
        movements = db.list_movements(hc["id"])
        if movements:
            st.dataframe(pd.DataFrame([{
                "Fecha": fmt_date(m["movement_date"]),
                "Acción": m["movement_type"],
                "Observación": m.get("description") or "",
            } for m in movements]), use_container_width=True, hide_index=True)
        if is_admin:
            if st.button("REABRIR TRABAJO", key=f"reopen_{hc['id']}"):
                db.reopen_case(hc["id"])
                db.log_audit(int(current_user["id"]),"REOPEN","case",hc["id"])
                st.success("Trabajo reabierto y devuelto a TRABAJOS.")
                st.rerun()

elif page == "TAREAS":
    header("TAREAS", "Actuaciones, notificaciones, vencimientos, respuestas y prórrogas")
    st.markdown(f"Fuente de referencia: [**Calendario oficial COMARB**]({COMARB_CALENDAR_URL})")
    tasks=db.list_tasks([c["id"] for c in all_cases],include_done=True)
    active_t=[t for t in tasks if t.get("status") not in ("CUMPLIDA","CANCELADA")]
    hist_t=[t for t in tasks if t.get("status") in ("CUMPLIDA","CANCELADA")]
    t1,t2,t3=st.tabs([f"📌 ACTIVAS ({len(active_t)})",f"🗂 HISTÓRICO ({len(hist_t)})","＋ NUEVA TAREA"])
    with t1:
        if active_t:
            st.dataframe(pd.DataFrame(task_rows(active_t)),use_container_width=True,hide_index=True,height=430)
            render_task_actions(active_t,"global")
        else: st.info("No hay tareas activas.")
    with t2:
        if hist_t: st.dataframe(pd.DataFrame(task_rows(hist_t)),use_container_width=True,hide_index=True,height=460)
        else: st.info("Todavía no hay tareas finalizadas.")
    with t3:
        if not all_cases: st.warning("No hay trabajos activos disponibles.")
        else:
            cmap={f"{c['case_number']} · {c.get('taxpayer_name') or c.get('title') or ''}":c for c in all_cases}
            sel=st.selectbox("Trabajo",list(cmap.keys()),key="task_global_case")
            render_new_tracking_task(cmap[sel],"global_new")

elif page == "NUEVA ACTUACIÓN":
    header("NUEVA ACTUACIÓN", "Elegí un trabajo y cargá la última actividad")
    if not all_cases:
        st.warning("Primero cargá un trabajo.")
        st.stop()
    labels = {f"{c['case_number']} · {c.get('taxpayer_name') or c.get('title') or ''}": c for c in all_cases}
    chosen = st.selectbox("Trabajo", list(labels.keys()))
    manual_activity_widget(labels[chosen], "actuacion")

elif page == "💡 SUGERENCIAS":
    header("💡 SUGERENCIAS", "Canal corto y directo para mejorar PATÁN")
    st.info("¿Algo puede funcionar mejor? Contá la mejora en pocas palabras: qué cambiarías y para qué. Máximo 300 caracteres.")
    with st.form("suggestion_form",clear_on_submit=True):
        msg=st.text_area("Sugerencia",max_chars=300,height=90,placeholder="Ej.: En Tareas, agregar filtro por destinatario para encontrar más rápido una nota.",help="Breve, concreta y accionable. Máximo 300 caracteres.")
        if st.form_submit_button("💡 ENVIAR SUGERENCIA",use_container_width=False,type="primary"):
            try:
                sid=db.add_suggestion(int(current_user['id']),msg)
                db.log_audit(int(current_user['id']),"CREATE","suggestion",sid,details=msg[:80])
                st.success("Sugerencia enviada al administrador."); st.rerun()
            except Exception as e: st.error(str(e))
    st.markdown("---")
    st.caption("Uso educativo y demostrativo · Sin fines comerciales · La información cargada es responsabilidad exclusiva del usuario.")
    if is_admin:
        st.markdown("### Bandeja del administrador")
        suggestions=db.list_suggestions()
        if suggestions:
            st.dataframe(pd.DataFrame([{"Fecha":x['created_at'],"Agente":x['display_name'],"Estado":x['status'],"Sugerencia":x['message'],"Nota ADM":x.get('admin_note') or ''} for x in suggestions]),use_container_width=True,hide_index=True,height=330)
            smap={f"#{x['id']} · {x['display_name']} · {x['message'][:55]}":x for x in suggestions}
            sl=st.selectbox("Gestionar sugerencia",list(smap.keys()))
            sx=smap[sl]
            c1,c2=st.columns(2)
            new_status=c1.selectbox("Estado",["NUEVA","EN EVALUACIÓN","IMPLEMENTADA","DESCARTADA"],index=["NUEVA","EN EVALUACIÓN","IMPLEMENTADA","DESCARTADA"].index(sx['status']))
            note=c2.text_input("Nota interna",value=sx.get('admin_note') or '')
            g1,g2=st.columns(2)
            if g1.button("GUARDAR ESTADO",use_container_width=True):
                db.update_suggestion(int(sx['id']),new_status,note); st.rerun()
            if g2.button("PUBLICAR COMO NOVEDAD",use_container_width=True,disabled=new_status!='IMPLEMENTADA'):
                nid=db.add_news("Mejora implementada",sx['message'],int(current_user['id']))
                db.update_suggestion(int(sx['id']),"IMPLEMENTADA",note)
                db.log_audit(int(current_user['id']),"CREATE","news",nid,details=sx['message'][:80]); st.success("Novedad publicada."); st.rerun()
        else: st.info("No hay sugerencias todavía.")

elif page == "🔔 NOVEDADES":
    header("🔔 NOVEDADES", "Cambios y mejoras de PATÁN")
    news=db.list_news(int(current_user['id']))
    unread=[n for n in news if not n.get('is_read')]
    if unread:
        st.warning(f"Tenés {len(unread)} novedad(es) sin leer. El aviso seguirá titilando hasta que las leas.")
        if st.button("MARCAR TODAS COMO LEÍDAS",use_container_width=False,type="primary"):
            db.mark_news_read(int(current_user['id'])); st.rerun()
    if news:
        for n in news:
            icon="🔵 NUEVA" if not n.get('is_read') else "✓ LEÍDA"
            with st.container(border=True):
                st.markdown(f"### {icon} · {n['title']}")
                st.caption(f"{n['created_at']} · {n.get('author') or 'PATÁN'}")
                st.write(n['message'])
                if not n.get('is_read') and st.button("MARCAR COMO LEÍDA",key=f"read_news_{n['id']}"):
                    db.mark_news_read(int(current_user['id']),int(n['id'])); st.rerun()
    else: st.info("No hay novedades publicadas.")
    if is_admin:
        st.divider(); st.markdown("### Publicar novedad")
        with st.form("new_news",clear_on_submit=True):
            nt=st.text_input("Título",max_chars=80,placeholder="Ej.: Nuevo filtro en Tareas")
            nm=st.text_area("Mensaje",max_chars=500,height=100,placeholder="Explicá el cambio en forma breve y directa.")
            if st.form_submit_button("PUBLICAR NOVEDAD",use_container_width=False,type="primary"):
                try:
                    nid=db.add_news(nt,nm,int(current_user['id'])); db.log_audit(int(current_user['id']),"CREATE","news",nid,details=nt); st.success("Novedad publicada."); st.rerun()
                except Exception as e: st.error(str(e))

elif page == "AGENTES":
    header("AGENTES", "Cada agente es un usuario de PATÁN · carga activa y situación de cartera")
    users_all = [u for u in db.list_users(active_only=False) if int(u.get("is_agent") or 0)==1]
    rows = []
    for u in users_all:
        ucases = [c for c in all_cases if c.get("responsible_user_id") == u["id"]]
        item = {
            "Agente": u["display_name"],
            "Usuario": u["username"],
            "Estado": "Activo" if u["active"] else "Pausado",
            "Rol": {"ADMIN":"Administrador","SUPERVISOR":"Supervisor","USUARIO":"Usuario"}.get(u["role"],u["role"]),
            "Trabajos activos": len(ucases),
            "🟢": 0, "🟡": 0, "🔴": 0, "🔵": 0,
            "Tareas vencidas": sum(1 for t in open_tasks if t.get("owner_user_id")==u["id"] and t.get("status")=="VENCIDA"),
            "Determinado": 0.0, "Conformado": 0.0,
        }
        for c in ucases:
            cs = case_states[c["id"]]
            item[cs.icon] += 1
            item["Determinado"] += float(c.get("amount_determined") or 0)
            item["Conformado"] += float(c.get("amount_confirmed") or 0)
        rows.append(item)
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"Referencia operativa: {settings['active_cases_target']} trabajos activos en paralelo por agente.")

elif page == "REUNIONES":
    header("REUNIONES", "Seguimiento mensual · decisiones · compromisos")
    with st.form("meeting_form"):
        d = st.date_input("Fecha", value=date.today())
        mt = st.selectbox("Tipo", ["Agente / Jefatura de División", "División / Departamento / Dirección", "Otra"])
        case_options = {"Sin trabajo específico": None, **{c["case_number"]: c["id"] for c in all_cases}}
        csel = st.selectbox("Trabajo", list(case_options.keys()))
        issue = st.text_area("Situación / desvío / riesgo")
        decision = st.text_area("Decisión")
        commitment = st.text_input("Compromiso")
        col1, col2 = st.columns(2)
        owner = col1.text_input("Responsable")
        due = col2.date_input("Plazo", value=date.today())
        if st.form_submit_button("Registrar reunión", use_container_width=False, type="primary", disabled=not can_edit):
            mid=db.add_meeting({"meeting_date": d.isoformat(), "meeting_type": mt, "case_id": case_options[csel], "issue": issue, "decision": decision, "commitment": commitment, "owner": owner, "due_date": due.isoformat()})
            db.log_audit(int(current_user["id"]),"CREATE","meeting",mid,details=mt)
            st.success("Reunión registrada.")
            st.rerun()
    meetings = db.list_meetings([c["id"] for c in all_cases])
    if meetings:
        st.dataframe(pd.DataFrame(meetings)[["meeting_date","meeting_type","case_number","issue","decision","commitment","owner","due_date","status"]], use_container_width=True, hide_index=True)

elif page == "USUARIOS":
    header("USUARIOS", "Roles, jurisdicciones y seguridad de acceso")
    st.caption("Roles disponibles: Usuario, Supervisor y Administrador. El acceso técnico es ADM / PATÁN / Administrador / Agente: No.")
    users_now=db.list_users(active_only=False)
    if users_now:
        st.dataframe(pd.DataFrame([{
            "Usuario":u['username'],"Nombre":u['display_name'],"Rol":{"ADMIN":"Administrador","SUPERVISOR":"Supervisor","USUARIO":"Usuario"}.get(u['role'],u['role']),
            "Agente":"Sí" if u.get('is_agent') else "No","Jurisdicción":u.get('jurisdiction') or '—',"Estado":"ACTIVO" if u['active'] else 'PAUSADO',
            "Último acceso":u.get('last_login_at') or '—',"Cambio clave":u.get('password_changed_at') or '—'
        } for u in users_now]),use_container_width=True,hide_index=True,height=280)
    st.markdown("### Gestión de usuarios")
    left_u,right_u=st.columns([1,1.35])
    with left_u:
        st.markdown("#### Agregar usuario")
        with st.form("new_user_form",clear_on_submit=True):
            username_new=st.text_input("Usuario",placeholder="Ej.: jperez",help="Identificador para ingresar a PATÁN.")
            display_new=st.text_input("Nombre y apellido",placeholder="Ej.: Juan Pérez")
            role_new=st.selectbox("Rol",["USUARIO","SUPERVISOR","ADMIN"],format_func=lambda x:{"USUARIO":"Usuario","SUPERVISOR":"Supervisor","ADMIN":"Administrador"}[x])
            is_agent_new=st.checkbox("Es agente",value=True,help="Si está activo, puede ser responsable de trabajos y tareas.")
            jurisdiction_new=st.text_input("Jurisdicción",value="RIO GRANDE",placeholder="Ej.: RIO GRANDE / USHUAIA / CABA",help="Los trabajos y tareas del agente heredan esta jurisdicción.")
            st.text_input("Clave inicial",value="1234",disabled=True,help="PATÁN asigna 1234 y obliga al usuario a cambiarla en el primer ingreso.")
            if st.form_submit_button("AGREGAR USUARIO",use_container_width=False,type="primary"):
                try:
                    uid=db.create_user(username_new,display_new,"1234",role_new,jurisdiction_new,int(is_agent_new))
                    db.log_audit(int(current_user['id']),"CREATE","user",uid,details=f"{display_new} @{username_new} · {role_new}")
                    st.success("Usuario creado con clave inicial 1234."); st.rerun()
                except Exception as e: st.error(f"No se pudo crear: {e}")
    with right_u:
        st.markdown("#### Editar / seguridad")
        if users_now:
            umap={f"{u['display_name']} · @{u['username']} · {'ACTIVO' if u['active'] else 'PAUSADO'}":u for u in users_now}
            ul=st.selectbox("Seleccionar usuario",list(umap.keys()),key="edit_user_select")
            ue=umap[ul]
            protected_adm=str(ue['username']).upper()=='ADM'
            with st.form(f"edit_user_{ue['id']}"):
                c1,c2=st.columns(2); uname=c1.text_input("Usuario",value=ue['username'],disabled=protected_adm); disp=c2.text_input("Nombre",value=ue['display_name'],disabled=protected_adm)
                role_edit=st.selectbox("Rol",["USUARIO","SUPERVISOR","ADMIN"],index=["USUARIO","SUPERVISOR","ADMIN"].index(ue['role'] if ue['role'] in ["USUARIO","SUPERVISOR","ADMIN"] else "USUARIO"),format_func=lambda x:{"USUARIO":"Usuario","SUPERVISOR":"Supervisor","ADMIN":"Administrador"}[x],disabled=protected_adm)
                agent_edit=st.checkbox("Es agente",value=bool(ue.get('is_agent')),disabled=protected_adm)
                jur_edit=st.text_input("Jurisdicción",value=ue.get('jurisdiction') or "RIO GRANDE",disabled=protected_adm,help="Ej.: RIO GRANDE / USHUAIA / CABA. Los trabajos y tareas del agente heredan este valor.")
                new_pin=st.text_input("Nueva clave (vacío = conservar)",type="password",max_chars=20,help="Entre 4 y 20 caracteres.")
                force_change=st.checkbox("Obligar cambio de clave en próximo ingreso",value=bool(ue.get('must_change_password')))
                if st.form_submit_button("GUARDAR CAMBIOS",use_container_width=False):
                    try:
                        db.update_user(int(ue['id']),username=ue['username'] if protected_adm else uname,display_name=ue['display_name'] if protected_adm else disp,pin=new_pin or None,role=ue['role'] if protected_adm else role_edit,jurisdiction=ue['jurisdiction'] if protected_adm else jur_edit,is_agent=ue['is_agent'] if protected_adm else int(agent_edit),must_change_password=int(force_change))
                        db.log_audit(int(current_user['id']),"UPDATE","user",int(ue['id']),details=f"{disp} @{uname}"); st.success("Usuario actualizado."); st.rerun()
                    except Exception as e: st.error(str(e))
            active_count=db.count_active_cases_for_user(int(ue['id']))
            if active_count: st.warning(f"Tiene {active_count} trabajo(s) activo(s). Reasignalos antes de pausar o eliminar.")
            a1,a2,a3=st.columns(3)
            if ue['active']:
                if a1.button("⏸ PAUSAR",use_container_width=True,disabled=protected_adm or active_count>0): db.update_user(int(ue['id']),active=0); st.rerun()
            else:
                if a1.button("▶ REACTIVAR",use_container_width=True): db.update_user(int(ue['id']),active=1); st.rerun()
            if a2.button("🔐 CERRAR SESIONES",use_container_width=True,disabled=protected_adm): db.force_logout_user(int(ue['id']),int(current_user['id'])); st.rerun()
            confirm=st.checkbox(f"Confirmo eliminar a {ue['display_name']}",disabled=protected_adm)
            if a3.button("🗑 ELIMINAR",use_container_width=True,disabled=protected_adm or not confirm or active_count>0): db.delete_user(int(ue['id'])); st.rerun()
            supervisors={u['display_name']:u['id'] for u in users_now if u['role']=='SUPERVISOR' and int(u['id'])!=int(ue['id'])}
            supopts=["Sin supervisor"]+list(supervisors.keys()); cursup=next((n for n,i in supervisors.items() if i==ue.get('supervisor_user_id')),"Sin supervisor")
            sup=st.selectbox("Supervisor",supopts,index=supopts.index(cursup))
            if st.button("GUARDAR SUPERVISOR",use_container_width=False): db.set_user_supervisor(int(ue['id']),supervisors.get(sup),int(current_user['id'])); st.rerun()

elif page == "SEGURIDAD":
    header("SEGURIDAD", "Auditoría, accesos y respaldo")
    s1,s2,s3=st.columns(3)
    s1.metric("Auditoría registrada",len(db.list_audit(10000)))
    logs=db.list_login_log(10000)
    s2.metric("Ingresos correctos",sum(int(x["success"])==1 for x in logs))
    s3.metric("Intentos fallidos",sum(int(x["success"])==0 for x in logs))
    tab_a,tab_l,tab_b=st.tabs(["AUDITORÍA","ACCESOS","BACKUP"] )
    with tab_a:
        audit=db.list_audit(1000)
        if audit:
            adf=pd.DataFrame(audit)
            st.dataframe(adf,use_container_width=True,hide_index=True,height=420)
            st.download_button("EXPORTAR AUDITORÍA CSV",adf.to_csv(index=False).encode("utf-8-sig"),"patan_auditoria.csv","text/csv")
        else: st.info("Todavía no hay eventos de auditoría.")
    with tab_l:
        if logs: st.dataframe(pd.DataFrame(logs),use_container_width=True,hide_index=True,height=420)
    with tab_b:
        st.success("PATÁN crea automáticamente un backup diario de la base en data/backups.")
        if st.button("CREAR / VERIFICAR BACKUP DE HOY",use_container_width=False): st.code(db.backup_database() or "Sin base")

elif page == "PARÁMETROS":
    header("PARÁMETROS", "Umbrales editables del motor de control")
    st.info("El plazo de referencia para trabajos complejos queda parametrizado y puede ajustarse sin tocar código.")
    with st.form("settings_form"):
        c1, c2, c3 = st.columns(3)
        vals = {}
        vals["yellow_inactivity_days"] = c1.number_input("Amarillo · días sin actividad", min_value=1, value=int(settings["yellow_inactivity_days"]))
        vals["red_inactivity_days"] = c1.number_input("Rojo · días sin actividad", min_value=1, value=int(settings["red_inactivity_days"]))
        vals["yellow_deadline_pct"] = c2.number_input("Amarillo · % plazo", min_value=1, max_value=100, value=int(settings["yellow_deadline_pct"]))
        vals["red_deadline_pct"] = c2.number_input("Rojo · % plazo", min_value=1, max_value=100, value=int(settings["red_deadline_pct"]))
        vals["yellow_progress_days"] = c3.number_input("Amarillo · días desde informe", min_value=1, value=int(settings["yellow_progress_days"]))
        vals["progress_interval_days"] = c3.number_input("Informe de avance cada", min_value=1, value=int(settings["progress_interval_days"]))
        d1, d2, d3 = st.columns(3)
        vals["standard_objective_days"] = d1.number_input("Plazo estándar", min_value=1, value=int(settings["standard_objective_days"]))
        vals["complex_objective_days"] = d2.number_input("Plazo complejo", min_value=1, value=int(settings["complex_objective_days"]))
        vals["active_cases_target"] = d3.number_input("Trabajos activos por agente", min_value=1, value=int(settings["active_cases_target"]))
        vals["preliminary_business_days"] = st.number_input("Análisis preliminar · días hábiles", min_value=1, value=int(settings["preliminary_business_days"]))
        vals["first_request_business_days"] = st.number_input("Primer requerimiento · días hábiles", min_value=1, value=int(settings["first_request_business_days"]))
        vals["final_report_business_days"] = st.number_input("Informe final · días hábiles", min_value=1, value=int(settings["final_report_business_days"]))
        if st.form_submit_button("Guardar parámetros", use_container_width=False, type="primary"):
            db.save_settings(vals)
            db.log_audit(int(current_user["id"]),"UPDATE","settings",details="Parámetros de control actualizados")
            st.success("Parámetros actualizados.")
            st.rerun()
