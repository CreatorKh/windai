"""Logistik regressiya va baholash metrikalari."""
import math
import random

import pytest

from app.model import (LogisticRegression, auc_roc, brier_score, gini,
                       ks_statistic, sigmoid)


def test_sigmoid_barqaror():
    assert sigmoid(0) == 0.5
    # Katta manfiy argument OverflowError bermaydi, 0.0 gacha kamayadi —
    # bu xavfsiz: pastki oqimda log(p) emas, softplus ishlatiladi va
    # IRLS vaznlari max(p(1-p), 1e-6) bilan pollanadi.
    assert sigmoid(-1000) == 0.0
    assert sigmoid(-40) < 1e-17
    assert sigmoid(1000) == pytest.approx(1.0)


def test_koeffitsientlarni_tiklaydi():
    rnd = random.Random(7)
    X = [[rnd.gauss(0, 1), rnd.gauss(0, 1)] for _ in range(4000)]
    y = [1 if rnd.random() < sigmoid(1.5 * a - 0.8 * b) else 0 for a, b in X]
    m = LogisticRegression(l2=0.01).fit(X, y)
    assert m.coef[0] == pytest.approx(1.5, abs=0.25)
    assert m.coef[1] == pytest.approx(-0.8, abs=0.25)
    assert m.converged


def test_toliq_ajralishda_portlamaydi():
    """Quasi-complete separation: demplashsiz Newton beta ni cheksizga uchiradi.

    Bu regressiya testi — line search qo'shilishidan oldin bu holatda
    koeffitsientlar ~100 gacha o'sib, bashoratlar to'yinib qolar va
    AUC 0.5 ga tushib ketardi.
    """
    X = [[float(i)] for i in range(-60, 60)]
    y = [0] * 60 + [1] * 60
    m = LogisticRegression(l2=1.0).fit(X, y)
    assert all(math.isfinite(c) for c in m.coef)
    assert abs(m.coef[0]) < 50
    assert auc_roc(y, [m.predict_proba(x) for x in X]) == 1.0


def test_kollinear_belgilar_bilan_yaqinlashadi():
    rnd = random.Random(3)
    base = [rnd.gauss(0, 1) for _ in range(1500)]
    X = [[b, b * 2 + 1e-6, rnd.gauss(0, 1)] for b in base]
    y = [1 if b > 0 else 0 for b in base]
    m = LogisticRegression(l2=1.0).fit(X, y)
    assert all(math.isfinite(c) for c in m.coef)


def test_bosh_toplam_xato_beradi():
    with pytest.raises(ValueError):
        LogisticRegression().fit([], [])


def test_hissalar_yigindisi_qaror_qiymatini_beradi():
    m = LogisticRegression().fit([[1.0, 2.0], [0.0, 1.0], [2.0, 0.0], [1.0, 1.0]],
                                 [1, 0, 1, 0], ["a", "b"])
    x = [0.7, 1.3]
    assert sum(m.contributions(x).values()) + m.intercept == \
        pytest.approx(m.decision_value(x))


def test_serializatsiya_aylanma():
    m = LogisticRegression().fit([[1.0], [2.0], [3.0], [4.0]], [0, 0, 1, 1], ["x"])
    again = LogisticRegression.from_dict(m.to_dict())
    assert again.predict_proba([2.5]) == pytest.approx(m.predict_proba([2.5]))


# ------------------------------------------------------------------ metrikalar
def test_auc_mukammal_va_teskari():
    y = [0, 0, 1, 1]
    assert auc_roc(y, [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert auc_roc(y, [0.9, 0.8, 0.2, 0.1]) == 0.0
    assert gini(y, [0.1, 0.2, 0.8, 0.9]) == 1.0


def test_auc_teng_ballarda_0_5():
    """Barcha ballar bir xil -> ajratish yo'q -> 0.5 (NaN emas)."""
    assert auc_roc([0, 1, 0, 1], [0.5] * 4) == 0.5


def test_auc_bitta_sinf():
    assert auc_roc([1, 1, 1], [0.2, 0.5, 0.9]) == 0.5


def test_ks_va_brier():
    y = [0, 0, 1, 1]
    assert ks_statistic(y, [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1.0)
    assert brier_score(y, [0.0, 0.0, 1.0, 1.0]) == 0.0
    assert brier_score([], []) == 0.0
