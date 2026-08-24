"""MAJBURIY ALGORITM #1 va #2 uchun testlar."""
import math

import pytest

from app.features import (annuity_payment, cash_flow, dti_pti, loan_burden,
                          median, stdev, trimmed_mean)


# --------------------------------------------------------------- DTI / PTI
def test_dti_pti_oddiy_holat():
    r = dti_pti(monthly_income=5_000_000, existing_monthly_debt=1_000_000,
                new_payment=500_000)
    assert r["dti"] == pytest.approx(0.30)
    assert r["pti"] == pytest.approx(0.10)
    assert r["dti_current"] == pytest.approx(0.20)
    assert r["free_cash"] == pytest.approx(3_500_000)


def test_dti_nol_daromad_xavfsiz_qiymat_qaytaradi():
    """Chekka holat: daromad yo'q -> ZeroDivisionError emas, maksimal xavf."""
    r = dti_pti(0, 500_000, 100_000)
    assert r["dti"] == 1.0 and r["income_missing"] == 1.0
    assert math.isfinite(r["dti"])


def test_dti_manfiy_daromad_ham_himoyalangan():
    r = dti_pti(-100, 0, 0)
    assert r["income_missing"] == 1.0


def test_dti_manfiy_qarz_nolga_qisqartiriladi():
    r = dti_pti(1_000_000, -500_000, -100_000)
    assert r["dti"] == 0.0 and r["pti"] == 0.0


def test_dti_shiftlangan():
    """Juda katta yuk 5.0 da to'xtaydi — model uchun outlier bo'lmasin."""
    assert dti_pti(1_000, 10_000_000, 0)["dti"] == 5.0


# ------------------------------------------------------------------ annuitet
def test_annuitet_formulasi():
    # 12 mln, 24 oy, 28% yillik -> ~659k
    p = annuity_payment(12_000_000, 0.28, 24)
    assert 640_000 < p < 680_000
    # to'lovlar yig'indisi asosiy qarzdan katta bo'lishi shart
    assert p * 24 > 12_000_000


def test_annuitet_nol_stavka():
    assert annuity_payment(1_200_000, 0.0, 12) == pytest.approx(100_000)


def test_annuitet_nol_muddat():
    assert annuity_payment(500_000, 0.28, 0) == 500_000


# ----------------------------------------------------------------- cash-flow
def _flows(values):
    return [{"oy": f"m{i}", "kirim": v, "chiqim": v * 0.5,
             "naqd_yechish": v * 0.1, "oy_oxiri_qoldiq": v * 0.2}
            for i, v in enumerate(values)]


def test_cash_flow_median_va_cv():
    r = cash_flow(_flows([100, 100, 100, 100]))
    assert r["income_median"] == 100
    assert r["income_cv"] == 0.0            # o'zgarishsiz daromad
    assert r["burn_ratio"] == pytest.approx(0.5)
    assert r["cash_ratio"] == pytest.approx(0.1)


def test_cash_flow_cv_ozgaruvchan_daromadda_yuqori():
    barqaror = cash_flow(_flows([100] * 12))
    ozgaruvchan = cash_flow(_flows([20, 180, 30, 170, 40, 160,
                                    25, 175, 35, 165, 45, 155]))
    assert ozgaruvchan["income_cv"] > barqaror["income_cv"]
    assert ozgaruvchan["income_cv"] > 0.5


def test_cash_flow_bosh_tarix():
    """Chekka holat: oqim yo'q -> flows_missing va yuqori CV."""
    r = cash_flow([])
    assert r["flows_missing"] == 1.0
    assert r["income_median"] == 0.0
    assert r["income_cv"] == 1.5
    assert r["zero_months"] == 12.0


def test_cash_flow_nol_kirim_oylari_sanaladi():
    r = cash_flow(_flows([100, 0, 100, 0, 100, 0]))
    assert r["zero_months"] == 3.0


def test_cash_flow_trend():
    osayotgan = cash_flow(_flows([100, 100, 100, 200, 200, 200]))
    assert osayotgan["income_trend"] == pytest.approx(2.0)


def test_cash_flow_bitta_oy_stdev_bermaydi():
    """n < 2 -> stdev aniqlanmagan; CV 0 bo'lishi kerak, NaN emas."""
    r = cash_flow(_flows([100]))
    assert math.isfinite(r["income_cv"]) and r["income_cv"] == 0.0


# ------------------------------------------------------------- statistikalar
def test_median_juft_va_toq():
    assert median([1, 2, 3]) == 2
    assert median([1, 2, 3, 4]) == 2.5
    assert median([]) == 0.0


def test_stdev_kam_elementda_nol():
    assert stdev([]) == 0.0 and stdev([5]) == 0.0


def test_trimmed_mean_outlierni_kesadi():
    v = [10] * 10 + [10_000]
    assert trimmed_mean(v, 0.1) < sum(v) / len(v)


# ------------------------------------------------------------- kredit yuki
def test_loan_burden_faqat_faol_kreditlarni_sanaydi():
    loans = [
        {"bank": "A", "oylik_tolov": 100, "qoldiq": 1000, "status": "faol",
         "max_kechikish_kun": 15},
        {"bank": "B", "oylik_tolov": 900, "qoldiq": 5000, "status": "yopilgan",
         "max_kechikish_kun": 95},
    ]
    r = loan_burden(loans)
    assert r["active_payment"] == 100          # yopilgani hisoblanmaydi
    assert r["max_delinq"] == 95               # tarix esa hisoblanadi
    assert r["ever_delinq_90"] == 1.0
    assert r["bank_count"] == 2


def test_loan_burden_bosh_royxat():
    r = loan_burden([])
    assert r["has_credit_history"] == 0.0 and r["max_delinq"] == 0.0
