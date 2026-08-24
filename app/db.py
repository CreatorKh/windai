"""Ma'lumotlar bazasi: ariza -> qaror -> tarix zanjiri.

Ikkita baza talabi shu faylda bajariladi:

1) IMMUTABLE QAROR JURNALI
   `decision_journal` faqat INSERT ni qabul qiladi. UPDATE va DELETE
   SQLite trigger'lari bilan bloklangan (RAISE(ABORT)). Qo'shimcha himoya —
   HASH ZANJIRI: har bir yozuv oldingi yozuv hash'ini o'z ichiga oladi
   (`prev_hash`), shuning uchun o'tmishdagi bitta satrni jimgina almashtirish
   zanjirni buzadi va `verify_chain()` buni topadi.

2) SKORKARTA VERSIYALASH (SCD Type 2)
   `scorecard_version` jadvalida `valid_from` / `valid_to` / `is_current`.
   Yangi versiya kelganda eskisi yopiladi, o'chirilmaydi. Har bir qaror
   qaysi versiya bilan chiqarilganini saqlaydi, shuning uchun eski qarorni
   ayni o'sha eski skorkarta bilan qayta hisoblash mumkin
   (`rescore_with_version`).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- arizachi
CREATE TABLE IF NOT EXISTS applicant (
    applicant_id TEXT PRIMARY KEY,
    payload      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- ------------------------------------------------------------------ ariza
CREATE TABLE IF NOT EXISTS application (
    application_id TEXT PRIMARY KEY,
    applicant_id   TEXT NOT NULL,
    manba          TEXT NOT NULL DEFAULT 'dataset',  -- dataset | web
    payload        TEXT NOT NULL,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_application_applicant
    ON application(applicant_id);

-- --------------------------------------------- skorkarta versiyasi (SCD2)
CREATE TABLE IF NOT EXISTS scorecard_version (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    version     TEXT NOT NULL,
    payload     TEXT NOT NULL,          -- to'liq skorkarta (binning + koef.)
    metrics     TEXT NOT NULL DEFAULT '{}',
    izoh        TEXT NOT NULL DEFAULT '',
    valid_from  TEXT NOT NULL,
    valid_to    TEXT,                   -- NULL = hali amalda
    is_current  INTEGER NOT NULL DEFAULT 1
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_scorecard_version ON scorecard_version(version);
CREATE INDEX IF NOT EXISTS ix_scorecard_current ON scorecard_version(is_current);

-- ------------------------------------------- o'zgarmas qarorlar jurnali
CREATE TABLE IF NOT EXISTS decision_journal (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    version_id     INTEGER NOT NULL REFERENCES scorecard_version(id),
    qaror          TEXT NOT NULL,
    ball           REAL NOT NULL,
    pd             REAL NOT NULL,
    sabab          TEXT NOT NULL,
    tavsiya_summa  REAL NOT NULL DEFAULT 0,
    payload        TEXT NOT NULL,       -- to'liq qaror (omillar bilan)
    kim            TEXT NOT NULL DEFAULT 'tizim',   -- qarorni chiqargan xodim
    created_at     TEXT NOT NULL,
    prev_hash      TEXT NOT NULL,
    hash           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decision_app ON decision_journal(application_id);
CREATE INDEX IF NOT EXISTS ix_decision_ver ON decision_journal(version_id);

-- Immutability: jurnalni o'zgartirish/o'chirish taqiqlanadi.
CREATE TRIGGER IF NOT EXISTS trg_decision_no_update
BEFORE UPDATE ON decision_journal
BEGIN
    SELECT RAISE(ABORT, 'decision_journal o''zgarmas: UPDATE taqiqlangan');
END;

CREATE TRIGGER IF NOT EXISTS trg_decision_no_delete
BEFORE DELETE ON decision_journal
BEGIN
    SELECT RAISE(ABORT, 'decision_journal o''zgarmas: DELETE taqiqlangan');
END;

-- ------------------------------------------------- omillar hissasi (audit)
CREATE TABLE IF NOT EXISTS decision_factor (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES decision_journal(id),
    kalit       TEXT NOT NULL,
    nom         TEXT NOT NULL,
    qiymat      TEXT,
    bucket      TEXT,
    woe         REAL NOT NULL,
    beta        REAL NOT NULL,
    ball        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_factor_decision ON decision_factor(decision_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Bitta ulanish ochadi va sxemani yaratadi (bir oqimli foydalanish uchun)."""
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(p)
    conn.executescript(SCHEMA)
    from . import auth
    auth.ensure_schema(conn)
    return conn


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class Database:
    """Har bir oqim (thread) uchun ALOHIDA sqlite ulanishi.

    Nega shart. `check_same_thread=False` faqat Python darajasidagi
    tekshiruvni o'chiradi — u C darajasida hech qanday xavfsizlik BERMAYDI.
    Bitta `sqlite3.Connection` obyektini ikki oqimdan bir vaqtda ishlatish
    macOS ning tizim libsqlite3 kutubxonasida xotirani buzadi va jarayon
    SIGSEGV bilan qulaydi (stek: sqlite3LockAndPrepare ->
    sqlite3GenerateColumnNames -> sqlite3DbMallocRawNNTyped).

    FastAPI `def` (sync) endpointlarni threadpool da bajaradi, ya'ni bir
    nechta so'rov PARALLEL ravishda bitta ulanishga tushardi. Bu demo
    paytida kafolatlangan qulash edi: server 30-60 soniyada o'lardi.

    Yechim: ulanish oqimga bog'lanadi (threading.local). Yozuvlar esa
    `write_lock` bilan ketma-ketlashtiriladi — hash zanjiri uzluksiz
    bo'lishi uchun "oxirgi hash ni o'qish + yangi satr qo'shish" atomar
    bajarilishi kerak. O'qishlar WAL rejimida parallel ketaveradi.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.write_lock = threading.RLock()
        boot = _open(self.path)          # sxemani bir marta yaratamiz
        boot.executescript(SCHEMA)
        from . import auth                       # aylanma importdan qochish
        auth.ensure_schema(boot)
        auth.seed_users(boot)
        boot.close()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = _open(self.path)
            self._local.conn = c
        return c

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None


# ---------------------------------------------------------------------------
# Skorkarta versiyalari (SCD Type 2)
# ---------------------------------------------------------------------------


def save_scorecard(conn: sqlite3.Connection, version: str, payload: dict,
                   metrics: dict, izoh: str = "") -> int:
    """Yangi versiyani ochadi, oldingisini yopadi (SCD Type 2). O(1).

    Bir xil `version` nomi bilan qayta chaqirilganda:
      * payload AYNAN o'sha bo'lsa -> eski id qaytadi (idempotent);
      * payload FARQ qilsa -> `v1#2` kabi suffiks bilan YANGI satr ochiladi.

    Nega. Avval nom band bo'lsa eski id qaytarilar, yangi payload esa
    yozilmasdan tashlanardi. Natijada xotiradagi skorkarta bazadagidan farq
    qilib qolar va "eski qarorni eski versiya bilan qayta hisoblash"
    kafolati buzilardi: jurnalda ball 630.91, qayta hisoblaganda 625.70 —
    qaror MAQULLANDI dan QOLDA_KORIB_CHIQISH ga o'tib ketardi.
    """
    ts = now_iso()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    with conn:
        row = conn.execute(
            "SELECT id, payload FROM scorecard_version WHERE version = ?", (version,)
        ).fetchone()
        if row is not None:
            if row["payload"] == payload_json:   # o'zgarish yo'q — idempotent
                return row["id"]
            base, n = version, 2                 # nom band, mazmuni boshqa
            while conn.execute("SELECT 1 FROM scorecard_version WHERE version = ?",
                               (f"{base}#{n}",)).fetchone():
                n += 1
            version = f"{base}#{n}"
        conn.execute(
            "UPDATE scorecard_version SET valid_to = ?, is_current = 0 "
            "WHERE is_current = 1", (ts,))
        cur = conn.execute(
            "INSERT INTO scorecard_version "
            "(version, payload, metrics, izoh, valid_from, valid_to, is_current) "
            "VALUES (?,?,?,?,?,NULL,1)",
            (version, payload_json,
             json.dumps(metrics, ensure_ascii=False), izoh, ts))
        return cur.lastrowid


def current_version(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM scorecard_version WHERE is_current = 1 "
        "ORDER BY id DESC LIMIT 1").fetchone()


def get_version(conn: sqlite3.Connection, version_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM scorecard_version WHERE id = ?",
                        (version_id,)).fetchone()


def list_versions(conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT id, version, metrics, izoh, valid_from, valid_to, is_current "
        "FROM scorecard_version ORDER BY id").fetchall()
    return [{**dict(r), "metrics": json.loads(r["metrics"])} for r in rows]


# ---------------------------------------------------------------------------
# Arizalar
# ---------------------------------------------------------------------------


def upsert_applicant(conn: sqlite3.Connection, applicant: dict) -> None:
    with conn:
        conn.execute(
            "INSERT INTO applicant (applicant_id, payload, created_at) VALUES (?,?,?) "
            "ON CONFLICT(applicant_id) DO UPDATE SET payload = excluded.payload",
            (applicant["applicant_id"],
             json.dumps(applicant, ensure_ascii=False), now_iso()))


def upsert_application(conn: sqlite3.Connection, application: dict,
                       manba: str = "dataset") -> None:
    with conn:
        conn.execute(
            "INSERT INTO application "
            "(application_id, applicant_id, manba, payload, created_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(application_id) DO UPDATE SET payload = excluded.payload",
            (application["application_id"], application["applicant_id"], manba,
             json.dumps(application, ensure_ascii=False), now_iso()))


def get_application(conn: sqlite3.Connection, application_id: str) -> Optional[dict]:
    r = conn.execute("SELECT * FROM application WHERE application_id = ?",
                     (application_id,)).fetchone()
    return json.loads(r["payload"]) if r else None


# ---------------------------------------------------------------------------
# Qarorlar jurnali (append-only + hash zanjiri)
# ---------------------------------------------------------------------------


GENESIS = "0" * 64


def _last_hash(conn: sqlite3.Connection) -> str:
    r = conn.execute("SELECT hash FROM decision_journal ORDER BY id DESC LIMIT 1"
                     ).fetchone()
    return r["hash"] if r else GENESIS


def _row_hash(prev_hash: str, application_id: str, version_id: int, qaror: str,
              ball: float, pd: float, created_at: str, payload_json: str,
              kim: str = "tizim") -> str:
    # `kim` ham zanjirga kiradi: audit izida javobgar xodimni keyinchalik
    # jimgina almashtirib bo'lmasin.
    blob = "|".join([prev_hash, application_id, str(version_id), qaror,
                     f"{ball:.6f}", f"{pd:.8f}", created_at, payload_json, kim])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def append_decision(conn: sqlite3.Connection, decision, version_id: int,
                    kim: str = "tizim") -> int:
    """Jurnalga yangi yozuv qo'shadi. Faqat INSERT — o'zgartirish yo'q. O(1).

    `kim` — qarorni chiqargan xodimning login i. Regulyator audit izida
    javobgarni ko'rishi kerak, shuning uchun u hash zanjiriga ham kiradi.
    """
    payload = decision.to_dict()
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    created_at = now_iso()
    with conn:
        prev = _last_hash(conn)
        h = _row_hash(prev, decision.application_id, version_id, decision.qaror,
                      decision.score.score, decision.score.pd, created_at,
                      payload_json, kim)
        cur = conn.execute(
            "INSERT INTO decision_journal (application_id, version_id, qaror, "
            "ball, pd, sabab, tavsiya_summa, payload, kim, created_at, "
            "prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (decision.application_id, version_id, decision.qaror,
             decision.score.score, decision.score.pd, decision.sabab,
             decision.tavsiya_summa, payload_json, kim, created_at, prev, h))
        did = cur.lastrowid
        conn.executemany(
            "INSERT INTO decision_factor "
            "(decision_id, kalit, nom, qiymat, bucket, woe, beta, ball) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [(did, c.key, c.label, str(c.value), c.bin_label, c.woe, c.beta,
              c.points) for c in decision.score.contributions])
    return did


def decision_history(conn: sqlite3.Connection, application_id: str) -> List[dict]:
    """Ariza -> qaror -> tarix zanjiri (eng yangisi oxirida)."""
    rows = conn.execute(
        "SELECT d.*, v.version AS scorecard "
        "FROM decision_journal d JOIN scorecard_version v ON v.id = d.version_id "
        "WHERE d.application_id = ? ORDER BY d.id", (application_id,)).fetchall()
    return [{"id": r["id"], "qaror": r["qaror"], "ball": r["ball"], "pd": r["pd"],
             "sabab": r["sabab"], "scorecard": r["scorecard"],
             "kim": r["kim"] if "kim" in r.keys() else "tizim",
             "version_id": r["version_id"], "created_at": r["created_at"],
             "hash": r["hash"], "prev_hash": r["prev_hash"],
             "payload": json.loads(r["payload"])} for r in rows]


def recent_decisions(conn: sqlite3.Connection, limit: int = 100,
                     qaror: Optional[str] = None) -> List[dict]:
    sql = ("SELECT d.id, d.application_id, d.qaror, d.ball, d.pd, d.sabab, "
           "d.tavsiya_summa, d.kim, d.created_at, v.version AS scorecard "
           "FROM decision_journal d JOIN scorecard_version v ON v.id = d.version_id ")
    args: list = []
    if qaror:
        sql += "WHERE d.qaror = ? "
        args.append(qaror)
    sql += "ORDER BY d.id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def verify_chain(conn: sqlite3.Connection) -> dict:
    """Hash zanjirini boshidan oxirigacha qayta hisoblab tekshiradi. O(n)."""
    prev = GENESIS
    checked = 0
    for r in conn.execute("SELECT * FROM decision_journal ORDER BY id"):
        expected = _row_hash(prev, r["application_id"], r["version_id"], r["qaror"],
                             r["ball"], r["pd"], r["created_at"], r["payload"],
                             r["kim"] if "kim" in r.keys() else "tizim")
        if r["prev_hash"] != prev or r["hash"] != expected:
            return {"butun": False, "buzilgan_id": r["id"], "tekshirildi": checked}
        prev = r["hash"]
        checked += 1
    return {"butun": True, "buzilgan_id": None, "tekshirildi": checked}


def stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) n, AVG(ball) avg_ball, AVG(pd) avg_pd FROM decision_journal"
    ).fetchone()
    by = {r["qaror"]: r["n"] for r in conn.execute(
        "SELECT qaror, COUNT(*) n FROM decision_journal GROUP BY qaror")}
    return {"jami_qaror": row["n"] or 0,
            "ortacha_ball": round(row["avg_ball"] or 0, 1),
            "ortacha_pd": round(row["avg_pd"] or 0, 4),
            "qarorlar": by,
            "arizalar": conn.execute("SELECT COUNT(*) n FROM application"
                                     ).fetchone()["n"]}
