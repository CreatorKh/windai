"""Uchdan-uchgacha (end-to-end) pipeline testi + natija fayli shartnomasi."""
import csv

import pytest

from app.config import DATA_DIR
from app.pipeline import COLUMNS, RESULT_NAME, run


@pytest.fixture(scope="module")
def natija(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pipeline")
    summary = run(version="v1", data_dir=DATA_DIR, db_path=tmp / "k.db",
                  out_dir=tmp / "natija", evaluate=True, quiet=True)
    with (tmp / "natija" / RESULT_NAME).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return summary, rows


def test_fayl_nomi_shartga_mos():
    """TZ: nomida "qaror", "score" yoki "decision" bo'lishi shart."""
    assert any(w in RESULT_NAME for w in ("qaror", "score", "decision"))


def test_barcha_test_arizalari_yozilgan(natija, dataset):
    _, rows = natija
    kutilgan = {a["application_id"] for a in dataset.test()}
    olingan = {r["application_id"] for r in rows}
    assert olingan == kutilgan, f"yetishmaydi: {sorted(kutilgan - olingan)[:5]}"


def test_majburiy_ustunlar_bor(natija):
    _, rows = natija
    assert set(COLUMNS).issubset(rows[0].keys())
    for col in ("application_id", "score", "pd"):
        assert col in rows[0]


def test_id_lar_takrorlanmaydi(natija):
    _, rows = natija
    ids = [r["application_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_pd_oraliqda_va_score_haqiqiy_son(natija):
    _, rows = natija
    for r in rows:
        pd = float(r["pd"])
        assert 0.0 <= pd <= 1.0
        assert 300.0 <= float(r["score"]) <= 900.0


def test_har_bir_satrda_sabab_bor(natija):
    _, rows = natija
    assert all(r["sabab"].strip() for r in rows)
    assert all(r["asosiy_omil"].strip() for r in rows)


def test_auc_javob_kaliti_boyicha(natija):
    summary, _ = natija
    rep = summary.get("baholash")
    if rep is None:
        pytest.skip("javob kaliti yo'q")
    assert rep["coverage"] == rep["n_key"]      # to'liq qamrov
    assert rep["auc"] > 0.70
    assert rep["gini"] > 0.40


def test_jurnal_zanjiri_butun(natija):
    summary, _ = natija
    assert summary["jurnal"]["butun"] is True
    assert summary["jurnal"]["tekshirildi"] == summary["n_test"]


def test_qaytariluvchanlik(tmp_path):
    """Bir xil kirish -> bir xil chiqish (deterministik model)."""
    def ballar(name):
        run(version="v1", data_dir=DATA_DIR, db_path=tmp_path / f"{name}.db",
            out_dir=tmp_path / name, evaluate=False, journal=False, quiet=True)
        with (tmp_path / name / RESULT_NAME).open(encoding="utf-8") as fh:
            return {r["application_id"]: r["score"] for r in csv.DictReader(fh)}
    assert ballar("a") == ballar("b")


def test_qarorlar_taqsimoti_maqbul(natija):
    """Hamma narsani rad etuvchi yoki hammaga ha deyuvchi model foydasiz."""
    summary, rows = natija
    n = len(rows)
    for qaror, cnt in summary["qarorlar"].items():
        assert cnt < n, f"barcha arizalar {qaror} bo'lib qoldi"
    assert summary["qarorlar"].get("MAQULLANDI", 0) >= n * 0.05
