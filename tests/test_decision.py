"""Izohlanuvchanlik shartnomasi — mavzuning ASOSIY talabi.

Bu fayldagi testlar TZ dagi "tuzoq" ni qo'riqlaydi: qaror hech qachon
sababsiz chiqmasligi va ball omillar hissasining ANIQ yig'indisi bo'lishi
kerak (approksimatsiya emas).
"""
import pytest

from app.config import APPROVE_SCORE, MAX_DTI, REVIEW_SCORE, SCORE_MAX, SCORE_MIN
from app.decision import APPROVE, DECLINE, REVIEW, decide, knockout_rules
from app.features import build_features
from app.loaders import label_of


# --------------------------------------------------------------------------
# Ball = neytral tayanch + hissalar yig'indisi
# --------------------------------------------------------------------------
def test_hissalar_yigindisi_ballni_beradi(trained, train_rows):
    rows, _ = train_rows
    for r in rows[:200]:
        res = trained.score(r)
        kutilgan = res.neutral + sum(c.points for c in res.contributions)
        if SCORE_MIN < res.score < SCORE_MAX:      # shiftga urilmagan holatlar
            assert res.score == pytest.approx(kutilgan, abs=1e-6), r["application_id"]


def test_har_bir_belgi_uchun_bitta_hissa(trained, train_rows):
    rows, _ = train_rows
    res = trained.score(rows[0])
    kalitlar = [c.key for c in res.contributions]
    assert len(kalitlar) == len(set(kalitlar)) == len(trained.spec)


def test_hissa_belgisi_woe_ga_mos(trained, train_rows):
    """WOE musbat (xavf yuqori) -> ball hissasi manfiy bo'lishi shart.

    Barcha beta >= 0 (wrong-sign elimination) bo'lgani uchun bu invariant
    butun skorkarta bo'ylab saqlanadi — aks holda izoh yolg'on bo'lardi
    ("DTI yuqori, shuning uchun +10 ball").
    """
    rows, _ = train_rows
    for r in rows[:100]:
        for c in trained.score(r).contributions:
            if abs(c.woe) > 1e-9 and abs(c.beta) > 1e-9:
                assert (c.woe > 0) == (c.points < 0)


def test_barcha_beta_manfiy_emas(trained):
    assert all(b >= -1e-9 for b in trained.model.coef)


# --------------------------------------------------------------------------
# Sabab hech qachon bo'sh emas
# --------------------------------------------------------------------------
def test_har_bir_qaror_sababga_ega(trained, dataset):
    """540 ta test arizasining HAMMASIDA sabab bo'lishi kerak."""
    bosh = []
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = decide(feats, trained)
        if not d.sabab or not d.sabab.strip():
            bosh.append(app["application_id"])
    assert bosh == []


def test_rad_javobida_aniq_omil_korsatiladi(trained, dataset):
    """Rad etilgan har bir arizada raqamli dalil bo'lishi shart."""
    tekshirildi = 0
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = decide(feats, trained)
        if d.qaror != DECLINE:
            continue
        tekshirildi += 1
        assert d.sabab.startswith("Rad etildi:")
        assert any(ch.isdigit() for ch in d.sabab)      # raqamli dalil
        assert d.rules, "rad javobi hech bo'lmasa bitta qoidaga tayanishi kerak"
        assert any(r.qaror == DECLINE for r in d.rules)
    assert tekshirildi > 0


def test_maqullashda_ijobiy_omillar_korsatiladi(trained, dataset):
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = decide(feats, trained)
        if d.qaror == APPROVE:
            assert "Asosiy ijobiy omillar" in d.sabab
            assert d.tavsiya_summa > 0
            return
    pytest.skip("test to'plamida ma'qullangan ariza yo'q")


# --------------------------------------------------------------------------
# Knock-out qoidalari
# --------------------------------------------------------------------------
def test_ishsizlik_knockout():
    r = knockout_rules({"bandlik": "ishsiz", "income_used": 1_000_000, "yosh": 30})
    assert any(x.kod == "KO_BANDLIK" and x.qaror == DECLINE for x in r)


def test_90_kun_kechikish_knockout():
    r = knockout_rules({"max_delinq": 95, "income_used": 5_000_000, "yosh": 35})
    assert any(x.kod == "KO_KECHIKISH" and x.qaror == DECLINE for x in r)


def test_yosh_chegarasi_knockout():
    assert any(x.kod == "KO_YOSH" for x in
               knockout_rules({"yosh": 17, "income_used": 1, "bandlik": "IT"}))
    assert any(x.kod == "KO_YOSH" for x in
               knockout_rules({"yosh": 80, "income_used": 1, "bandlik": "IT"}))
    assert not any(x.kod == "KO_YOSH" for x in
                   knockout_rules({"yosh": 40, "income_used": 1, "bandlik": "IT"}))


def test_toza_profilda_knockout_yoq():
    r = knockout_rules({"yosh": 35, "max_delinq": 0, "bandlik": "byudjet",
                        "income_used": 6_000_000, "ish_staji_oy": 60})
    assert r == []


# --------------------------------------------------------------------------
# Siyosat: DTI oshishi — rad emas, kamaytirilgan taklif
# --------------------------------------------------------------------------
def _feats(**over):
    base = {
        "application_id": "T1", "applicant_id": "T1",
        "dti": 0.2, "pti": 0.1, "dti_current": 0.1, "free_cash": 3_000_000,
        "income_missing": 0.0, "income_median": 5_000_000, "income_cv": 0.05,
        "income_trend": 1.0, "burn_ratio": 0.5, "cash_ratio": 0.1,
        "zero_months": 0.0, "buffer_months": 2.0, "net_flow": 1_000_000,
        "max_delinq": 0.0, "ever_delinq_30": 0.0, "ever_delinq_90": 0.0,
        "active_count": 0.0, "bank_count": 0.0, "has_credit_history": 0.0,
        "balance_to_income": 0.0, "requested": 10_000_000, "term_months": 24.0,
        "new_payment": 500_000, "loan_to_income": 0.2, "maqsad": "iste'mol",
        "yosh": 35.0, "ish_staji_oy": 60.0, "bandlik": "byudjet",
        "talim": "oliy", "oila_azolari": 2.0, "mijoz_boldi_oy": 24.0,
        "viloyat": "Toshkent", "income_used": 5_000_000,
        "declared_income": 5_000_000, "income_gap": 1.0,
        "income_per_capita": 2_500_000,
    }
    base.update(over)
    return base


def test_dti_oshsa_rad_emas_balki_kamaytirilgan_taklif(trained):
    """To'lov qobiliyati bor ekan, katta so'rov RAD emas — counter-offer."""
    d = decide(_feats(dti=MAX_DTI + 0.3, pti=0.45, requested=300_000_000), trained)
    assert d.qaror == REVIEW
    assert 0 < d.tavsiya_summa < 300_000_000
    assert "taklif" in d.sabab or "qobiliyati" in d.sabab


def test_tavsiya_hech_qachon_sorovdan_oshmaydi(trained, dataset):
    for app in dataset.test()[:150]:
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = decide(feats, trained)
        assert d.tavsiya_summa <= feats["requested"] + 1e-6


def test_rad_etilganda_tavsiya_nol(trained, dataset):
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = decide(feats, trained)
        if d.qaror == DECLINE:
            assert d.tavsiya_summa == 0


def test_maqullash_uchun_ball_chegarasi(trained, dataset):
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = decide(feats, trained)
        if d.qaror == APPROVE:
            assert d.score.score >= APPROVE_SCORE
        if d.score.score < REVIEW_SCORE:
            assert d.qaror == DECLINE


# --------------------------------------------------------------------------
# Reyting sifati
# --------------------------------------------------------------------------
def test_maqullanganlar_rad_etilganlardan_xavfsizroq(trained, dataset):
    """Biznes tekshiruvi: qaror haqiqiy natijalarni ajratishi kerak."""
    import csv
    from app.config import DATA_DIR
    key_path = DATA_DIR / "_javob_kaliti" / "test_natijalari.csv"
    if not key_path.exists():
        pytest.skip("javob kaliti yo'q")
    with key_path.open(encoding="utf-8") as fh:
        key = {r["application_id"]: r["haqiqiy_natija"] for r in csv.DictReader(fh)}

    guruh = {APPROVE: [], REVIEW: [], DECLINE: []}
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = decide(feats, trained)
        guruh[d.qaror].append(1 if key[app["application_id"]] == "defolt" else 0)

    rate = {k: (sum(v) / len(v) if v else None) for k, v in guruh.items()}
    assert rate[APPROVE] is not None and rate[DECLINE] is not None
    assert rate[APPROVE] < rate[DECLINE], rate
    if rate[REVIEW] is not None:
        assert rate[APPROVE] <= rate[REVIEW] <= rate[DECLINE], rate


def test_auc_minimal_chegaradan_yuqori(trained, dataset):
    """Regressiya qo'riqchisi: model sifati tushib ketmasin."""
    import csv
    from app.config import DATA_DIR
    from app.model import auc_roc
    key_path = DATA_DIR / "_javob_kaliti" / "test_natijalari.csv"
    if not key_path.exists():
        pytest.skip("javob kaliti yo'q")
    with key_path.open(encoding="utf-8") as fh:
        key = {r["application_id"]: r["haqiqiy_natija"] for r in csv.DictReader(fh)}
    y, p = [], []
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        y.append(1 if key[app["application_id"]] == "defolt" else 0)
        p.append(trained.score(feats).pd)
    assert auc_roc(y, p) > 0.70


# --------------------------------------------------------------------------
# Mijozga qaratilgan izoh (app/explain.py)
# --------------------------------------------------------------------------
def test_mijoz_izohi_har_doim_toliq(trained, dataset):
    """Har bir test arizasida sodda izoh ham, amaliy maslahat ham bo'lsin."""
    from app.decision import decide as _decide
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        e = _decide(feats, trained).mijoz_izohi()
        assert e["sarlavha"].strip()
        assert e["bosh_gap"].strip()
        assert e["keyingi_qadam"], app["application_id"]
        assert all(s.strip() for s in e["keyingi_qadam"])


def test_mijoz_izohida_jargon_yoq(trained, dataset):
    """Mijoz matnida texnik atamalar ("DTI", "WOE", "PD", "shift") bo'lmasin."""
    from app.decision import decide as _decide
    taqiqlangan = ("DTI", "PTI", "WOE", "IV ", "PD ", "shift", "scorecard",
                   "binning", "beta", "logit")
    for app in dataset.test()[:150]:
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        e = _decide(feats, trained).mijoz_izohi()
        matn = " ".join([e["bosh_gap"]]
                        + [x["matn"] for x in e["yordam_berdi"]]
                        + [x["matn"] for x in e["tosqinlik_qildi"]]
                        + e["keyingi_qadam"])
        for term in taqiqlangan:
            assert term not in matn, f"{app['application_id']}: '{term}' -> {matn}"


def test_har_bir_belgi_uchun_inson_ifodasi_bor(trained):
    """FEATURE_SPEC ga yangi belgi qo'shilsa, matni ham qo'shilishi shart."""
    from app.explain import HUMAN
    from app.scorecard import FEATURE_SPEC
    yoq = [k for k, _, _, _ in FEATURE_SPEC if k not in HUMAN]
    assert yoq == [], f"inson tilidagi ifoda yozilmagan belgilar: {yoq}"
    for key, tmpl in HUMAN.items():
        assert set(tmpl) == {"+", "-"}, key


def test_rad_etilganda_maslahat_amaliy(trained, dataset):
    """Rad javobi «yo'q» bilan tugamasin — nima qilish kerakligi aytilsin."""
    from app.decision import DECLINE, decide as _decide
    korildi = 0
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        d = _decide(feats, trained)
        if d.qaror != DECLINE:
            continue
        korildi += 1
        e = d.mijoz_izohi()
        assert e["keyingi_qadam"]
        assert e["tosqinlik_qildi"], "rad sababi omil bilan ko'rsatilishi kerak"
    assert korildi > 0


def test_mijoz_sababi_csv_uchun_bir_qatorda(trained, dataset):
    from app.decision import decide as _decide
    for app in dataset.test()[:50]:
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        s = _decide(feats, trained).mijoz_sababi()
        assert s.strip() and "\n" not in s and len(s) > 60
