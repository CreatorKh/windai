"""Autentifikatsiya va rollar.

Bank tizimida "kim qaror chiqardi" degan savol "qanday qaror chiqdi" dan kam
muhim emas: regulyator audit izida javobgar xodimni ko'rishi kerak. Shu sababli
bu modul ikki vazifani bajaradi:

  1. Kirish (sessiya cookie) va parolni xavfsiz saqlash.
  2. Rol bo'yicha ruxsat — har bir endpoint qaysi lavozimga ochiq.

Parollar `pbkdf2_hmac('sha256', ..., 200_000)` bilan, har bir foydalanuvchiga
alohida sol (salt) qo'shib saqlanadi. Ochiq matnda hech qayerda turmaydi.
Taqqoslash `hmac.compare_digest` bilan — vaqt bo'yicha hujumdan himoya.

Sessiya: `secrets.token_urlsafe(32)` -> HttpOnly cookie. Har bir so'rovda
`last_seen` yangilanadi (sliding expiration), `SESSION_IDLE_MINUTES` davomida
harakat bo'lmasa sessiya o'ladi.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Rollar
# ---------------------------------------------------------------------------
# Kalit -> (o'zbekcha yorliq, lavozim tavsifi, ruxsatlar to'plami)
#
# Ruxsatlar kredit jarayonining haqiqiy taqsimotiga mos:
#   front-office -> underwriting -> risk -> IT
ROLES: Dict[str, dict] = {
    "mijoz_menejeri": {
        "nom": "Mijoz menejeri",
        "tavsif": "Front-office: ariza qabul qiladi, mijozga qarorni tushuntiradi",
        "ruxsat": {"ariza:yuborish", "mijoz:korish", "simulyatsiya"},
    },
    "underwriter": {
        "nom": "Underwriter",
        "tavsif": "Qarorlar oqimini yuritadi, chegaraviy arizalarni ko'rib chiqadi",
        # Underwriter qaror chiqargan MODELNI ham ko'rishi shart — aks holda
        # "nega bu ball?" savoliga javob bera olmaydi.
        "ruxsat": {"ariza:yuborish", "mijoz:korish", "simulyatsiya",
                   "qarorlar:korish", "portfel:korish", "skorkarta:korish"},
    },
    "risk_menejer": {
        "nom": "Risk menejeri",
        "tavsif": "Skorkartani boshqaradi: versiyalar, qayta o'rgatish, portfel tahlili",
        "ruxsat": {"ariza:yuborish", "mijoz:korish", "simulyatsiya",
                   "qarorlar:korish", "portfel:korish",
                   "skorkarta:korish", "skorkarta:orgatish"},
    },
    "admin": {
        "nom": "Administrator",
        "tavsif": "Tizim ma'muri: foydalanuvchilar va audit izi",
        "ruxsat": {"ariza:yuborish", "mijoz:korish", "simulyatsiya",
                   "qarorlar:korish", "portfel:korish",
                   "skorkarta:korish", "skorkarta:orgatish",
                   "jurnal:korish", "foydalanuvchi:boshqarish"},
    },
}

# Demo hisoblar — login ekranida ko'rsatiladi. Hakaton uchun ataylab oddiy:
# hakam bir bosishda har bir rolni sinab ko'ra olishi kerak.
SEED_USERS = [
    ("aziza",   "Aziza Karimova",   "Mijoz menejeri",  "mijoz_menejeri", "aziza123"),
    ("bekzod",  "Bekzod Rustamov",  "Underwriter",     "underwriter",    "bekzod123"),
    ("dilnoza", "Dilnoza Yusupova", "Risk menejeri",   "risk_menejer",   "dilnoza123"),
    ("admin",   "Tizim ma'muri",    "Administrator",   "admin",          "admin123"),
]

SESSION_COOKIE = "windai_session"
SESSION_IDLE_MINUTES = 60
PBKDF2_ITERATIONS = 200_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    login       TEXT NOT NULL UNIQUE,
    ism         TEXT NOT NULL,
    lavozim     TEXT NOT NULL,
    rol         TEXT NOT NULL,
    parol_hash  TEXT NOT NULL,
    parol_salt  TEXT NOT NULL,
    faol        INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    last_login  TEXT
);

CREATE TABLE IF NOT EXISTS app_session (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES app_user(id),
    created_at TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_session_user ON app_session(user_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Parol
# ---------------------------------------------------------------------------


def hash_password(password: str, salt: Optional[bytes] = None) -> tuple:
    """(hash_hex, salt_hex). Sol berilmasa yangisi generatsiya qilinadi."""
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                 PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    """Vaqt bo'yicha hujumga chidamli taqqoslash."""
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, hash_hex)


# ---------------------------------------------------------------------------
# Sxema va boshlang'ich foydalanuvchilar
# ---------------------------------------------------------------------------


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_users(conn: sqlite3.Connection) -> int:
    """Demo hisoblarni yaratadi (mavjudlariga tegmaydi). Yaratilganlar sonini qaytaradi."""
    created = 0
    with conn:
        for login, ism, lavozim, rol, parol in SEED_USERS:
            row = conn.execute("SELECT 1 FROM app_user WHERE login = ?",
                               (login,)).fetchone()
            if row:
                continue
            h, s = hash_password(parol)
            conn.execute(
                "INSERT INTO app_user (login, ism, lavozim, rol, parol_hash, "
                "parol_salt, faol, created_at) VALUES (?,?,?,?,?,?,1,?)",
                (login, ism, lavozim, rol, h, s, now_iso()))
            created += 1
    return created


# ---------------------------------------------------------------------------
# Sessiya
# ---------------------------------------------------------------------------


def _user_row(conn: sqlite3.Connection, login: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM app_user WHERE login = ? AND faol = 1",
                        (login,)).fetchone()


def login(conn: sqlite3.Connection, user_login: str, password: str) -> Optional[str]:
    """To'g'ri bo'lsa sessiya tokenini, aks holda None qaytaradi."""
    row = _user_row(conn, (user_login or "").strip().lower())
    if row is None:
        # Mavjud bo'lmagan login uchun ham parol tekshiruvi qadar vaqt ketsin —
        # aks holda javob tezligi loginning bor-yo'qligini oshkor qiladi.
        hash_password(password or "")
        return None
    if not verify_password(password or "", row["parol_hash"], row["parol_salt"]):
        return None
    token = secrets.token_urlsafe(32)
    ts = now_iso()
    with conn:
        conn.execute("INSERT INTO app_session (token, user_id, created_at, last_seen) "
                     "VALUES (?,?,?,?)", (token, row["id"], ts, ts))
        conn.execute("UPDATE app_user SET last_login = ? WHERE id = ?", (ts, row["id"]))
    return token


def logout(conn: sqlite3.Connection, token: Optional[str]) -> None:
    if not token:
        return
    with conn:
        conn.execute("DELETE FROM app_session WHERE token = ?", (token,))


def current_user(conn: sqlite3.Connection, token: Optional[str]) -> Optional[dict]:
    """Tokendan foydalanuvchini oladi va `last_seen` ni yangilaydi (sliding).

    Idle timeout: oxirgi faollikdan `SESSION_IDLE_MINUTES` o'tgan bo'lsa
    sessiya o'chiriladi va None qaytadi.
    """
    if not token:
        return None
    row = conn.execute(
        "SELECT s.token, s.last_seen, u.* FROM app_session s "
        "JOIN app_user u ON u.id = s.user_id "
        "WHERE s.token = ? AND u.faol = 1", (token,)).fetchone()
    if row is None:
        return None

    try:
        last = datetime.fromisoformat(row["last_seen"])
    except ValueError:
        last = datetime.now(timezone.utc)
    if datetime.now(timezone.utc) - last > timedelta(minutes=SESSION_IDLE_MINUTES):
        logout(conn, token)
        return None

    with conn:
        conn.execute("UPDATE app_session SET last_seen = ? WHERE token = ?",
                     (now_iso(), token))
    return to_public(row)


def to_public(row) -> dict:
    """Foydalanuvchi obyekti — parol maydonlarisiz."""
    rol = row["rol"]
    meta = ROLES.get(rol, {})
    return {
        "id": row["id"],
        "login": row["login"],
        "ism": row["ism"],
        "lavozim": row["lavozim"],
        "rol": rol,
        "rol_nomi": meta.get("nom", rol),
        "rol_tavsifi": meta.get("tavsif", ""),
        "ruxsat": sorted(meta.get("ruxsat", set())),
    }


def has(user: Optional[dict], permission: str) -> bool:
    return bool(user) and permission in set(user.get("ruxsat", []))


def list_users(conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute("SELECT * FROM app_user ORDER BY id").fetchall()
    return [{**to_public(r), "faol": bool(r["faol"]),
             "last_login": r["last_login"]} for r in rows]


def demo_accounts() -> List[dict]:
    """Login ekranida ko'rsatiladigan demo hisoblar.

    Bu ATAYLAB ochiq: hakam har bir rolni bir bosishda sinab ko'rishi kerak.
    Haqiqiy tizimda bu ro'yxat bo'lmaydi.
    """
    return [{"login": login, "parol": parol, "ism": ism,
             "rol": rol, "rol_nomi": ROLES[rol]["nom"],
             "tavsif": ROLES[rol]["tavsif"]}
            for login, ism, _lavozim, rol, parol in SEED_USERS]
