"""Binary search limit qidiruvi (bonus algoritm)."""
import pytest

from app.config import LIMIT_STEP, MAX_DTI, MAX_PTI
from app.limit import affordability, binding_constraint, max_limit


def test_topilgan_limit_cheklovlarni_buzmaydi():
    r = max_limit(income=5_000_000, existing_debt=500_000, term_months=24)
    a = affordability(r.limit, 5_000_000, 500_000, 24)
    assert a["dti"] <= MAX_DTI + 1e-9
    assert a["pti"] <= MAX_PTI + 1e-9
    assert a["free_cash"] >= 0


def test_bir_qadam_yuqorisi_allaqachon_buzadi():
    """Binary search MAKSIMALNI topganini isbotlaydi, shunchaki mos qiymatni emas."""
    income, debt, term = 5_000_000, 500_000, 24
    r = max_limit(income, debt, term)
    a = affordability(r.limit + LIMIT_STEP, income, debt, term)
    assert a["dti"] > MAX_DTI or a["pti"] > MAX_PTI


def test_brute_force_bilan_mos_keladi():
    """Kichik oraliqda to'liq qidiruv bilan solishtiramiz."""
    income, debt, term = 3_000_000, 200_000, 12
    r = max_limit(income, debt, term)
    best = 0.0
    amount = 0.0
    while amount <= 60_000_000:
        a = affordability(amount, income, debt, term)
        if a["dti"] <= MAX_DTI and a["pti"] <= MAX_PTI and a["free_cash"] >= 0:
            best = amount
        amount += LIMIT_STEP
    assert r.limit == pytest.approx(best, abs=LIMIT_STEP)


def test_logarifmik_iteratsiya_soni():
    """500 mln / 100k oraliq uchun ~13 iteratsiya yetarli (chiziqli emas)."""
    r = max_limit(10_000_000, 0, 36)
    assert r.iterations <= 20


def test_daromad_yoq_limit_nol():
    r = max_limit(0, 0, 12)
    assert r.limit == 0 and r.afford_limit == 0
    assert "daromad" in r.binding


def test_qarz_shiftdan_oshgan_limit_nol():
    r = max_limit(1_000_000, 900_000, 12)
    assert r.limit == 0
    assert "DTI" in r.binding


def test_limit_daromadga_monoton():
    prev = -1.0
    for income in (1_000_000, 2_000_000, 5_000_000, 10_000_000):
        cur = max_limit(income, 0, 24).limit
        assert cur >= prev
        prev = cur


def test_uzoq_muddat_kattaroq_limit():
    kam = max_limit(4_000_000, 0, 6).limit
    kop = max_limit(4_000_000, 0, 60).limit
    assert kop > kam


def test_qadam_nol_bolsa_xato():
    with pytest.raises(ValueError):
        max_limit(1_000_000, 0, 12, step=0)


def test_ball_darvozasi_otmasa_afford_saqlanadi():
    """Skorkarta hech qanday summada o'tkazmasa — to'lov qobiliyati limiti
    yo'qolmaydi, faqat `limit` nolga tushadi va bayroq qo'yiladi."""
    r = max_limit(5_000_000, 0, 24, score_fn=lambda amount: (100.0, 0.99))
    assert r.limit == 0
    assert r.afford_limit > 0
    assert r.score_gate_ok is False
    assert "skorkarta" in r.binding


def test_ball_darvozasi_otsa_afford_ga_teng():
    r = max_limit(5_000_000, 0, 24, score_fn=lambda amount: (999.0, 0.001))
    assert r.limit == r.afford_limit > 0
    assert r.score_gate_ok is True
    assert r.guard_steps == 0


def test_binding_constraint_matni():
    assert binding_constraint(0, 0, 12) == "daromad tasdiqlanmagan"
    assert "oshgan" in binding_constraint(1_000_000, 800_000, 12)
