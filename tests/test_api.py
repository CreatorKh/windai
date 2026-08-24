"""HTTP qatlami: ariza -> qaror -> tarix zanjiri va versiyalash."""
import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient          # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Har bir test seansi uchun toza baza."""
    import app.api as api_module
    from app.engine import CreditEngine

    tmp = tmp_path_factory.mktemp("api")
    api_module.engine = CreditEngine(db_path=tmp / "api.db")
    with TestClient(api_module.app) as c:
        # Endpointlar rol darvozasi ostida — testlar admin sifatida ishlaydi.
        # TestClient cookie ni o'zi saqlab qoladi.
        r = c.post("/api/auth/login", json={"login": "admin", "password": "admin123"})
        assert r.status_code == 200, r.text
        yield c


ARIZA = {
    "yosh": 34, "oila_azolari": 3, "bandlik": "byudjet", "talim": "oliy",
    "ish_staji_oy": 48, "mijoz_boldi_oy": 24,
    "deklaratsiya_daromad": 6_000_000, "oylik_daromad": 6_200_000,
    "oylik_chiqim": 3_400_000, "naqd_yechish": 700_000,
    "mavjud_oylik_yuk": 600_000, "mavjud_kredit_soni": 1,
    "kredit_qoldigi": 7_000_000, "max_kechikish_kun": 0,
    "sorlgan_summa": 20_000_000, "muddat_oy": 24, "maqsad": "iste'mol",
}


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    d = r.json()
    assert "ishsiz" in d["bandlik"]
    assert d["siyosat"]["APPROVE_SCORE"] > d["siyosat"]["REVIEW_SCORE"]
    assert d["dataset"]["test"] == 540


def test_scorecard_ochiladi(client):
    d = client.get("/api/scorecard").json()
    assert d["belgilar_soni"] > 5
    assert d["yaqinlashdi"] is True
    assert d["metrics"]["auc_cv"] > 0.7
    assert all(row["iv"] >= 0 for row in d["iv"])


def test_ariza_qaror_qaytaradi(client):
    r = client.post("/api/ariza", json=ARIZA)
    assert r.status_code == 200
    d = r.json()
    assert d["qaror"] in {"MAQULLANDI", "QOLDA_KORIB_CHIQISH", "RAD_ETILDI"}
    assert d["sabab"].strip()
    assert d["skoring"]["omillar"]
    assert d["decision_id"] > 0
    assert 0 <= d["pd"] <= 1


def test_ariza_tarixga_tushadi(client):
    app_id = client.post("/api/ariza", json=ARIZA).json()["application_id"]
    d = client.get(f"/api/ariza/{app_id}").json()
    assert d["tarix"][-1]["sabab"]
    assert d["tarix"][-1]["hash"]


def test_daromadsiz_ariza_400(client):
    bad = {**ARIZA, "oylik_daromad": 0, "deklaratsiya_daromad": 0}
    r = client.post("/api/ariza", json=bad)
    assert r.status_code == 400
    assert "daromad" in r.json()["detail"]


def test_ishsiz_rad_etiladi_va_sabab_aniq(client):
    d = client.post("/api/simulyatsiya",
                    json={**ARIZA, "bandlik": "ishsiz"}).json()
    assert d["qaror"] == "RAD_ETILDI"
    assert any(q["kod"] == "KO_BANDLIK" for q in d["qoidalar"])
    assert "ishsiz" in d["sabab"]


def test_90_kun_kechikish_rad_etiladi(client):
    d = client.post("/api/simulyatsiya",
                    json={**ARIZA, "max_kechikish_kun": 120}).json()
    assert d["qaror"] == "RAD_ETILDI"
    assert any(q["kod"] == "KO_KECHIKISH" for q in d["qoidalar"])


def test_simulyatsiya_jurnalga_yozmaydi(client):
    oldin = client.get("/api/jurnal?limit=1").json()["statistika"]["jami_qaror"]
    d = client.post("/api/simulyatsiya", json=ARIZA).json()
    keyin = client.get("/api/jurnal?limit=1").json()["statistika"]["jami_qaror"]
    assert d["saqlanmadi"] is True
    assert oldin == keyin


def test_daromad_oshsa_limit_oshadi(client):
    """What-if ekranining asosiy va'dasi."""
    kam = client.post("/api/simulyatsiya", json=ARIZA).json()
    kop = client.post("/api/simulyatsiya",
                      json={**ARIZA, "oylik_daromad": ARIZA["oylik_daromad"] * 2,
                            "deklaratsiya_daromad":
                                ARIZA["deklaratsiya_daromad"] * 2}).json()
    assert (kop["limit"]["tolov_qobiliyati_limiti"]
            > kam["limit"]["tolov_qobiliyati_limiti"])


def test_arizalar_royxati_va_filtr(client):
    client.post("/api/ariza", json=ARIZA)
    hammasi = client.get("/api/arizalar?limit=50").json()
    assert hammasi
    for q in {"MAQULLANDI", "QOLDA_KORIB_CHIQISH", "RAD_ETILDI"}:
        filtrlangan = client.get(f"/api/arizalar?limit=50&qaror={q}").json()
        assert all(r["qaror"] == q for r in filtrlangan)


def test_topilmagan_ariza_404(client):
    assert client.get("/api/ariza/YOQ_BUNAQA").status_code == 404


def test_jurnal_zanjiri_butun(client):
    d = client.get("/api/jurnal").json()
    assert d["zanjir"]["butun"] is True


def test_retrain_yangi_versiya_ochadi(client):
    oldin = client.get("/api/scorecard/versions").json()
    r = client.post("/api/scorecard/retrain",
                    json={"version": "test-v2", "l2": 1.0, "izoh": "test"})
    assert r.status_code == 200
    keyin = client.get("/api/scorecard/versions").json()
    assert len(keyin) == len(oldin) + 1
    assert sum(v["is_current"] for v in keyin) == 1        # faqat bittasi amalda
    assert keyin[-1]["version"] == "test-v2"


def test_bosh_belgilar_royxati_400(client):
    r = client.post("/api/scorecard/retrain",
                    json={"version": "x", "belgilar": ["yoq_bunaqa_belgi"]})
    assert r.status_code == 400


def test_versiyalarni_taqqoslash(client):
    """Eski qarorni ESKI skorkarta bilan qayta hisoblash — baza talabi."""
    app_id = client.post("/api/ariza", json=ARIZA).json()["application_id"]
    vs = client.get("/api/scorecard/versions").json()
    if len(vs) < 2:
        pytest.skip("kamida ikki versiya kerak")
    a, b = vs[0]["id"], vs[-1]["id"]
    d = client.get(f"/api/ariza/{app_id}/taqqoslash?a={a}&b={b}").json()
    assert d["a"]["scorecard_version_id"] == a
    assert d["b"]["scorecard_version_id"] == b
    assert "delta_ball" in d


def test_frontend_ochiladi(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Kredit" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


# ---------------------------------------------------------------------------
# Rol darvozalari
# ---------------------------------------------------------------------------
@pytest.fixture()
def anon(client):
    """Kirmagan mijoz — o'sha ilovaga, lekin cookie'siz."""
    import app.api as api_module
    with TestClient(api_module.app) as c:
        yield c


def _kir(c, login, parol):
    r = c.post("/api/auth/login", json={"login": login, "password": parol})
    assert r.status_code == 200, r.text
    return r.json()


def test_kirmasdan_401(anon):
    """Har bir himoyalangan endpoint kirmagan foydalanuvchini rad etadi."""
    for yol in ("/api/scorecard", "/api/arizalar", "/api/portfel",
                "/api/jurnal", "/api/mijozlar", "/api/statistika"):
        assert anon.get(yol).status_code == 401, yol
    assert anon.post("/api/ariza", json=ARIZA).status_code == 401


def test_meta_va_demo_ochiq(anon):
    """Login ekrani ishlashi uchun bu ikkisi ochiq bo'lishi shart."""
    assert anon.get("/api/meta").status_code == 200
    demo = anon.get("/api/auth/demo").json()
    assert {d["rol"] for d in demo} == {"mijoz_menejeri", "underwriter",
                                        "risk_menejer", "admin"}
    assert all(d["login"] and d["parol"] for d in demo)


def test_notogri_parol_401(anon):
    assert anon.post("/api/auth/login",
                     json={"login": "admin", "password": "xato"}).status_code == 401
    assert anon.post("/api/auth/login",
                     json={"login": "yoq", "password": "x"}).status_code == 401


def test_mijoz_menejeri_modelni_orgata_olmaydi(anon):
    u = _kir(anon, "aziza", "aziza123")
    assert u["rol"] == "mijoz_menejeri"
    # ruxsati bor
    assert anon.post("/api/simulyatsiya", json=ARIZA).status_code == 200
    assert anon.get("/api/mijozlar").status_code == 200
    # ruxsati yo'q
    for yol in ("/api/arizalar", "/api/portfel", "/api/scorecard", "/api/jurnal"):
        assert anon.get(yol).status_code == 403, yol
    assert anon.post("/api/scorecard/retrain",
                     json={"version": "x"}).status_code == 403


def test_underwriter_qarorlarni_koradi_lekin_orgatmaydi(anon):
    u = _kir(anon, "bekzod", "bekzod123")
    assert u["rol"] == "underwriter"
    for yol in ("/api/arizalar", "/api/portfel", "/api/scorecard",
                "/api/statistika"):
        assert anon.get(yol).status_code == 200, yol
    assert anon.get("/api/jurnal").status_code == 403          # xom audit izi
    assert anon.post("/api/scorecard/retrain",
                     json={"version": "x"}).status_code == 403


def test_risk_menejer_orgata_oladi_auditni_kormaydi(anon):
    _kir(anon, "dilnoza", "dilnoza123")
    assert anon.get("/api/scorecard").status_code == 200
    assert anon.get("/api/jurnal").status_code == 403
    assert anon.get("/api/foydalanuvchilar").status_code == 403


def test_admin_hammasini_koradi(anon):
    _kir(anon, "admin", "admin123")
    for yol in ("/api/jurnal", "/api/foydalanuvchilar", "/api/scorecard",
                "/api/portfel", "/api/statistika"):
        assert anon.get(yol).status_code == 200, yol


def test_chiqishdan_keyin_sessiya_oladi(anon):
    _kir(anon, "admin", "admin123")
    assert anon.get("/api/auth/me").status_code == 200
    assert anon.post("/api/auth/logout").status_code == 200
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/scorecard").status_code == 401


def test_qaror_jurnalida_xodim_qayd_etiladi(anon):
    """Audit izi: qarorni KIM chiqargani yozilishi va hash zanjiriga kirishi kerak."""
    _kir(anon, "bekzod", "bekzod123")
    app_id = anon.post("/api/ariza", json=ARIZA).json()["application_id"]
    _kir(anon, "admin", "admin123")
    tarix = anon.get(f"/api/ariza/{app_id}").json()["tarix"]
    assert tarix[-1]["kim"] == "bekzod"
    assert anon.get("/api/jurnal").json()["zanjir"]["butun"] is True


def test_parol_ochiq_matnda_saqlanmaydi(client):
    """Bazada parol emas, faqat pbkdf2 hash va sol turishi kerak."""
    import app.api as api_module
    from app import auth
    row = api_module.engine.conn.execute(
        "SELECT * FROM app_user WHERE login = 'admin'").fetchone()
    assert "admin123" not in row["parol_hash"]
    assert len(row["parol_hash"]) == 64 and len(row["parol_salt"]) == 32
    assert auth.verify_password("admin123", row["parol_hash"], row["parol_salt"])
    assert not auth.verify_password("admin124", row["parol_hash"], row["parol_salt"])


def test_mijoz_kartasi(client):
    d = client.get("/api/mijoz/A000003").json()
    assert d["applicant"]["applicant_id"] == "A000003"
    assert len(d["oqim"]) == 12
    assert d["korsatkichlar"]["daromad_median"] > 0
    assert isinstance(d["arizalar"], list)
    assert client.get("/api/mijoz/YOQ").status_code == 404


def test_mijoz_grafi(client):
    """Aloqalar grafi: tugunlar, qatlamlar va halollik maydonlari."""
    d = client.get("/api/mijoz/A000003/graf").json()
    assert d["root"] == "cA000003"
    types = {n["type"] for n in d["nodes"]}
    assert "client" in types                       # markaz + o'xshashlar
    kinds = {e["kind"] for e in d["edges"]}
    assert "similar" in kinds
    # halollik maydonlari: nima kesildi, nima yo'q — javobda bo'lishi shart
    assert "missing" in d and d["missing"]
    assert "took" in d and d["took"]["total"] >= 0
    # o'xshash mijoz qirralarida izoh (qaysi belgilar bo'yicha yaqin)
    sim = [e for e in d["edges"] if e["kind"] == "similar"]
    assert sim and all(e.get("label") for e in sim)
    assert client.get("/api/mijoz/YOQ/graf").status_code == 404
