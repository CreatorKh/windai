"""CLI: skorkartani o'rgatadi, TEST arizalarni ballaydi, natija faylini yozadi.

    python -m app.pipeline                      # o'rgatish + natija/kredit_qarorlari.csv
    python -m app.pipeline --version v2 --l2 1  # boshqa versiya
    python -m app.pipeline --evaluate           # javob kaliti bilan solishtirish
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from . import db
from .config import DATA_DIR, DB_PATH, OUT_DIR
from .engine import CreditEngine
from .loaders import label_of
from .model import auc_roc, brier_score, gini, ks_statistic

RESULT_NAME = "kredit_qarorlari.csv"
# `sabab` — hakam QO'LDA o'qiydigan ustun, shuning uchun u inson tilida yoziladi.
# Texnik variant (foizlar, chegaralar, ball hissalari) alohida ustunda qoladi.
COLUMNS = ["application_id", "score", "pd", "qaror", "sabab", "sabab_texnik",
           "asosiy_omil", "tavsiya_summa", "limit", "dti", "pti", "income_cv",
           "scorecard_version"]


def run(version: str = "v1", l2: float = 3.0, data_dir: Path = DATA_DIR,
        db_path: Path = DB_PATH, out_dir: Path = OUT_DIR,
        evaluate: bool = False, journal: bool = True, quiet: bool = False) -> dict:
    t0 = time.time()
    log = (lambda *a: None) if quiet else (lambda *a: print(*a, flush=True))

    engine = CreditEngine(data_dir=data_dir, db_path=db_path, l2=l2)
    log(f"[1/4] Dataset: {len(engine.data.applications)} ariza, "
        f"{len(engine.data.train())} train / {len(engine.data.test())} test")

    # 2-kun stsenariysi: hakamlar `natija` ustuni BO'SH bo'lgan dataset berishi
    # mumkin. Bunda o'rgatish imkonsiz — bazadagi amaldagi (muzlatilgan) SCD2
    # versiyasi bilan faqat ballash rejimiga o'tamiz. Traceback bilan yiqilish
    # o'rniga natija fayli baribir yoziladi.
    if engine.data.train():
        sc = engine.train(version=version, izoh=f"pipeline, l2={l2}")
        m = sc.metrics
        log(f"[2/4] Skorkarta '{sc.version}': belgilar={len(sc.spec)}  "
            f"AUC(in-sample)={m['auc_in_sample']}  AUC(5-fold CV)={m['auc_cv']}  "
            f"KS={m['ks']}")
    else:
        sc = engine.ensure_scorecard(version=version)
        if sc is None or engine.version_id is None:
            log("XATO: o'quv to'plami bo'sh va bazada saqlangan skorkarta ham yo'q. "
                "Avval belgilangan (natija to'ldirilgan) dataset bilan bir marta "
                "ishga tushiring yoki DB_PATH orqali mavjud bazani ko'rsating.")
            return {"xato": "o'quv to'plami ham, saqlangan skorkarta ham yo'q",
                    "n_test": 0}
        m = sc.metrics
        log(f"[2/4] O'quv to'plami bo'sh — muzlatilgan skorkarta '{sc.version}' "
            f"bilan faqat ballash rejimi.")
    version = sc.version

    test_apps = engine.data.test()
    rows: List[dict] = []
    log(f"[3/4] {len(test_apps)} ta test arizasi ballanmoqda…")
    for app in test_apps:
        feats = engine.features_of(app)
        d = engine.decide(app, feats)
        if journal:
            engine.record(app, d, manba="dataset")
        top_neg = d.score.top_factors(1, sign=-1)
        rows.append({
            "application_id": app["application_id"],
            "score": round(d.score.score, 1),
            "pd": round(d.score.pd, 6),
            "qaror": d.qaror,
            "sabab": d.mijoz_sababi(),
            "sabab_texnik": d.sabab,
            "asosiy_omil": (f"{top_neg[0].label} ({top_neg[0].points:+.0f} ball)"
                            if top_neg else "salbiy omil yo'q"),
            "tavsiya_summa": round(d.tavsiya_summa),
            "limit": round(d.limit.limit),
            "dti": round(feats["dti"], 4),
            "pti": round(feats["pti"], 4),
            "income_cv": round(feats["income_cv"], 4),
            "scorecard_version": version,
        })

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / RESULT_NAME
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    log(f"[4/4] Yozildi: {out_path}  ({len(rows)} satr)")

    summary = {
        "version": version, "n_test": len(rows), "out": str(out_path),
        "metrics": m, "sekund": round(time.time() - t0, 2),
        "qarorlar": _count(rows, "qaror"),
    }

    if evaluate:
        rep = evaluate_against_key(rows, data_dir)
        summary["baholash"] = rep
        if rep:
            # UI "CV AUC 0.7959" ni ko'rsatadi, hakam esa holdout AUC ni so'raydi.
            # Ikkalasi ham ekranda bo'lishi uchun natijani faylga yozamiz.
            rep_out = dict(rep, version=version,
                           qarorlar=_count(rows, "qaror"),
                           qaror_sifati=_decision_quality(rows, data_dir))
            (out_dir / "metrikalar.json").write_text(
                json.dumps(rep_out, ensure_ascii=False, indent=2), encoding="utf-8")
        if rep:
            log(f"\n=== JAVOB KALITI BILAN TEKSHIRUV ===")
            log(f"  AUC-ROC : {rep['auc']}")
            log(f"  Gini    : {rep['gini']}")
            log(f"  KS      : {rep['ks']}")
            log(f"  Brier   : {rep['brier']}")
            log(f"  Shift (haqiqiy PD ning AUC si): {rep['ceiling_auc']}")
            log(f"  Qamrov  : {rep['coverage']}/{rep['n_key']} test arizasi")

    chain = db.verify_chain(engine.conn)
    summary["jurnal"] = chain
    log(f"\nJurnal zanjiri: {'BUTUN' if chain['butun'] else 'BUZILGAN'} "
        f"({chain['tekshirildi']} yozuv)")
    return summary


def _decision_quality(rows: List[dict], data_dir: Path) -> Optional[dict]:
    """Har bir qaror toifasi bo'yicha HAQIQIY defolt ulushi.

    Bu — modelning emas, QARORNING sifati: hakam aynan shuni so'raydi
    ("ma'qullaganlaringiz rostdan xavfsizroqmi?").
    """
    key_path = Path(data_dir) / "_javob_kaliti" / "test_natijalari.csv"
    if not key_path.exists():
        return None
    with key_path.open(encoding="utf-8") as fh:
        key = {r["application_id"]: r["haqiqiy_natija"] for r in csv.DictReader(fh)}
    grouped: Dict[str, List[int]] = {}
    for r in rows:
        k = key.get(r["application_id"])
        if k is None:
            continue
        grouped.setdefault(r["qaror"], []).append(1 if k == "defolt" else 0)
    return {q: {"n": len(v), "defolt": round(sum(v) / len(v), 4)}
            for q, v in grouped.items()}


def _count(rows: List[dict], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for r in rows:
        out[r[key]] = out.get(r[key], 0) + 1
    return out


def evaluate_against_key(rows: List[dict], data_dir: Path = DATA_DIR) -> Optional[dict]:
    """Ochiq datasetdagi javob kaliti bilan o'zini tekshirish."""
    key_path = Path(data_dir) / "_javob_kaliti" / "test_natijalari.csv"
    if not key_path.exists():
        return None
    with key_path.open(encoding="utf-8") as fh:
        key = {r["application_id"]: r for r in csv.DictReader(fh)}

    y, p, true_pd = [], [], []
    for r in rows:
        k = key.get(r["application_id"])
        if not k:
            continue
        y.append(1 if k["haqiqiy_natija"] == "defolt" else 0)
        p.append(float(r["pd"]))
        true_pd.append(float(k["haqiqiy_pd"]))

    if len(set(y)) < 2:
        return None
    return {
        "auc": round(auc_roc(y, p), 4),
        "gini": round(gini(y, p), 4),
        "ks": round(ks_statistic(y, p), 4),
        "brier": round(brier_score(y, p), 5),
        "ceiling_auc": round(auc_roc(y, true_pd), 4),
        "coverage": len(y), "n_key": len(key),
        "defolt_ulushi": round(sum(y) / len(y), 4),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Kredit skoring dvigateli — batch")
    ap.add_argument("--version", default="v1", help="skorkarta versiyasi nomi")
    ap.add_argument("--l2", type=float, default=3.0, help="L2 regulyarizatsiya")
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--db", type=Path, default=DB_PATH)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--evaluate", action="store_true",
                    help="javob kaliti bilan AUC hisoblash")
    ap.add_argument("--no-journal", action="store_true",
                    help="qarorlarni bazaga yozmaslik")
    ap.add_argument("--json", action="store_true", help="xulosani JSON da chiqarish")
    a = ap.parse_args(argv)

    s = run(version=a.version, l2=a.l2, data_dir=a.data_dir, db_path=a.db,
            out_dir=a.out_dir, evaluate=a.evaluate, journal=not a.no_journal,
            quiet=a.json)
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
