"""Baza talablari: o'zgarmas jurnal + SCD Type 2 versiyalash."""
import json
import sqlite3

import pytest

from app import db
from app.decision import decide
from app.features import build_features


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture()
def bitta_qaror(dataset, trained):
    app = dataset.test()[0]
    feats = build_features(app, dataset.profile(app["applicant_id"]))
    return app, decide(feats, trained)


# --------------------------------------------------------------------------
# SCD Type 2
# --------------------------------------------------------------------------
def test_yangi_versiya_eskisini_yopadi(conn):
    v1 = db.save_scorecard(conn, "v1", {"a": 1}, {"auc": 0.7})
    v2 = db.save_scorecard(conn, "v2", {"a": 2}, {"auc": 0.8})
    rows = {r["id"]: r for r in db.list_versions(conn)}
    assert rows[v1]["is_current"] == 0 and rows[v1]["valid_to"] is not None
    assert rows[v2]["is_current"] == 1 and rows[v2]["valid_to"] is None
    assert db.current_version(conn)["id"] == v2


def test_eski_versiya_ochirilmaydi(conn):
    db.save_scorecard(conn, "v1", {"a": 1}, {})
    db.save_scorecard(conn, "v2", {"a": 2}, {})
    db.save_scorecard(conn, "v3", {"a": 3}, {})
    assert len(db.list_versions(conn)) == 3


def test_eski_versiya_payloadi_saqlanib_qoladi(conn):
    """Eski qarorni eski skorkarta bilan qayta hisoblash uchun shart."""
    v1 = db.save_scorecard(conn, "v1", {"koef": [1, 2, 3]}, {})
    db.save_scorecard(conn, "v2", {"koef": [9, 9, 9]}, {})
    assert json.loads(db.get_version(conn, v1)["payload"])["koef"] == [1, 2, 3]


def test_bir_xil_payload_idempotent(conn):
    """Aynan bir xil skorkarta qayta saqlansa — yangi satr ochilmaydi."""
    a = db.save_scorecard(conn, "v1", {"a": 1}, {})
    b = db.save_scorecard(conn, "v1", {"a": 1}, {})
    assert a == b and len(db.list_versions(conn)) == 1


def test_bir_xil_nom_boshqa_payload_yangi_satr_ochadi(conn):
    """Nom band, mazmuni boshqa -> `v1#2` ochiladi, eskisi YOPILADI.

    Regressiya: avval eski id qaytarilib, yangi payload jimgina tashlanardi.
    Natijada xotiradagi skorkarta bazadagidan farq qilib qolar va "eski
    qarorni eski versiya bilan qayta hisoblash" kafolati buzilardi.
    """
    a = db.save_scorecard(conn, "v1", {"a": 1}, {})
    b = db.save_scorecard(conn, "v1", {"a": 2}, {})
    assert b != a
    rows = {r["id"]: r for r in db.list_versions(conn)}
    assert len(rows) == 2
    assert rows[a]["is_current"] == 0 and rows[a]["valid_to"] is not None
    assert rows[b]["is_current"] == 1 and rows[b]["version"] == "v1#2"
    # Eski payload buzilmagan — tarixiy qarorni qayta hisoblash mumkin.
    assert json.loads(db.get_version(conn, a)["payload"]) == {"a": 1}


# --------------------------------------------------------------------------
# Immutability
# --------------------------------------------------------------------------
def test_jurnalni_ozgartirib_bolmaydi(conn, bitta_qaror):
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    did = db.append_decision(conn, d, vid)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE decision_journal SET qaror = 'MAQULLANDI' WHERE id = ?",
                     (did,))


def test_jurnaldan_ochirib_bolmaydi(conn, bitta_qaror):
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    did = db.append_decision(conn, d, vid)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM decision_journal WHERE id = ?", (did,))


def test_qayta_qaror_yangi_satr_qoshadi_eskisini_ozgartirmaydi(conn, bitta_qaror):
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    db.append_decision(conn, d, vid)
    db.append_decision(conn, d, vid)
    tarix = db.decision_history(conn, app["application_id"])
    assert len(tarix) == 2
    assert tarix[0]["id"] < tarix[1]["id"]


# --------------------------------------------------------------------------
# Hash zanjiri
# --------------------------------------------------------------------------
def test_zanjir_butun(conn, bitta_qaror):
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    for _ in range(5):
        db.append_decision(conn, d, vid)
    r = db.verify_chain(conn)
    assert r["butun"] is True and r["tekshirildi"] == 5


def test_zanjir_buzilishini_topadi(conn, bitta_qaror):
    """Trigger'ni chetlab o'tib satr almashtirilsa ham hash buni ochib beradi."""
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    for _ in range(3):
        db.append_decision(conn, d, vid)

    # Trigger'ni vaqtincha o'chirib, "ichki buzg'unchi" ni modellashtiramiz.
    conn.executescript("DROP TRIGGER trg_decision_no_update;")
    conn.execute("UPDATE decision_journal SET ball = 999 WHERE id = 2")
    conn.commit()

    r = db.verify_chain(conn)
    assert r["butun"] is False and r["buzilgan_id"] == 2


def test_bosh_jurnal_butun_hisoblanadi(conn):
    assert db.verify_chain(conn) == {"butun": True, "buzilgan_id": None,
                                     "tekshirildi": 0}


# --------------------------------------------------------------------------
# Ariza -> qaror -> tarix zanjiri
# --------------------------------------------------------------------------
def test_ariza_qaror_tarix_zanjiri(conn, bitta_qaror):
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    db.append_decision(conn, d, vid)

    saqlangan = db.get_application(conn, app["application_id"])
    assert saqlangan["applicant_id"] == app["applicant_id"]

    tarix = db.decision_history(conn, app["application_id"])
    assert tarix[0]["scorecard"] == "v1"
    assert tarix[0]["sabab"] == d.sabab
    assert tarix[0]["payload"]["skoring"]["omillar"]


def test_omillar_alohida_jadvalga_yoziladi(conn, bitta_qaror):
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    did = db.append_decision(conn, d, vid)
    n = conn.execute("SELECT COUNT(*) n FROM decision_factor WHERE decision_id = ?",
                     (did,)).fetchone()["n"]
    assert n == len(d.score.contributions) > 0


def test_stats(conn, bitta_qaror):
    app, d = bitta_qaror
    vid = db.save_scorecard(conn, "v1", {}, {})
    db.upsert_application(conn, app)
    db.append_decision(conn, d, vid)
    s = db.stats(conn)
    assert s["jami_qaror"] == 1 and s["arizalar"] == 1
    assert d.qaror in s["qarorlar"]


# --------------------------------------------------------------------------
# Ko'p oqimli xavfsizlik (regressiya testi)
# --------------------------------------------------------------------------
def test_kop_oqimda_qulamaydi(tmp_path, dataset, trained):
    """Bitta sqlite ulanishini oqimlar bo'ylab BO'LISHIB BO'LMAYDI.

    Regressiya: avval `CreditEngine` bitta `sqlite3.Connection` ni
    `check_same_thread=False` bilan saqlar edi. Bu bayroq faqat Python
    tekshiruvini o'chiradi — C darajasida hech nima himoyalanmaydi.
    FastAPI sync endpointlarni threadpool da bajargani uchun parallel
    so'rovlar bitta ulanishga tushar va jarayon SIGSEGV bilan qular edi
    (macOS libsqlite3: sqlite3LockAndPrepare -> sqlite3GenerateColumnNames).
    Server demo paytida 30-60 soniyada o'lardi.

    Bu test tuzatishdan OLDIN pytest ni segfault bilan o'ldirardi.
    """
    import threading

    from app.decision import decide
    from app.engine import CreditEngine
    from app.features import build_features

    engine = CreditEngine(db_path=tmp_path / "concurrent.db")
    engine.ensure_scorecard("v1")
    app0 = engine.data.test()[0]
    engine.record(app0, engine.decide(app0, engine.features_of(app0)), "dataset")

    errors = []

    def reader():
        try:
            for _ in range(40):
                db.recent_decisions(engine.conn, limit=25)
                db.verify_chain(engine.conn)
                db.stats(engine.conn)
                db.decision_history(engine.conn, app0["application_id"])
        except Exception as exc:                       # pragma: no cover
            errors.append(repr(exc))

    def writer(idx):
        try:
            for j in range(8):
                alt = dict(app0, application_id=f"CONC{idx}_{j}")
                engine.record(alt, engine.decide(alt, engine.features_of(alt)), "web")
        except Exception as exc:                       # pragma: no cover
            errors.append(repr(exc))

    threads = ([threading.Thread(target=reader) for _ in range(6)]
               + [threading.Thread(target=writer, args=(i,)) for i in range(3)])
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=90)

    assert not any(t.is_alive() for t in threads), "oqimlar osilib qoldi"
    assert errors == []
    assert db.verify_chain(engine.conn)["butun"] is True
    # 1 boshlang'ich + 3 yozuvchi x 8 = 25 yozuv
    assert db.stats(engine.conn)["jami_qaror"] == 25


def test_har_bir_oqim_oz_ulanishini_oladi(tmp_path):
    """`Database.conn` — oqimga bog'langan; ikki oqim bir obyektni ko'rmaydi."""
    import threading

    d = db.Database(tmp_path / "tl.db")
    seen = {}

    def grab(name):
        seen[name] = id(d.conn)

    main_id = id(d.conn)
    t = threading.Thread(target=grab, args=("other",))
    t.start()
    t.join()
    assert seen["other"] != main_id
