"""Mijozga qaratilgan matn qatlami (app/explain.py).

Bu fayldagi testlarning aksariyati — REGRESSIYA qulflari. Har biri ko'p
agentli auditda topilgan va o'lchangan aniq nuqsonga bog'langan: matn
qatlami jim buziladi (kod ishlaydi, testlar yashil), lekin mijoz noto'g'ri
yoki huquqiy jihatdan xavfli jumlani o'qiydi.
"""
import math

import pytest

from app.config import ANNUAL_RATE
from app.decision import APPROVE, DECLINE, REVIEW, decide
from app.explain import (CLIENT_VISIBLE, HUMAN, MIN_CLIENT_POINTS,
                         client_explanation, client_sentence, foiz, oy,
                         recommended_payment, som)
from app.features import annuity_payment, build_features
from app.scorecard import FEATURE_SPEC


@pytest.fixture(scope="module")
def qarorlar(dataset, trained):
    """Barcha test arizalari bo'yicha (belgilar, qaror) juftliklari."""
    out = []
    for app in dataset.test():
        feats = build_features(app, dataset.profile(app["applicant_id"]))
        out.append((feats, decide(feats, trained)))
    return out


# ---------------------------------------------------------------------------
# Formatlash
# ---------------------------------------------------------------------------
def test_som_ming_ajratgich():
    assert som(1234567) == "1 234 567 so'm"
    assert som(0) == "0 so'm"


def test_oy_yilga_aylantiradi():
    assert oy(6) == "6 oy"
    assert oy(24) == "2 yil"
    assert oy(30) == "2 yil 6 oy"


def test_foiz():
    assert foiz(0.527, 1) == "52.7%"


# ---------------------------------------------------------------------------
# To'liqlik
# ---------------------------------------------------------------------------
def test_har_bir_modeldagi_belgi_uchun_matn_bor():
    """FEATURE_SPEC ga belgi qo'shilsa, inson tilidagi ifodasi ham kerak."""
    yoq = [k for k, _, _, _ in FEATURE_SPEC if k not in HUMAN]
    assert yoq == [], f"matn yozilmagan belgilar: {yoq}"


def test_har_bir_matnda_ikkala_ishora_bor():
    for key, tmpl in HUMAN.items():
        assert set(tmpl) == {"+", "-"}, key


def test_client_visible_faqat_mavjud_belgilardan_iborat():
    nomalum = CLIENT_VISIBLE - set(HUMAN)
    assert nomalum == set(), f"HUMAN da yo'q kalitlar: {nomalum}"


# ---------------------------------------------------------------------------
# REGRESSIYA 1.1 — yosh va ma'lumot mijoz matniga tushmasin
# ---------------------------------------------------------------------------
def test_yosh_mijoz_matnida_ishlatilmaydi(qarorlar):
    """Yoshga ko'ra kamsitish sifatida o'qiladigan jumla bo'lmasin.

    Regressiya: `client_explanation` barcha omillarni ko'rsatar edi va
    540 qarordan 234 tasida mijoz "25 yosh guruhida to'lovni kechiktirish
    ko'proq uchraydi" degan jumlani o'qirdi. Yosh endi reyting omili ham
    emas (FEATURE_SPEC dan olib tashlangan), lekin qaytib qo'shilsa ham
    mijoz qatlamiga chiqmasligi kerak.
    """
    for feats, d in qarorlar:
        e = client_explanation(d)
        matn = " ".join(x["matn"] for x in e["yordam_berdi"] + e["tosqinlik_qildi"])
        assert "yosh" not in matn.lower(), feats["application_id"]


def test_nozik_belgilar_client_visible_da_yoq():
    for himoyalangan in ("yosh", "talim", "jins", "viloyat"):
        assert himoyalangan not in CLIENT_VISIBLE


def test_shovqin_chegarasi_hurmat_qilinadi(qarorlar):
    """±2 balldan kichik omil mijozni chalg'itadi — ko'rsatilmaydi."""
    for _, d in qarorlar:
        e = client_explanation(d)
        for x in e["yordam_berdi"] + e["tosqinlik_qildi"]:
            if x["ball"] != 0.0:                       # 0.0 = zaxira matn
                assert abs(x["ball"]) >= MIN_CLIENT_POINTS


# ---------------------------------------------------------------------------
# REGRESSIYA 1.2 — "deklaratsiyadan farq qiladi" faqat haqiqatan farq bo'lsa
# ---------------------------------------------------------------------------
def test_daromad_farqi_yolgon_aytilmaydi(qarorlar):
    """Regressiya: shablon WOE bucket ishorasiga qarab tanlanar edi, natijada
    daromadi tasdiqlangan mijozga ham "farq qiladi" deyilardi (100 arizadan
    38 tasi, hammasida |gap - 1| < 0.15)."""
    for feats, d in qarorlar:
        e = client_explanation(d)
        matn = " ".join(x["matn"] for x in e["yordam_berdi"] + e["tosqinlik_qildi"])
        if "sezilarli farq qiladi" in matn:
            assert abs(feats["income_gap"] - 1.0) >= 0.15, feats["application_id"]


# ---------------------------------------------------------------------------
# REGRESSIYA 1.3 — oylik to'lov TAVSIYA etilgan summaga mos bo'lsin
# ---------------------------------------------------------------------------
def test_oylik_tolov_tavsiyaga_mos(qarorlar):
    """Regressiya: `raqamlar.oylik_tolov` so'ralgan summadan hisoblanar,
    `raqamlar.tavsiya` esa kamaytirilgan bo'lardi. UI da ular yonma-yon
    turadi — 540 dan 131 tasi qarama-qarshi ko'rinardi."""
    tekshirildi = 0
    for feats, d in qarorlar:
        if d.tavsiya_summa <= 0:
            continue
        tekshirildi += 1
        kutilgan = annuity_payment(d.tavsiya_summa, ANNUAL_RATE,
                                   feats["term_months"])
        assert d.mijoz_izohi()["raqamlar"]["oylik_tolov"] == pytest.approx(
            round(kutilgan), abs=1)
    assert tekshirildi > 0


def test_rad_etilganda_tolov_nol(qarorlar):
    for _, d in qarorlar:
        if d.qaror == DECLINE:
            assert recommended_payment(d) == 0.0
            assert d.mijoz_izohi()["raqamlar"]["oylik_tolov"] == 0


# ---------------------------------------------------------------------------
# REGRESSIYA 1.4 — bajarib bo'lmaydigan va'da berilmasin
# ---------------------------------------------------------------------------
def test_kafolat_vada_qilinmaydi(qarorlar):
    """Regressiya: "bu summa hozirdanoq ma'qullanadi" 55 arizada aytilar,
    ulardan 4 tasida qayta hisob baribir QOLDA_KORIB_CHIQISH berardi."""
    for _, d in qarorlar:
        for qadam in client_explanation(d)["keyingi_qadam"]:
            assert "hozirdanoq ma'qullanadi" not in qadam


# ---------------------------------------------------------------------------
# Mustahkamlik — matn qatlamidagi xato QARORNI buzmasligi kerak
# ---------------------------------------------------------------------------
def test_buzuq_belgilarda_ham_izoh_qaytadi(trained, dataset):
    """`_lead` va `next_steps` ichidagi kutilmagan qiymat oqimni yiqitmasin."""
    app = dataset.test()[0]
    feats = build_features(app, dataset.profile(app["applicant_id"]))
    d = decide(feats, trained)
    d.feats = {}                      # eng yomon holat: belgilar yo'q
    e = client_explanation(d)
    assert e["sarlavha"] and e["bosh_gap"] and e["keyingi_qadam"]


def test_notanish_belgi_texnik_nomga_tushadi(trained, dataset):
    from app.explain import humanize

    class Soxta:
        key, label, points = "yoq_bunaqa_belgi", "Texnik nom", -5.0

    assert humanize(Soxta(), {}) == "Texnik nom"


# ---------------------------------------------------------------------------
# Shartnoma: izoh hech qachon bo'sh emas
# ---------------------------------------------------------------------------
def test_har_bir_qarorda_toliq_izoh(qarorlar):
    for feats, d in qarorlar:
        e = client_explanation(d)
        assert e["sarlavha"].strip()
        assert e["bosh_gap"].strip()
        assert e["keyingi_qadam"] and all(s.strip() for s in e["keyingi_qadam"])
        assert e["ohang"] in {"ijobiy", "ogohlantirish", "salbiy"}


def test_rad_etilganda_sabab_omil_bilan(qarorlar):
    """Rad javobi hech qachon "shunchaki yo'q" bo'lmasin."""
    korildi = 0
    for _, d in qarorlar:
        if d.qaror != DECLINE:
            continue
        korildi += 1
        e = client_explanation(d)
        assert e["tosqinlik_qildi"], "rad sababi omil bilan ko'rsatilishi kerak"
        assert e["keyingi_qadam"]
    assert korildi > 0


def test_client_sentence_csv_uchun_yaroqli(qarorlar):
    for _, d in qarorlar[:80]:
        s = client_sentence(d)
        assert s.strip() and "\n" not in s and len(s) > 60


def test_raqamlar_izchil(qarorlar):
    for feats, d in qarorlar:
        r = client_explanation(d)["raqamlar"]
        assert r["soralgan"] == round(feats["requested"])
        assert r["tavsiya"] <= r["soralgan"] + 1
        assert all(math.isfinite(v) for v in r.values() if isinstance(v, (int, float)))
