from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import re
import shutil
import time
from datetime import datetime, timedelta
from contextlib import contextmanager
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "patan.db"

# Rendimiento WEB/Supabase: evita repetir trabajo remoto en cada rerun de Streamlit.
_WEB_INIT_DONE = False
_LAST_OVERDUE_REFRESH = 0.0
_SETTINGS_CACHE: dict[str, Any] | None = None
_SETTINGS_CACHE_AT = 0.0
_ACTIVITY_TYPES_CACHE: dict[bool, tuple[float, list[dict[str, Any]]]] = {}



def _database_url() -> str | None:
    url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    if url:
        return url
    try:
        import streamlit as st
        return st.secrets.get("DATABASE_URL") or st.secrets.get("SUPABASE_DB_URL")
    except Exception:
        return None


def _pg_sql(sql: str) -> str:
    sql = re.sub(r"\s+COLLATE\s+NOCASE", "", sql, flags=re.I)
    sql = sql.replace("?", "%s")
    return sql


class _PGResult:
    def __init__(self, cursor, lastrowid=None):
        self._cursor = cursor
        self.lastrowid = lastrowid
    def fetchone(self): return self._cursor.fetchone()
    def fetchall(self): return self._cursor.fetchall()


class _PGCompat:
    _ID_TABLES = {"users","cases","movements","meetings","activity_types","case_tasks","audit_log","login_log","rectifications","suggestions","news"}
    def __init__(self, conn): self._conn = conn
    def execute(self, sql: str, params=()):
        from psycopg.rows import dict_row
        q = _pg_sql(sql.strip())
        ignore = bool(re.match(r"^INSERT\s+OR\s+IGNORE\s+INTO", q, re.I))
        if ignore:
            q = re.sub(r"^INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", q, flags=re.I)
            q += " ON CONFLICT DO NOTHING"
        m = re.match(r"^INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", q, re.I)
        wants_id = bool(m and m.group(1).lower() in self._ID_TABLES and "RETURNING" not in q.upper() and not ignore)
        if wants_id: q += " RETURNING id"
        cur = self._conn.cursor(row_factory=dict_row)
        cur.execute(q, params)
        lastrowid = None
        if wants_id:
            row = cur.fetchone()
            lastrowid = row["id"] if row else None
        return _PGResult(cur, lastrowid)
    def executescript(self, script: str):
        cur = self._conn.cursor()
        cur.execute(script)
        return _PGResult(cur)


@contextmanager
def get_conn():
    url = _database_url()
    if url:
        import psycopg
        conn = psycopg.connect(url, autocommit=False, prepare_threshold=None)
        wrapper = _PGCompat(conn)
        try:
            yield wrapper
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()




def _upper_text(value: Any) -> Any:
    """Normaliza texto operativo a MAYÚSCULAS sin alterar None ni valores no textuales."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().upper()
    return value
def _column_exists(conn, table: str, column: str) -> bool:
    if isinstance(conn, _PGCompat):
        row = conn.execute("SELECT 1 AS ok FROM information_schema.columns WHERE table_schema='public' AND table_name=? AND column_name=?", (table, column)).fetchone()
        return bool(row)
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def _hash_pin(pin: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()
    return f"{salt}${digest}"


def verify_pin(pin: str, stored: str) -> bool:
    try:
        salt, expected = stored.split("$", 1)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt), 120_000).hex()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def init_db() -> None:
    global _WEB_INIT_DONE
    # En web/Supabase la estructura se crea una sola vez desde SQL Editor.
    # Streamlit reejecuta app.py con cada clic: no repetimos este sembrado remoto.
    if _database_url() and _WEB_INIT_DONE:
        return
    # Aquí sólo validamos/sembramos parámetros y usuarios base; local conserva SQLite.
    if _database_url():
        with get_conn() as conn:
            defaults = {
                "yellow_inactivity_days":"15","red_inactivity_days":"30","yellow_deadline_pct":"70",
                "red_deadline_pct":"90","yellow_progress_days":"45","progress_interval_days":"60",
                "standard_objective_days":"180","complex_objective_days":"365","preliminary_business_days":"5",
                "first_request_business_days":"10","final_report_business_days":"10","active_cases_target":"5",
                "password_expiry_days":"90","inactive_user_alert_days":"90"}
            for key,value in defaults.items():
                conn.execute("INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO NOTHING", (key,value))
            bad_carlos = "00112233445566778899aabbccddeeff$4e94476e7793ccf66fddcbc373716c3559e5c1ea0126ca6d916378efe3a4dc80"
            bad_adm = "ffeeddccbbaa99887766554433221100$7961ef49749fb16498e308f2b64bd3f96c3c600522809d2be899057be3ad0bdf"
            for username,display,role,jur,agent,bad in [("CARLOS","CARLOS FREYBERGUER","USUARIO","RIO GRANDE",1,bad_carlos),("ADM","PATÁN","ADMIN","SISTEMA",0,bad_adm)]:
                row=conn.execute("SELECT id,pin_hash FROM users WHERE UPPER(username)=?",(username,)).fetchone()
                if not row:
                    conn.execute("INSERT INTO users(username,display_name,pin_hash,role,active,jurisdiction,is_agent,must_change_password,password_changed_at) VALUES (?,?,?,?,1,?,?,1,CURRENT_TIMESTAMP)",(username,display,_hash_pin("1234"),role,jur,agent))
                elif row.get("pin_hash") == bad:
                    conn.execute("UPDATE users SET pin_hash=? WHERE id=?",(_hash_pin("1234"),row["id"]))
            for name in ["REQUERIMIENTO","CÉDULA INTIMACIÓN","NOTA ELECTRÓNICA","ACTA","INFORME DE AVANCE","RESPUESTA DEL CONTRIBUYENTE","CIRCULARIZACIÓN","OTRA ACTUACIÓN"]:
                conn.execute("INSERT INTO activity_types(name,active,is_custom) VALUES (?,1,0) ON CONFLICT(name) DO NOTHING",(name,))
        _WEB_INIT_DONE = True
        return
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT NOT NULL,
                pin_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'USUARIO',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_number TEXT NOT NULL UNIQUE,
                case_type TEXT NOT NULL DEFAULT 'TRABAJO',
                title TEXT,
                cuit TEXT,
                taxpayer_name TEXT,
                tax_id TEXT,
                tax_kind TEXT,
                periods TEXT,
                task TEXT,
                procedure TEXT,
                responsible TEXT,
                responsible_user_id INTEGER,
                supervisor TEXT,
                division TEXT,
                department TEXT,
                date_received TEXT,
                date_assigned TEXT,
                date_registered TEXT,
                date_preliminary TEXT,
                date_first_request TEXT,
                complexity TEXT NOT NULL DEFAULT 'ESTANDAR',
                memo_applies INTEGER NOT NULL DEFAULT 1,
                status_stage TEXT NOT NULL DEFAULT 'EN CURSO',
                amount_determined REAL NOT NULL DEFAULT 0,
                amount_confirmed REAL NOT NULL DEFAULT 0,
                notes TEXT,
                is_closed INTEGER NOT NULL DEFAULT 0,
                closed_at TEXT,
                closed_reason TEXT,
                closed_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(responsible_user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(closed_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                movement_date TEXT NOT NULL,
                movement_type TEXT NOT NULL,
                description TEXT,
                useful_activity INTEGER NOT NULL DEFAULT 1,
                is_progress_report INTEGER NOT NULL DEFAULT 0,
                document_path TEXT,
                document_name TEXT,
                extraction_confidence REAL,
                extracted_case_number TEXT,
                extracted_cuit TEXT,
                raw_excerpt TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_date TEXT NOT NULL,
                meeting_type TEXT NOT NULL,
                case_id INTEGER,
                issue TEXT,
                decision TEXT,
                commitment TEXT,
                owner TEXT,
                due_date TEXT,
                status TEXT NOT NULL DEFAULT 'PENDIENTE',
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS activity_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                active INTEGER NOT NULL DEFAULT 1,
                is_custom INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS case_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                due_date TEXT,
                priority TEXT NOT NULL DEFAULT 'MEDIA',
                status TEXT NOT NULL DEFAULT 'PENDIENTE',
                owner_user_id INTEGER,
                notes TEXT,
                completed_at TEXT,
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
                FOREIGN KEY(owner_user_id) REFERENCES users(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER,
                field_name TEXT,
                old_value TEXT,
                new_value TEXT,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS login_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                user_id INTEGER,
                success INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            """
        )

        # Migraciones para bases PATÁN v1/v2 existentes.
        for col, ddl in [
            ("responsible_user_id", "ALTER TABLE cases ADD COLUMN responsible_user_id INTEGER"),
            ("is_closed", "ALTER TABLE cases ADD COLUMN is_closed INTEGER NOT NULL DEFAULT 0"),
            ("closed_at", "ALTER TABLE cases ADD COLUMN closed_at TEXT"),
            ("closed_reason", "ALTER TABLE cases ADD COLUMN closed_reason TEXT"),
            ("closed_by_user_id", "ALTER TABLE cases ADD COLUMN closed_by_user_id INTEGER"),
        ]:
            if not _column_exists(conn, "cases", col):
                conn.execute(ddl)

        for col, ddl in [
            ("session_version", "ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 1"),
            ("supervisor_user_id", "ALTER TABLE users ADD COLUMN supervisor_user_id INTEGER"),
        ]:
            if not _column_exists(conn, "users", col):
                conn.execute(ddl)

        for col, ddl in [
            ("closure_result", "ALTER TABLE cases ADD COLUMN closure_result TEXT"),
            ("closure_notes", "ALTER TABLE cases ADD COLUMN closure_notes TEXT"),
            ("documentary_complete", "ALTER TABLE cases ADD COLUMN documentary_complete INTEGER NOT NULL DEFAULT 0"),
            ("archived_at", "ALTER TABLE cases ADD COLUMN archived_at TEXT"),
        ]:
            if not _column_exists(conn, "cases", col):
                conn.execute(ddl)

        for col, ddl in [
            ("task_type", "ALTER TABLE case_tasks ADD COLUMN task_type TEXT"),
            ("reference_number", "ALTER TABLE case_tasks ADD COLUMN reference_number TEXT"),
            ("recipient", "ALTER TABLE case_tasks ADD COLUMN recipient TEXT"),
            ("sent_date", "ALTER TABLE case_tasks ADD COLUMN sent_date TEXT"),
            ("notification_date", "ALTER TABLE case_tasks ADD COLUMN notification_date TEXT"),
            ("term_days", "ALTER TABLE case_tasks ADD COLUMN term_days INTEGER"),
            ("response_date", "ALTER TABLE case_tasks ADD COLUMN response_date TEXT"),
            ("extension_requested_date", "ALTER TABLE case_tasks ADD COLUMN extension_requested_date TEXT"),
            ("extension_granted_date", "ALTER TABLE case_tasks ADD COLUMN extension_granted_date TEXT"),
            ("extension_days", "ALTER TABLE case_tasks ADD COLUMN extension_days INTEGER"),
            ("extension_due_date", "ALTER TABLE case_tasks ADD COLUMN extension_due_date TEXT"),
        ]:
            if not _column_exists(conn, "case_tasks", col):
                conn.execute(ddl)

        # PATÁN v12: roles simplificados, seguridad, jurisdicción, firma, comunicación interna y escritura en mayúsculas.
        for col, ddl in [
            ("jurisdiction", "ALTER TABLE users ADD COLUMN jurisdiction TEXT NOT NULL DEFAULT 'RIO GRANDE'"),
            ("is_agent", "ALTER TABLE users ADD COLUMN is_agent INTEGER NOT NULL DEFAULT 1"),
            ("must_change_password", "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"),
            ("password_changed_at", "ALTER TABLE users ADD COLUMN password_changed_at TEXT"),
            ("last_login_at", "ALTER TABLE users ADD COLUMN last_login_at TEXT"),
        ]:
            if not _column_exists(conn, "users", col):
                conn.execute(ddl)

        for col, ddl in [
            ("jurisdiction", "ALTER TABLE cases ADD COLUMN jurisdiction TEXT"),
            ("record_status", "ALTER TABLE cases ADD COLUMN record_status TEXT NOT NULL DEFAULT 'BORRADOR'"),
            ("signed_at", "ALTER TABLE cases ADD COLUMN signed_at TEXT"),
            ("signed_by_user_id", "ALTER TABLE cases ADD COLUMN signed_by_user_id INTEGER"),
        ]:
            if not _column_exists(conn, "cases", col):
                conn.execute(ddl)

        for col, ddl in [
            ("jurisdiction", "ALTER TABLE case_tasks ADD COLUMN jurisdiction TEXT"),
            ("record_status", "ALTER TABLE case_tasks ADD COLUMN record_status TEXT NOT NULL DEFAULT 'BORRADOR'"),
            ("signed_at", "ALTER TABLE case_tasks ADD COLUMN signed_at TEXT"),
            ("signed_by_user_id", "ALTER TABLE case_tasks ADD COLUMN signed_by_user_id INTEGER"),
        ]:
            if not _column_exists(conn, "case_tasks", col):
                conn.execute(ddl)

        for col, ddl in [
            ("record_status", "ALTER TABLE movements ADD COLUMN record_status TEXT NOT NULL DEFAULT 'BORRADOR'"),
            ("signed_at", "ALTER TABLE movements ADD COLUMN signed_at TEXT"),
            ("signed_by_user_id", "ALTER TABLE movements ADD COLUMN signed_by_user_id INTEGER"),
        ]:
            if not _column_exists(conn, "movements", col):
                conn.execute(ddl)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rectifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                user_id INTEGER,
                reason TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'NUEVA',
                admin_note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                created_by_user_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                active INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(created_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS news_reads (
                news_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(news_id,user_id),
                FOREIGN KEY(news_id) REFERENCES news(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)

        defaults = {
            "yellow_inactivity_days": "15",
            "red_inactivity_days": "30",
            "yellow_deadline_pct": "70",
            "red_deadline_pct": "90",
            "yellow_progress_days": "45",
            "progress_interval_days": "60",
            "standard_objective_days": "180",
            "complex_objective_days": "365",
            "preliminary_business_days": "5",
            "first_request_business_days": "10",
            "final_report_business_days": "10",
            "active_cases_target": "5",
            "password_expiry_days": "90",
            "inactive_user_alert_days": "90",
        }
        for key, value in defaults.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES (?,?)", (key, value))

        # PATÁN v12: cuenta técnica separada del agente Carlos.
        carlos = conn.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE", ("carlos",)).fetchone()
        if not carlos:
            conn.execute(
                "INSERT INTO users(username,display_name,pin_hash,role,active,jurisdiction,is_agent,must_change_password,password_changed_at) VALUES (?,?,?,?,1,?,?,?,CURRENT_TIMESTAMP)",
                ("CARLOS", "CARLOS FREYBERGUER", _hash_pin("1234"), "USUARIO", "RIO GRANDE", 1, 1),
            )
        else:
            conn.execute("UPDATE users SET display_name='CARLOS FREYBERGUER', role='USUARIO', is_agent=1 WHERE id=?", (carlos["id"],))

        adm = conn.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE", ("ADM",)).fetchone()
        if not adm:
            conn.execute(
                "INSERT INTO users(username,display_name,pin_hash,role,active,jurisdiction,is_agent,must_change_password,password_changed_at) VALUES (?,?,?,?,1,?,?,?,CURRENT_TIMESTAMP)",
                ("ADM", "PATÁN", _hash_pin("1234"), "ADMIN", "SISTEMA", 0, 1),
            )
        else:
            conn.execute("UPDATE users SET display_name='PATÁN', role='ADMIN', is_agent=0, jurisdiction='SISTEMA' WHERE id=?", (adm["id"],))

        # Roles v12: sólo USUARIO, SUPERVISOR y ADMIN.
        conn.execute("UPDATE users SET role='USUARIO' WHERE role IN ('AGENTE','LECTURA')")

        # Tipos de actividad manuales. Se pueden ampliar desde la propia app.
        for name in ["Requerimiento", "Cédula Intimación", "Nota electrónica", "Acta", "Informe de avance", "Respuesta del contribuyente", "Circularización", "Otra actuación"]:
            conn.execute("INSERT OR IGNORE INTO activity_types(name,active,is_custom) VALUES (?,?,0)", (name, 1))

        # V1-PRUEBA: base operativa deliberadamente vacía.
        # No se cargan trabajos/casos de demostración al iniciar.
        count = conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"]

        conn.execute("UPDATE cases SET memo_applies=1")

        carlos_row = conn.execute("SELECT id,jurisdiction FROM users WHERE username=? COLLATE NOCASE", ("carlos",)).fetchone()
        if carlos_row:
            conn.execute(
                "UPDATE cases SET responsible_user_id=?, responsible='CARLOS FREYBERGUER' WHERE responsible_user_id IS NULL",
                (carlos_row["id"],),
            )
            conn.execute("UPDATE cases SET jurisdiction=COALESCE(NULLIF(jurisdiction,''),?) WHERE responsible_user_id=?", (carlos_row["jurisdiction"], carlos_row["id"]))
        conn.execute("UPDATE case_tasks SET jurisdiction=(SELECT jurisdiction FROM cases c WHERE c.id=case_tasks.case_id) WHERE jurisdiction IS NULL OR jurisdiction='' ")

        # PATÁN V12: uniformidad visual y de datos. Todo texto operativo queda en MAYÚSCULAS.
        # Las claves/PIN no se modifican y conservan mayúsculas/minúsculas como fueron definidas.
        conn.execute("UPDATE users SET username=UPPER(username), display_name=UPPER(display_name), jurisdiction=UPPER(jurisdiction)")
        for table, cols in {
            'cases':['case_number','case_type','title','cuit','taxpayer_name','tax_id','tax_kind','periods','task','procedure','responsible','supervisor','division','department','complexity','status_stage','notes','jurisdiction','record_status'],
            'movements':['movement_type','description','document_name','extracted_case_number','extracted_cuit','raw_excerpt','record_status'],
            'case_tasks':['title','priority','status','notes','task_type','reference_number','recipient','jurisdiction','record_status'],
            'meetings':['meeting_type','issue','decision','commitment','owner','status','notes'],
            'suggestions':['message','status','admin_note'],
            'news':['title','message'],
            'activity_types':['name'],
        }.items():
            for col in cols:
                if _column_exists(conn, table, col):
                    conn.execute(f"UPDATE {table} SET {col}=UPPER({col}) WHERE {col} IS NOT NULL")


def seed_cases(conn: sqlite3.Connection) -> None:
    rows = [
        {
            "case_number": "N-1547-2026",
            "case_type": "Nota electrónica",
            "title": "GENUS - GESTIÓN ADMINISTRATIVA",
            "task": "Revisión, Tratamiento y/o Autorización",
            "procedure": "Genus",
            "date_received": "2026-08-27",
            "complexity": "ESTANDAR",
            "memo_applies": 1,
        },
        {
            "case_number": "ET-39-2026",
            "case_type": "TRABAJO",
            "title": "LEANVAL SA - ANÁLISIS GENERAL",
            "taxpayer_name": "LEANVAL SA",
            "cuit": "30-59947912-7",
            "task": "Revisión, Tratamiento y/o Autorización",
            "procedure": "TRABAJO",
            "date_received": "2026-04-28",
            "date_assigned": "2026-04-28",
            "date_registered": "2026-04-28",
            "complexity": "ESTANDAR",
            "memo_applies": 1,
        },
        {
            "case_number": "ET-177-2025",
            "case_type": "TRABAJO",
            "title": "AVICOLA BRANDEN S.A. s/alta de oficio",
            "taxpayer_name": "AVICOLA BRANDEN S.A.",
            "task": "Revisión, Tratamiento y/o Autorización",
            "procedure": "TRABAJO",
            "date_received": "2026-08-03",
            "date_assigned": "2026-08-03",
            "date_registered": "2026-08-03",
            "complexity": "ESTANDAR",
            "memo_applies": 1,
        },
        {
            "case_number": "ET-175-2025",
            "case_type": "TRABAJO",
            "title": "CASELLA NICOLAS VICENTE - ANÁLISIS GENERAL",
            "taxpayer_name": "CASELLA NICOLAS VICENTE",
            "task": "Revisión, Tratamiento y/o Autorización",
            "procedure": "TRABAJO",
            "date_received": "2026-09-02",
            "date_assigned": "2026-09-02",
            "date_registered": "2026-09-02",
            "complexity": "COMPLEJA",
            "memo_applies": 1,
        },
        {
            "case_number": "ET-174-2025",
            "case_type": "TRABAJO",
            "title": "ROMARION CLAUDIO ALFREDO - ANÁLISIS GENERAL",
            "taxpayer_name": "ROMARION CLAUDIO ALFREDO",
            "task": "Revisión, Tratamiento y/o Autorización",
            "procedure": "TRABAJO",
            "date_received": "2026-04-28",
            "date_assigned": "2026-04-28",
            "date_registered": "2026-04-28",
            "complexity": "COMPLEJA",
            "memo_applies": 1,
        },
    ]
    for r in rows:
        cols = ",".join(r.keys())
        qs = ",".join(["?"] * len(r))
        conn.execute(f"INSERT INTO cases({cols}) VALUES ({qs})", tuple(r.values()))


def _recent_failed_attempts(conn: sqlite3.Connection, username: str, minutes: int = 15) -> int:
    cutoff = (datetime.now() - timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM login_log WHERE username=? COLLATE NOCASE AND success=0 AND created_at>=?",
        (username.strip(), cutoff),
    ).fetchone()
    return int(row["n"] or 0)


def authenticate(username: str, pin: str) -> dict[str, Any] | None:
    username = username.strip()
    if not username or not pin:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1",
            (username,),
        ).fetchone()
        if _recent_failed_attempts(conn, username) >= 5:
            conn.execute("INSERT INTO login_log(username,user_id,success) VALUES (?,?,0)", (username, row["id"] if row else None))
            return None
        ok = bool(row and verify_pin(pin, row["pin_hash"]))
        conn.execute("INSERT INTO login_log(username,user_id,success) VALUES (?,?,?)", (username, row["id"] if row else None, int(ok)))
        previous_last_login = row["last_login_at"] if ok and row and "last_login_at" in row.keys() else None
        if ok and row:
            conn.execute("UPDATE users SET last_login_at=CURRENT_TIMESTAMP WHERE id=?", (row["id"],))
            row = conn.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
    if ok and row:
        user = dict(row)
        user.pop("pin_hash", None)
        user["_previous_last_login_at"] = previous_last_login
        return user
    return None

def list_users(active_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT id,username,display_name,role,active,session_version,supervisor_user_id,jurisdiction,is_agent,must_change_password,password_changed_at,last_login_at,created_at,updated_at FROM users"
    params: tuple[Any, ...] = ()
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY CASE WHEN role='ADMIN' THEN 0 ELSE 1 END, display_name COLLATE NOCASE"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def create_user(username: str, display_name: str, pin: str = "1234", role: str = "USUARIO", jurisdiction: str = "RIO GRANDE", is_agent: int = 1) -> int:
    username = _upper_text(username)
    display_name = _upper_text(display_name)
    pin = pin or "1234"
    if not username or not display_name:
        raise ValueError("Usuario y nombre son obligatorios.")
    if not 4 <= len(pin) <= 20:
        raise ValueError("La clave debe tener entre 4 y 20 caracteres.")
    role = role if role in ("ADMIN", "USUARIO", "SUPERVISOR") else "USUARIO"
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users(username,display_name,pin_hash,role,active,jurisdiction,is_agent,must_change_password,password_changed_at) VALUES (?,?,?,?,1,?,?,1,CURRENT_TIMESTAMP)",
            (username, display_name, _hash_pin(pin), role, _upper_text(jurisdiction) or "RIO GRANDE", int(is_agent)),
        )
        return int(cur.lastrowid)


def update_user(
    user_id: int, *, username: str | None = None, display_name: str | None = None,
    pin: str | None = None, active: int | None = None, role: str | None = None,
    jurisdiction: str | None = None, is_agent: int | None = None, must_change_password: int | None = None
) -> None:
    sets: list[str] = []
    vals: list[Any] = []
    if username is not None:
        username = _upper_text(username)
        if not username: raise ValueError("El usuario no puede quedar vacío.")
        sets.append("username=?"); vals.append(username)
    if display_name is not None:
        display_name = _upper_text(display_name)
        if not display_name: raise ValueError("El nombre no puede quedar vacío.")
        sets.append("display_name=?"); vals.append(display_name)
    if pin:
        if not 4 <= len(pin) <= 20: raise ValueError("La clave debe tener entre 4 y 20 caracteres.")
        sets += ["pin_hash=?", "password_changed_at=CURRENT_TIMESTAMP", "must_change_password=0"]
        vals.append(_hash_pin(pin))
    if active is not None: sets.append("active=?"); vals.append(int(active))
    if role is not None: sets.append("role=?"); vals.append(role if role in ("ADMIN","USUARIO","SUPERVISOR") else "USUARIO")
    if jurisdiction is not None: sets.append("jurisdiction=?"); vals.append(_upper_text(jurisdiction) or "RIO GRANDE")
    if is_agent is not None: sets.append("is_agent=?"); vals.append(int(is_agent))
    if must_change_password is not None: sets.append("must_change_password=?"); vals.append(int(must_change_password))
    if not sets: return
    vals.append(user_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {','.join(sets)}, updated_at=CURRENT_TIMESTAMP WHERE id=?", vals)


def change_password(user_id: int, current_pin: str, new_pin: str) -> None:
    if not 4 <= len(new_pin) <= 20:
        raise ValueError("La nueva clave debe tener entre 4 y 20 caracteres.")
    with get_conn() as conn:
        row=conn.execute("SELECT pin_hash FROM users WHERE id=?",(user_id,)).fetchone()
        if not row or not verify_pin(current_pin,row["pin_hash"]):
            raise ValueError("La clave actual no es correcta.")
        conn.execute("UPDATE users SET pin_hash=?,password_changed_at=CURRENT_TIMESTAMP,must_change_password=0,updated_at=CURRENT_TIMESTAMP WHERE id=?",(_hash_pin(new_pin),user_id))


def delete_user(user_id: int) -> None:
    """Elimina el acceso. Los casos quedan conservados y pasan a 'Sin asignar'."""
    with get_conn() as conn:
        conn.execute("UPDATE cases SET responsible_user_id=NULL, responsible='' WHERE responsible_user_id=?", (user_id,))
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


def list_activity_types(active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT id,name,active,is_custom,created_at FROM activity_types"
    if active_only:
        sql += " WHERE active=1"
    sql += " ORDER BY is_custom, name COLLATE NOCASE"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def add_activity_type(name: str) -> int:
    _ACTIVITY_TYPES_CACHE.clear()
    name = _upper_text(name)
    if not name:
        raise ValueError("Ingresá un nombre para la actividad.")
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM activity_types WHERE name=? COLLATE NOCASE", (name,)).fetchone()
        if existing:
            conn.execute("UPDATE activity_types SET active=1 WHERE id=?", (existing["id"],))
            return int(existing["id"])
        cur = conn.execute("INSERT INTO activity_types(name,active,is_custom) VALUES (?,1,1)", (name,))
        return int(cur.lastrowid)


def fetch_settings() -> dict[str, Any]:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_AT
    now = time.monotonic()
    if _database_url() and _SETTINGS_CACHE is not None and now - _SETTINGS_CACHE_AT < 30:
        return dict(_SETTINGS_CACHE)
    with get_conn() as conn:
        rows = conn.execute("SELECT key,value FROM settings").fetchall()
    out: dict[str, Any] = {}
    for row in rows:
        value = row["value"]
        try:
            out[row["key"]] = float(value) if "." in value else int(value)
        except ValueError:
            out[row["key"]] = value
    if _database_url():
        _SETTINGS_CACHE = dict(out)
        _SETTINGS_CACHE_AT = now
    return out


def save_settings(values: dict[str, Any]) -> None:
    global _SETTINGS_CACHE, _SETTINGS_CACHE_AT
    _SETTINGS_CACHE = None
    _SETTINGS_CACHE_AT = 0.0
    with get_conn() as conn:
        for key, value in values.items():
            conn.execute(
                "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )


def list_cases(user_id: int | None = None, include_closed: bool = False) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if user_id is not None:
        where.append("c.responsible_user_id=?")
        params.append(user_id)
    if not include_closed:
        where.append("COALESCE(c.is_closed,0)=0")
    sql = """
        SELECT c.*, u.display_name AS responsible_display,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.useful_activity=1) AS last_movement,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.is_progress_report=1) AS last_progress_report
        FROM cases c
        LEFT JOIN users u ON u.id=c.responsible_user_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY COALESCE(c.date_received,c.created_at) DESC, c.id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_closed_cases(user_id: int | None = None) -> list[dict[str, Any]]:
    where = ["COALESCE(c.is_closed,0)=1"]
    params: list[Any] = []
    if user_id is not None:
        where.append("c.responsible_user_id=?")
        params.append(user_id)
    sql = """
        SELECT c.*, u.display_name AS responsible_display, closer.display_name AS closed_by_display,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.useful_activity=1) AS last_movement,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.is_progress_report=1) AS last_progress_report
        FROM cases c
        LEFT JOIN users u ON u.id=c.responsible_user_id
        LEFT JOIN users closer ON closer.id=c.closed_by_user_id
        WHERE """ + " AND ".join(where) + " ORDER BY COALESCE(c.closed_at,c.updated_at) DESC, c.id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_case(case_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT c.*,u.display_name AS responsible_display FROM cases c LEFT JOIN users u ON u.id=c.responsible_user_id WHERE c.id=?",
            (case_id,),
        ).fetchone()
    return dict(row) if row else None


def upsert_case(data: dict[str, Any], case_id: int | None = None) -> int:
    allowed = {
        "case_number", "case_type", "title", "cuit", "taxpayer_name", "tax_id", "tax_kind", "periods",
        "task", "procedure", "responsible", "responsible_user_id", "supervisor", "division", "department", "date_received",
        "date_assigned", "date_registered", "date_preliminary", "date_first_request", "complexity",
        "memo_applies", "status_stage", "amount_determined", "amount_confirmed", "notes", "jurisdiction", "record_status"
    }
    clean = {k: v for k, v in data.items() if k in allowed}
    upper_fields = {
        "case_number","case_type","title","cuit","taxpayer_name","tax_id","tax_kind","periods",
        "task","procedure","responsible","supervisor","division","department","complexity",
        "status_stage","notes","jurisdiction","record_status"
    }
    clean = {k: (_upper_text(v) if k in upper_fields else v) for k, v in clean.items()}
    with get_conn() as conn:
        if case_id:
            sets = ",".join([f"{k}=?" for k in clean])
            conn.execute(f"UPDATE cases SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?", (*clean.values(), case_id))
            return case_id
        cols = ",".join(clean.keys())
        qs = ",".join(["?"] * len(clean))
        cur = conn.execute(f"INSERT INTO cases({cols}) VALUES ({qs})", tuple(clean.values()))
        return int(cur.lastrowid)


def close_case(case_id: int, user_id: int, reason: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE cases SET is_closed=1,status_stage='CERRADO',closed_at=CURRENT_TIMESTAMP,
               closed_reason=?,closed_by_user_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (_upper_text(reason), user_id, case_id),
        )


def reopen_case(case_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE cases SET is_closed=0,status_stage='EN CURSO',closed_at=NULL,closed_reason=NULL,
               closed_by_user_id=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (case_id,),
        )


def delete_case(case_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM movements WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM cases WHERE id=?", (case_id,))


def add_movement(data: dict[str, Any]) -> int:
    upper_fields={"movement_type","description","document_name","extracted_case_number","extracted_cuit","raw_excerpt","record_status"}
    data={k: (_upper_text(v) if k in upper_fields else v) for k,v in data.items()}
    cols = ",".join(data.keys())
    qs = ",".join(["?"] * len(data))
    with get_conn() as conn:
        cur = conn.execute(f"INSERT INTO movements({cols}) VALUES ({qs})", tuple(data.values()))
        return int(cur.lastrowid)


def list_movements(case_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM movements WHERE case_id=? ORDER BY movement_date DESC, id DESC", (case_id,)).fetchall()
    return [dict(r) for r in rows]


def add_meeting(data: dict[str, Any]) -> int:
    upper_fields={"meeting_type","issue","decision","commitment","owner","status","notes"}
    data={k: (_upper_text(v) if k in upper_fields else v) for k,v in data.items()}
    cols = ",".join(data.keys())
    qs = ",".join(["?"] * len(data))
    with get_conn() as conn:
        cur = conn.execute(f"INSERT INTO meetings({cols}) VALUES ({qs})", tuple(data.values()))
        return int(cur.lastrowid)


def list_meetings(case_ids: list[int] | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT mt.*, c.case_number
        FROM meetings mt
        LEFT JOIN cases c ON c.id=mt.case_id
    """
    params: list[Any] = []
    if case_ids is not None:
        if not case_ids:
            return []
        marks = ",".join(["?"] * len(case_ids))
        sql += f" WHERE mt.case_id IS NULL OR mt.case_id IN ({marks})"
        params.extend(case_ids)
    sql += " ORDER BY mt.meeting_date DESC, mt.id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def log_audit(user_id: int | None, action: str, entity_type: str, entity_id: int | None = None, *, field_name: str | None = None, old_value: Any = None, new_value: Any = None, details: str | None = None) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_log(user_id,action,entity_type,entity_id,field_name,old_value,new_value,details) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, action, entity_type, entity_id, field_name, None if old_value is None else str(old_value), None if new_value is None else str(new_value), details),
        )


def list_audit(limit: int = 500) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT a.*,u.display_name AS user_name FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def list_login_log(limit: int = 300) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT l.*,u.display_name AS user_name FROM login_log l LEFT JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT ?""",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def force_logout_user(user_id: int, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET session_version=COALESCE(session_version,1)+1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (user_id,))
    log_audit(actor_user_id, "FORCE_LOGOUT", "user", user_id)


def get_user(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        r=conn.execute("SELECT id,username,display_name,role,active,session_version,supervisor_user_id,jurisdiction,is_agent,must_change_password,password_changed_at,last_login_at,created_at,updated_at FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(r) if r else None


def visible_user_ids(user: dict[str, Any]) -> list[int] | None:
    role=(user.get("role") or "USUARIO").upper()
    uid=int(user["id"])
    if role=="ADMIN": return None
    if role=="SUPERVISOR":
        with get_conn() as conn:
            rows=conn.execute("SELECT id FROM users WHERE active=1 AND (id=? OR supervisor_user_id=?)",(uid,uid)).fetchall()
        return [int(r["id"]) for r in rows]
    return [uid]


def count_active_cases_for_user(user_id: int) -> int:
    with get_conn() as conn:
        r=conn.execute("SELECT COUNT(*) AS n FROM cases WHERE responsible_user_id=? AND COALESCE(is_closed,0)=0 AND status_stage!='SUSPENDIDO'", (user_id,)).fetchone()
    return int(r["n"] or 0)


def set_user_supervisor(user_id: int, supervisor_user_id: int | None, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET supervisor_user_id=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (supervisor_user_id,user_id))
    log_audit(actor_user_id,"UPDATE","user",user_id,field_name="supervisor_user_id",new_value=supervisor_user_id)


def add_task(case_id: int, title: str, due_date: str | None, priority: str, owner_user_id: int | None, notes: str, created_by_user_id: int | None, *, task_type: str | None = None, reference_number: str | None = None, recipient: str | None = None, sent_date: str | None = None, notification_date: str | None = None, term_days: int | None = None, jurisdiction: str | None = None, record_status: str = "BORRADOR") -> int:
    if not title.strip():
        raise ValueError("La tarea no puede quedar vacía.")
    with get_conn() as conn:
        cur=conn.execute("""INSERT INTO case_tasks(case_id,title,due_date,priority,status,owner_user_id,notes,created_by_user_id,task_type,reference_number,recipient,sent_date,notification_date,term_days,jurisdiction,record_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (case_id,_upper_text(title),due_date,_upper_text(priority),"PENDIENTE",owner_user_id,_upper_text(notes),created_by_user_id,_upper_text(task_type),_upper_text(reference_number),_upper_text(recipient),sent_date,notification_date,term_days,_upper_text(jurisdiction),_upper_text(record_status)))
        tid=int(cur.lastrowid)
    log_audit(created_by_user_id,"CREATE","task",tid,details=f"case_id={case_id}; {title}; destinatario={recipient or ''}; vence={due_date or ''}")
    return tid


def grant_task_extension(task_id: int, requested_date: str | None, granted_date: str, extension_days: int, extension_due_date: str, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute("""UPDATE case_tasks SET extension_requested_date=?,extension_granted_date=?,extension_days=?,extension_due_date=?,due_date=?,status='PENDIENTE',updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                     (requested_date,granted_date,int(extension_days),extension_due_date,extension_due_date,task_id))
    log_audit(actor_user_id,"EXTENSION","task",task_id,details=f"prorroga={extension_days} dias; nuevo_vto={extension_due_date}")


def complete_task(task_id: int, response_date: str, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE case_tasks SET status='CUMPLIDA',response_date=?,completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=?",(response_date,task_id))
    log_audit(actor_user_id,"COMPLETE","task",task_id,details=f"respuesta={response_date}")

def list_tasks(case_ids: list[int] | None = None, include_done: bool = True) -> list[dict[str, Any]]:
    sql="""SELECT t.*,c.case_number,u.display_name AS owner_name FROM case_tasks t JOIN cases c ON c.id=t.case_id LEFT JOIN users u ON u.id=t.owner_user_id"""
    params=[]
    where=[]
    if case_ids is not None:
        if not case_ids: return []
        marks=','.join(['?']*len(case_ids)); where.append(f"t.case_id IN ({marks})"); params.extend(case_ids)
    if not include_done: where.append("t.status!='CUMPLIDA'")
    if where: sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY CASE t.status WHEN 'VENCIDA' THEN 0 WHEN 'PENDIENTE' THEN 1 ELSE 2 END, COALESCE(t.due_date,'9999-12-31'), t.id DESC"
    with get_conn() as conn:
        rows=conn.execute(sql,params).fetchall()
    return [dict(r) for r in rows]


def update_task_status(task_id: int, status: str, actor_user_id: int | None = None) -> None:
    status=status if status in ('PENDIENTE','CUMPLIDA','CANCELADA') else 'PENDIENTE'
    with get_conn() as conn:
        conn.execute("UPDATE case_tasks SET status=?, completed_at=CASE WHEN ?='CUMPLIDA' THEN CURRENT_TIMESTAMP ELSE NULL END, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status,status,task_id))
    log_audit(actor_user_id,"UPDATE","task",task_id,field_name="status",new_value=status)


def refresh_overdue_tasks() -> None:
    global _LAST_OVERDUE_REFRESH
    now = time.monotonic()
    if _database_url() and _LAST_OVERDUE_REFRESH and now - _LAST_OVERDUE_REFRESH < 60:
        return
    today=datetime.now().strftime('%Y-%m-%d')
    with get_conn() as conn:
        conn.execute("UPDATE case_tasks SET status='VENCIDA', updated_at=CURRENT_TIMESTAMP WHERE status='PENDIENTE' AND due_date IS NOT NULL AND due_date < ?", (today,))
        conn.execute("UPDATE case_tasks SET status='PENDIENTE', updated_at=CURRENT_TIMESTAMP WHERE status='VENCIDA' AND (due_date IS NULL OR due_date >= ?)", (today,))
    if _database_url():
        _LAST_OVERDUE_REFRESH = now


def suspend_case(case_id: int, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE cases SET status_stage='SUSPENDIDO', updated_at=CURRENT_TIMESTAMP WHERE id=? AND COALESCE(is_closed,0)=0", (case_id,))
    log_audit(actor_user_id,"SUSPEND","case",case_id)


def resume_case(case_id: int, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE cases SET status_stage='EN CURSO', updated_at=CURRENT_TIMESTAMP WHERE id=? AND COALESCE(is_closed,0)=0", (case_id,))
    log_audit(actor_user_id,"RESUME","case",case_id)


def archive_case(case_id: int, actor_user_id: int | None = None) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE cases SET status_stage='ARCHIVADO', archived_at=CURRENT_TIMESTAMP, is_closed=1, updated_at=CURRENT_TIMESTAMP WHERE id=?", (case_id,))
    log_audit(actor_user_id,"ARCHIVE","case",case_id)


def close_case_checked(case_id: int, user_id: int, reason: str, result: str, notes: str, documentary_complete: bool) -> None:
    if not result.strip():
        raise ValueError("Indicá el resultado final.")
    if not documentary_complete:
        raise ValueError("Debés confirmar que el estado documental está completo.")
    with get_conn() as conn:
        conn.execute("""UPDATE cases SET is_closed=1,status_stage='CERRADO',closed_at=CURRENT_TIMESTAMP,closed_reason=?,closure_result=?,closure_notes=?,documentary_complete=1,closed_by_user_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                     (reason.strip(),result.strip(),notes.strip(),user_id,case_id))
    log_audit(user_id,"CLOSE","case",case_id,details=result.strip())


def backup_database() -> str | None:
    if _database_url():
        return None
    if not DB_PATH.exists():
        return None
    bdir=BASE_DIR/'data'/'backups'; bdir.mkdir(parents=True,exist_ok=True)
    dest=bdir/f"patan_{datetime.now().strftime('%Y%m%d')}.db"
    if dest.exists(): return str(dest)
    src=sqlite3.connect(DB_PATH)
    dst=sqlite3.connect(dest)
    try: src.backup(dst)
    finally: dst.close(); src.close()
    return str(dest)

def list_cases_for_users(user_ids: list[int] | None, include_closed: bool = False) -> list[dict[str, Any]]:
    if user_ids is None:
        return list_cases(user_id=None, include_closed=include_closed)
    if len(user_ids) == 1:
        return list_cases(user_id=user_ids[0], include_closed=include_closed)
    if not user_ids:
        return []
    marks=','.join(['?']*len(user_ids))
    where=[f"c.responsible_user_id IN ({marks})"]
    params=list(user_ids)
    if not include_closed:
        where.append("COALESCE(c.is_closed,0)=0")
    sql="""
        SELECT c.*, u.display_name AS responsible_display,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.useful_activity=1) AS last_movement,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.is_progress_report=1) AS last_progress_report
        FROM cases c LEFT JOIN users u ON u.id=c.responsible_user_id
        WHERE """ + " AND ".join(where) + " ORDER BY COALESCE(c.date_received,c.created_at) DESC, c.id DESC"
    with get_conn() as conn:
        rows=conn.execute(sql,params).fetchall()
    return [dict(r) for r in rows]


def list_closed_cases_for_users(user_ids: list[int] | None) -> list[dict[str, Any]]:
    if user_ids is None:
        return list_closed_cases(None)
    if len(user_ids)==1:
        return list_closed_cases(user_ids[0])
    if not user_ids: return []
    marks=','.join(['?']*len(user_ids))
    sql=f"""
        SELECT c.*,u.display_name AS responsible_display, closer.display_name AS closed_by_display,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.useful_activity=1) AS last_movement,
               (SELECT MAX(movement_date) FROM movements m WHERE m.case_id=c.id AND m.is_progress_report=1) AS last_progress_report
        FROM cases c LEFT JOIN users u ON u.id=c.responsible_user_id
        LEFT JOIN users closer ON closer.id=c.closed_by_user_id
        WHERE COALESCE(c.is_closed,0)=1 AND c.responsible_user_id IN ({marks})
        ORDER BY COALESCE(c.closed_at,c.updated_at) DESC,c.id DESC
    """
    with get_conn() as conn:
        rows=conn.execute(sql,user_ids).fetchall()
    return [dict(r) for r in rows]


# ---------------- PATÁN v12 ----------------
def password_status(user: dict[str, Any], expiry_days: int = 90, inactive_days: int = 90) -> dict[str, Any]:
    now=datetime.now()
    def p(v):
        if not v: return None
        try: return datetime.fromisoformat(str(v).replace('Z',''))
        except Exception: return None
    changed=p(user.get('password_changed_at')) or p(user.get('created_at'))
    last=p(user.get('last_login_at'))
    age=(now-changed).days if changed else None
    inactive=(now-last).days if last else None
    return {
        'must_change': bool(user.get('must_change_password')),
        'password_age_days': age,
        'password_expired': age is not None and age >= expiry_days,
        'inactive_days': inactive,
        'inactive_alert': inactive is not None and inactive >= inactive_days,
    }

def sign_record(entity_type: str, entity_id: int, user_id: int) -> None:
    table={'case':'cases','task':'case_tasks','movement':'movements'}.get(entity_type)
    if not table: raise ValueError('Entidad no firmable.')
    with get_conn() as conn:
        conn.execute(f"UPDATE {table} SET record_status='FIRMADO',signed_at=CURRENT_TIMESTAMP,signed_by_user_id=? WHERE id=?",(user_id,entity_id))
    log_audit(user_id,'SIGN',entity_type,entity_id,details='Registro firmado')

def rectify_record(entity_type: str, entity_id: int, user_id: int, reason: str, before_json: str = '', after_json: str = '') -> None:
    if not reason.strip(): raise ValueError('Indicá el motivo de la rectificación.')
    with get_conn() as conn:
        conn.execute("INSERT INTO rectifications(entity_type,entity_id,user_id,reason,before_json,after_json) VALUES (?,?,?,?,?,?)",(entity_type,entity_id,user_id,reason.strip(),before_json,after_json))
    log_audit(user_id,'RECTIFY',entity_type,entity_id,details=reason.strip())

def list_rectifications(entity_type: str, entity_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows=conn.execute("SELECT r.*,u.display_name FROM rectifications r LEFT JOIN users u ON u.id=r.user_id WHERE entity_type=? AND entity_id=? ORDER BY r.id DESC",(entity_type,entity_id)).fetchall()
    return [dict(r) for r in rows]

def update_task(task_id: int, data: dict[str, Any], actor_user_id: int, rectification_reason: str | None = None) -> None:
    with get_conn() as conn:
        old=conn.execute("SELECT * FROM case_tasks WHERE id=?",(task_id,)).fetchone()
        if not old: raise ValueError('Tarea inexistente.')
        signed=(old['record_status'] or 'BORRADOR')=='FIRMADO'
        if signed and not (rectification_reason or '').strip(): raise ValueError('La tarea está firmada. Indicá motivo de rectificación.')
        fields=['task_type','reference_number','recipient','sent_date','notification_date','term_days','due_date','notes','priority']
        upper_fields={'task_type','reference_number','recipient','notes','priority'}
        vals=[_upper_text(data.get(f)) if f in upper_fields else data.get(f) for f in fields]
        conn.execute("UPDATE case_tasks SET "+','.join(f"{f}=?" for f in fields)+",updated_at=CURRENT_TIMESTAMP WHERE id=?",vals+[task_id])
        new=conn.execute("SELECT * FROM case_tasks WHERE id=?",(task_id,)).fetchone()
    if signed:
        import json
        rectify_record('task',task_id,actor_user_id,rectification_reason or '',json.dumps(dict(old),ensure_ascii=False,default=str),json.dumps(dict(new),ensure_ascii=False,default=str))
    else:
        log_audit(actor_user_id,'UPDATE','task',task_id,details='Edición de borrador')

def add_suggestion(user_id: int, message: str) -> int:
    msg=_upper_text(' '.join((message or '').split()))
    if not msg: raise ValueError('Escribí una sugerencia.')
    if len(msg)>300: raise ValueError('Máximo 300 caracteres.')
    with get_conn() as conn:
        cur=conn.execute("INSERT INTO suggestions(user_id,message) VALUES (?,?)",(user_id,msg))
        return int(cur.lastrowid)

def list_suggestions() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows=conn.execute("SELECT s.*,u.display_name,u.username FROM suggestions s JOIN users u ON u.id=s.user_id ORDER BY CASE s.status WHEN 'NUEVA' THEN 0 WHEN 'EN EVALUACIÓN' THEN 1 WHEN 'IMPLEMENTADA' THEN 2 ELSE 3 END,s.id DESC").fetchall()
    return [dict(r) for r in rows]

def update_suggestion(suggestion_id: int, status: str, admin_note: str = '') -> None:
    if status not in ('NUEVA','EN EVALUACIÓN','IMPLEMENTADA','DESCARTADA'): status='NUEVA'
    with get_conn() as conn:
        conn.execute("UPDATE suggestions SET status=?,admin_note=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(status,_upper_text(admin_note),suggestion_id))

def unread_suggestion_count() -> int:
    with get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) n FROM suggestions WHERE status='NUEVA'").fetchone()['n'])

def add_news(title: str, message: str, created_by_user_id: int | None) -> int:
    if not (title or '').strip() or not (message or '').strip(): raise ValueError('Título y novedad son obligatorios.')
    with get_conn() as conn:
        cur=conn.execute("INSERT INTO news(title,message,created_by_user_id) VALUES (?,?,?)",(_upper_text(title),_upper_text(message),created_by_user_id))
        return int(cur.lastrowid)

def list_news(user_id: int) -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows=conn.execute("""SELECT n.*,u.display_name AS author,CASE WHEN nr.read_at IS NULL THEN 0 ELSE 1 END AS is_read,nr.read_at
            FROM news n LEFT JOIN users u ON u.id=n.created_by_user_id LEFT JOIN news_reads nr ON nr.news_id=n.id AND nr.user_id=?
            WHERE n.active=1 ORDER BY n.id DESC""",(user_id,)).fetchall()
    return [dict(r) for r in rows]

def unread_news_count(user_id: int) -> int:
    with get_conn() as conn:
        return int(conn.execute("SELECT COUNT(*) n FROM news n LEFT JOIN news_reads nr ON nr.news_id=n.id AND nr.user_id=? WHERE n.active=1 AND nr.read_at IS NULL",(user_id,)).fetchone()['n'])

def mark_news_read(user_id: int, news_id: int | None = None) -> None:
    with get_conn() as conn:
        if news_id is None:
            conn.execute("INSERT OR IGNORE INTO news_reads(news_id,user_id) SELECT id,? FROM news WHERE active=1",(user_id,))
        else:
            conn.execute("INSERT OR IGNORE INTO news_reads(news_id,user_id) VALUES (?,?)",(news_id,user_id))
