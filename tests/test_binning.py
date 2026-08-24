"""WOE / IV binning testlari (bonus algoritm)."""
import math

import pytest

from app.binning import (Bin, FeatureBinning, fit_categorical, fit_numeric,
                         iv_strength)


def test_woe_ishorasi_togri():
    """Yuqori bad-rate bucket musbat WOE olishi shart."""
    values = list(range(200))
    # katta qiymatlar = yomon
    labels = [0] * 150 + [1] * 50
    fb = fit_numeric("x", values, labels)
    assert fb.bins[0].woe < fb.bins[-1].woe
    assert fb.iv > 0.3


def test_iv_foydasiz_belgida_kichik():
    values = list(range(400))
    labels = [i % 2 for i in range(400)]     # belgi bilan bog'liq emas
    fb = fit_numeric("shovqin", values, labels)
    assert fb.iv < 0.05
    assert iv_strength(fb.iv) in {"foydasiz", "kuchsiz"}


def test_konstanta_belgi_yagona_bin():
    fb = fit_numeric("k", [7] * 100, [0] * 90 + [1] * 10)
    assert len(fb.bins) == 1 and fb.iv == 0.0


def test_bosh_royxat():
    fb = fit_numeric("b", [], [])
    assert len(fb.bins) == 1
    assert fb.woe_of(123)[0] == 0.0


def test_cuts_override_diskret_belgida():
    """Kuzatuvlarning 80% i nolda: kvantil ma'noli segmentni yo'qotadi."""
    values = [0.0] * 800 + [15.0] * 100 + [95.0] * 100
    labels = [0] * 800 + [0] * 90 + [1] * 10 + [1] * 60 + [0] * 40
    fb = fit_numeric("kechikish", values, labels, cuts_override=[1.0, 30.0, 90.0])
    labels_seen = [b.label for b in fb.bins]
    assert ">= 90" in labels_seen           # 90+ segmenti saqlanib qoldi
    hi = [b for b in fb.bins if b.label == ">= 90"][0]
    assert hi.bad_rate > 0.5


def test_bin_chegaralari_yopiq_ochiq():
    """[lo, hi) — chegara qiymati yuqori binga tushadi, ikki marta emas."""
    b = Bin(lo=10, hi=20)
    assert b.contains(10) and not b.contains(20) and not b.contains(9.99)


def test_har_bir_qiymat_aniq_bitta_binga_tushadi():
    fb = fit_numeric("x", list(range(500)), [i % 3 == 0 for i in range(500)])
    for v in (-1e9, 0, 123, 499, 1e9):
        hits = [b for b in fb.bins if b.contains(v)]
        assert len(hits) == 1, f"{v} uchun {len(hits)} ta bin"


def test_kategorik_kam_uchraydiganlar_birlashtiriladi():
    values = ["a"] * 300 + ["b"] * 300 + ["nodir"] * 3
    labels = [0] * 280 + [1] * 20 + [0] * 250 + [1] * 50 + [1] * 3
    fb = fit_categorical("c", values, labels)
    # 3 ta kuzatuvli kategoriya alohida ekstremal WOE olmasligi kerak
    assert all(b.n >= 20 for b in fb.bins)


def test_korilmagan_kategoriya_neytral_woe():
    fb = fit_categorical("c", ["a"] * 100 + ["b"] * 100, [0] * 100 + [1] * 100)
    woe, _ = fb.woe_of("hech_qachon_korilmagan")
    assert woe == fb.default_woe == 0.0


def test_woe_chekli_son_har_doim():
    """Laplace tekislash: bucket'da 0 ta bad bo'lsa ham WOE cheksiz bo'lmaydi."""
    values = list(range(200))
    labels = [0] * 199 + [1]
    fb = fit_numeric("x", values, labels)
    assert all(math.isfinite(b.woe) for b in fb.bins)


def test_serializatsiya_aylanma():
    fb = fit_numeric("x", list(range(300)), [i > 150 for i in range(300)])
    again = FeatureBinning.from_dict(fb.to_dict())
    for v in (0, 77, 150, 299):
        assert again.woe_of(v)[0] == pytest.approx(fb.woe_of(v)[0])


def test_iv_strength_shkalasi():
    assert iv_strength(0.01) == "foydasiz"
    assert iv_strength(0.05) == "kuchsiz"
    assert iv_strength(0.2) == "o'rtacha"
    assert iv_strength(0.4) == "kuchli"
    assert iv_strength(0.9) == "juda kuchli"


def test_kichik_lekin_ajratuvchi_toifa_yutilmaydi(dataset, train_rows):
    """Regressiya testi: 'ishsiz' toifasi qo'shnisiga qo'shilib ketmasin.

    Kategoriyalar uchun NISBIY chegara (5%) qo'yilganida 79 kuzatuvli
    'ishsiz' toifasi (defolt ulushi 63% — eng kuchli kategorik signal)
    'kam uchraydigan' deb birlashtirilib yuborilardi va IV 0.54 lik belgi
    yo'qolardi (test AUC 0.7493 -> 0.7444). Absolyut chegara (30) buni
    saqlaydi.
    """
    rows, labels = train_rows
    fb = fit_categorical("bandlik", [r["bandlik"] for r in rows], labels)
    ishsiz = [b for b in fb.bins if b.categories and "ishsiz" in b.categories]
    assert len(ishsiz) == 1
    assert ishsiz[0].categories == {"ishsiz"}, "boshqa toifa bilan qo'shilib ketdi"
    assert ishsiz[0].bad_rate > 0.5
    assert ishsiz[0].woe > 2.0
    assert fb.iv > 0.4
