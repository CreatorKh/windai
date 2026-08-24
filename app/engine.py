"""Xizmat qatlami: datasetni yuklaydi, skorkartani o'rgatadi/versiyalaydi,
arizalarni ballaydi va qarorni jurnalga yozadi.

API ham, CLI (pipeline) ham shu sinfdan foydalanadi — biznes mantiq bir joyda.
"""
from __future__ import annotations

import json
import random
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from . import db
from .config import DATA_DIR, DB_PATH, RANDOM_SEED
from .decision import Decision, decide
from .graph import GraphBuilder
from .features import build_features, cash_flow, loan_burden
from .loaders import Dataset, label_of
from .model import auc_roc, brier_score, gini, ks_statistic
from .scorecard import Scorecard


class CreditEngine:
    """Yagona kirish nuqtasi (facade). Thread-safe: yozuvlar lock ostida."""

    def __init__(self, data_dir: Path = DATA_DIR, db_path: Path = DB_PATH,
                 l2: float = 3.0):
        self.data = Dataset(data_dir)
        # Oqimga bog'langan ulanishlar — sabab uchun app/db.py::Database ga qarang.
        self._db = db.Database(db_path)
        self.l2 = l2
        self._lock = self._db.write_lock
        self.scorecard: Optional[Scorecard] = None
        self._portfolio_cache = (None, None)
        self.version_id: Optional[int] = None
        self._cache: Dict[int, Scorecard] = {}
        self.graph = GraphBuilder(self)

    @property
    def conn(self):
        """Joriy oqimning sqlite ulanishi."""
        return self._db.conn

    # -- o'rgatish / yuklash --------------------------------------------------
    def ensure_scorecard(self, version: str = "v1", retrain: bool = False,
                         izoh: str = "") -> Optional[Scorecard]:
        """Amaldagi versiyani bazadan oladi; bo'lmasa (yoki retrain) o'rgatadi.

        Bazada ham versiya yo'q va o'quv to'plami ham bo'sh bo'lsa `None`
        qaytaradi — chaqiruvchi buni aniq xabar bilan qayta ishlaydi
        (`ValueError` traceback o'rniga).
        """
        if not retrain:
            row = db.current_version(self.conn)
            if row is not None:
                self.scorecard = Scorecard.from_dict(json.loads(row["payload"]))
                self.version_id = row["id"]
                self._cache[row["id"]] = self.scorecard
                return self.scorecard
        if not self.data.train():
            return None
        return self.train(version=version, izoh=izoh)

    def train(self, version: str = "v1", izoh: str = "",
              spec=None, l2: Optional[float] = None) -> Scorecard:
        """Train qismida skorkartani o'rgatadi va yangi SCD2 versiya ochadi."""
        train_apps = self.data.train()
        rows = [self.features_of(a) for a in train_apps]
        labels = [label_of(a) for a in train_apps]
        sc = Scorecard.fit(rows, labels, version=version, spec=spec,
                           l2=self.l2 if l2 is None else l2)
        sc.metrics = self.evaluate(sc, rows, labels)
        with self._lock:
            self.version_id = db.save_scorecard(
                self.conn, version, sc.to_dict(), sc.metrics, izoh)
            # Nom band bo'lsa baza `v2#3` kabi suffiks bilan saqlaydi — UI
            # chip "v2" ko'rsatib, jurnal "v2#3" yozmasin: nomni qaytarib olamiz.
            row = db.get_version(self.conn, self.version_id)
            if row is not None:
                sc.version = row["version"]
            self.scorecard = sc
            self._cache[self.version_id] = sc
            self.graph.invalidate()      # WOE fazosi o'zgardi — qo'shnilar ham
        return sc

    # -- baholash -------------------------------------------------------------
    def evaluate(self, sc: Scorecard, rows: List[dict],
                 labels: List[int], folds: int = 5) -> dict:
        """In-sample + K-fold cross-validation metrikalari."""
        pds = [sc.score(r).pd for r in rows]
        rnd = random.Random(RANDOM_SEED)
        idx = list(range(len(rows)))
        rnd.shuffle(idx)
        cv_auc: List[float] = []
        for i in range(folds):
            te = set(idx[i::folds])
            tr = [j for j in idx if j not in te]
            if not te or len(set(labels[j] for j in tr)) < 2:
                continue
            fold_sc = Scorecard.fit([rows[j] for j in tr], [labels[j] for j in tr],
                                    l2=self.l2)
            cv_auc.append(auc_roc([labels[j] for j in te],
                                  [fold_sc.score(rows[j]).pd for j in te]))
        return {
            "n_train": len(rows),
            "defolt_ulushi": round(sum(labels) / len(labels), 4) if labels else 0.0,
            "auc_in_sample": round(auc_roc(labels, pds), 4),
            "gini_in_sample": round(gini(labels, pds), 4),
            "ks": round(ks_statistic(labels, pds), 4),
            "brier": round(brier_score(labels, pds), 5),
            "auc_cv": round(sum(cv_auc) / len(cv_auc), 4) if cv_auc else None,
            "cv_folds": [round(a, 4) for a in cv_auc],
            "belgilar": [k for k, _, _, _ in sc.spec],
        }

    # -- belgilar -------------------------------------------------------------
    def features_of(self, application: dict) -> dict:
        return build_features(application,
                              self.data.profile(application["applicant_id"]))

    def features_from_form(self, form: dict) -> Tuple[dict, dict]:
        """Veb-formadan kelgan xom ma'lumot -> (ariza, belgilar).

        Mavjud mijoz tanlansa — bank oqimi va kreditlar datasetdan olinadi.
        Yangi mijoz bo'lsa — forma qiymatlaridan sintetik profil quriladi.
        """
        applicant_id = (form.get("applicant_id") or "").strip()
        # ID jarayon xotirasidagi hisoblagichdan EMAS, global noyob qiymatdan
        # olinadi. Aks holda server qayta ishga tushgach nomerlash noldan
        # boshlanadi va `upsert_application` boshqa odamning arizasini ustidan
        # yozadi — o'zgarmas audit izi da'vosi shu yerda buzilardi.
        app_id = form.get("application_id") or (
            f"WEB{datetime.now(timezone.utc):%y%m%d}{uuid.uuid4().hex[:6].upper()}")

        application = {
            "application_id": app_id,
            "applicant_id": applicant_id or app_id,
            "ariza_sana": form.get("ariza_sana", ""),
            "sorlgan_summa": float(form.get("sorlgan_summa") or 0),
            "maqsad": form.get("maqsad") or "iste'mol",
            "muddat_oy": float(form.get("muddat_oy") or 12) or 12,
            "mavjud_oylik_yuk": float(form.get("mavjud_oylik_yuk") or 0),
            "natija": "",
        }

        if applicant_id and applicant_id in self.data.applicants:
            profile = self.data.profile(applicant_id)
        else:
            profile = self._synthetic_profile(form, application)

        return application, build_features(application, profile)

    def _synthetic_profile(self, form: dict, application: dict) -> dict:
        """Forma qiymatlaridan 12 oylik oqim va kredit ro'yxatini yasaydi."""
        income = float(form.get("oylik_daromad") or 0)
        expense = float(form.get("oylik_chiqim") or income * 0.6)
        cash = float(form.get("naqd_yechish") or 0)
        balance = float(form.get("oy_oxiri_qoldiq") or max(0.0, income - expense))
        series = form.get("kirim_seriya")           # ixtiyoriy: 12 ta qiymat

        flows = []
        if isinstance(series, list) and series:
            for i, v in enumerate(series[:12]):
                try:
                    inc = float(v)
                except (TypeError, ValueError):
                    inc = income
                flows.append({"oy": f"m{i+1:02d}", "kirim": inc,
                              "chiqim": expense, "naqd_yechish": cash,
                              "oy_oxiri_qoldiq": balance})
        else:
            for i in range(12):
                flows.append({"oy": f"m{i+1:02d}", "kirim": income,
                              "chiqim": expense, "naqd_yechish": cash,
                              "oy_oxiri_qoldiq": balance})

        loans = []
        n_loans = int(float(form.get("mavjud_kredit_soni") or 0))
        payment = float(form.get("mavjud_oylik_yuk") or 0)
        delinq = float(form.get("max_kechikish_kun") or 0)
        balance_left = float(form.get("kredit_qoldigi") or payment * 12)
        for i in range(max(0, n_loans)):
            loans.append({
                "loan_id": f"F{i+1}", "bank": f"BANK-{i+1:02d}",
                "summa": balance_left / max(1, n_loans),
                "muddat_oy": 12, "oylik_tolov": payment / max(1, n_loans),
                "qoldiq": balance_left / max(1, n_loans),
                "max_kechikish_kun": delinq if i == 0 else 0.0,
                "status": "faol",
            })

        applicant = {
            "applicant_id": application["applicant_id"],
            "ism": form.get("ism", ""),
            "jins": form.get("jins", ""),
            "yosh": int(float(form.get("yosh") or 0)),
            "viloyat": form.get("viloyat", "Toshkent"),
            "bandlik": form.get("bandlik") or "xususiy",
            "ish_staji_oy": float(form.get("ish_staji_oy") or 0),
            "deklaratsiya_daromad": float(form.get("deklaratsiya_daromad") or income),
            "oila_azolari": int(float(form.get("oila_azolari") or 1)),
            "talim": form.get("talim") or "orta",
            "mijoz_boldi_oy": float(form.get("mijoz_boldi_oy") or 0),
        }
        return {"applicant": applicant, "flows": flows, "loans": loans}

    # -- qaror ----------------------------------------------------------------
    def decide(self, application: dict, feats: dict,
               scorecard: Optional[Scorecard] = None) -> Decision:
        sc = scorecard or self.scorecard
        if sc is None:
            raise RuntimeError("skorkarta o'rgatilmagan")
        profile = (self.data.profile(application["applicant_id"])
                   if application["applicant_id"] in self.data.applicants else None)

        def rebuild(amount: float) -> dict:
            """Limit qidiruvi uchun: boshqa summada belgilarni qayta quramiz."""
            alt = dict(application)
            alt["sorlgan_summa"] = amount
            if profile is not None:
                return build_features(alt, profile)
            return build_features(alt, self._profile_from_feats(feats, alt))

        return decide(feats, sc, rebuild_features=rebuild)

    def _profile_from_feats(self, feats: dict, application: dict) -> dict:
        """Sintetik arizalar uchun profilni belgilardan qayta yig'ish."""
        income = feats.get("income_median", 0.0)
        return {
            "applicant": {
                "applicant_id": application["applicant_id"], "ism": "",
                "jins": "", "yosh": feats.get("yosh", 0),
                "viloyat": feats.get("viloyat", ""),
                "bandlik": feats.get("bandlik", "xususiy"),
                "ish_staji_oy": feats.get("ish_staji_oy", 0.0),
                "deklaratsiya_daromad": feats.get("declared_income", income),
                "oila_azolari": int(feats.get("oila_azolari", 1)),
                "talim": feats.get("talim", "orta"),
                "mijoz_boldi_oy": feats.get("mijoz_boldi_oy", 0.0),
            },
            "flows": [{"oy": f"m{i+1:02d}", "kirim": income,
                       "chiqim": income * feats.get("burn_ratio", 0.6),
                       "naqd_yechish": income * feats.get("cash_ratio", 0.0),
                       "oy_oxiri_qoldiq": 0.0} for i in range(12)],
            "loans": [{"loan_id": "S1", "bank": "BANK", "summa": 0.0,
                       "muddat_oy": 12,
                       "oylik_tolov": income * feats.get("dti_current", 0.0),
                       "qoldiq": feats.get("balance_to_income", 0.0) * income * 12,
                       "max_kechikish_kun": feats.get("max_delinq", 0.0),
                       "status": "faol"}] if feats.get("dti_current", 0) > 0 else [],
        }

    def record(self, application: dict, decision: Decision,
               manba: str = "web", kim: str = "tizim") -> int:
        """Arizani va qarorni bazaga yozadi (jurnal — faqat qo'shish).

        `kim` — qarorni chiqargan xodim login i (audit izi uchun).
        """
        with self._lock:
            db.upsert_application(self.conn, application, manba)
            return db.append_decision(self.conn, decision, self.version_id, kim=kim)

    # -- mijoz kartasi --------------------------------------------------------
    def client_card(self, applicant_id: str) -> Optional[dict]:
        """Mijozning 360° kesimi: shaxsiy ma'lumot, oqim, kreditlar, arizalar.

        Bank xodimi ekranni ochgan zahoti javob berishi kerak bo'lgan savollar:
        kim bu, qancha topadi, qancha qarzi bor, to'lov intizomi qanday,
        oldin nima so'ragan va nima olgan.

        Big-O: O(m + k + a) — oylar, kreditlar va arizalar soni bo'yicha
        chiziqli; barchasi allaqachon xotirada indekslangan.
        """
        applicant = self.data.applicants.get(applicant_id)
        if applicant is None:
            return None

        flows = self.data.flows.get(applicant_id, [])
        loans = self.data.loans.get(applicant_id, [])
        apps = [a for a in self.data.applications
                if a["applicant_id"] == applicant_id]

        cf = cash_flow(flows)
        lb = loan_burden(loans)
        income = cf["income_median"] or applicant.get("deklaratsiya_daromad", 0.0)

        # Har bir ariza uchun jurnal tarixini ham qo'shamiz.
        arizalar = []
        for a in apps:
            tarix = db.decision_history(self.conn, a["application_id"])
            arizalar.append({
                **a,
                "qaror": tarix[-1]["qaror"] if tarix else None,
                "ball": round(tarix[-1]["ball"], 1) if tarix else None,
                "sabab": tarix[-1]["sabab"] if tarix else None,
                "qaror_soni": len(tarix),
            })
        arizalar.sort(key=lambda r: r.get("ariza_sana", ""), reverse=True)

        return {
            "applicant": applicant,
            "oqim": flows,
            "kreditlar": loans,
            "arizalar": arizalar,
            "korsatkichlar": {
                "daromad_median": round(cf["income_median"]),
                "daromad_cv": round(cf["income_cv"], 4),
                "daromad_trendi": round(cf["income_trend"], 3),
                "sarf_ulushi": round(cf["burn_ratio"], 4),
                "naqd_ulushi": round(cf["cash_ratio"], 4),
                "zaxira_oy": round(cf["buffer_months"], 2),
                "nol_oylar": int(cf["zero_months"]),
                "mavjud_oylik_tolov": round(lb["active_payment"]),
                "faol_kreditlar": int(lb["active_count"]),
                "yopilgan_kreditlar": int(lb["closed_count"]),
                "qarz_qoldigi": round(lb["total_balance"]),
                "max_kechikish": lb["max_delinq"],
                "banklar_soni": int(lb["bank_count"]),
                "mavjud_dti": round(lb["active_payment"] / income, 4) if income else None,
                "jon_boshiga": round(income / max(1, applicant.get("oila_azolari", 1))),
            },
        }

    # -- portfel tahlili ------------------------------------------------------
    def portfolio(self, bins: int = 12) -> dict:
        """Portfel darajasidagi kesim: ball taqsimoti va bandlar sifati.

        `band_sifati` — eng muhim jadval: o'quv to'plamining HAQIQIY natijalari
        bo'yicha har bir ball oralig'ida defolt ulushi. Bu skorkarta
        ishlayotganini bitta rasmda isbotlaydi (ball oshgani sari defolt
        ulushi monoton kamayishi kerak).

        Big-O: O(n) — o'quv arizalari bo'yicha bir marta yurish. Natija
        keshlanadi, chunki skorkarta o'zgarmaguncha o'zgarmaydi.
        """
        sc = self.scorecard
        if sc is None:
            return {}
        cache_key = (id(sc), bins)
        if getattr(self, "_portfolio_cache", (None,))[0] == cache_key:
            return self._portfolio_cache[1]

        train_apps = self.data.train()
        rows = [(self.score_of(a), label_of(a)) for a in train_apps]
        scores = [s for s, _ in rows]
        lo, hi = min(scores), max(scores)
        span = max(hi - lo, 1.0)
        width = span / bins

        hist = []
        for i in range(bins):
            b_lo = lo + i * width
            b_hi = b_lo + width if i < bins - 1 else hi + 1e-9
            grp = [y for s, y in rows if b_lo <= s < b_hi]
            hist.append({
                "lo": round(b_lo), "hi": round(b_hi), "n": len(grp),
                "defolt": round(sum(grp) / len(grp), 4) if grp else None,
            })

        # Siyosat chegaralari bo'yicha kesim — hakam uchun eng o'qiladigan shakl.
        from .config import APPROVE_SCORE, REVIEW_SCORE
        bands = [("< " + str(int(REVIEW_SCORE)), -1e9, REVIEW_SCORE),
                 (f"{int(REVIEW_SCORE)}–{int(APPROVE_SCORE)}", REVIEW_SCORE, APPROVE_SCORE),
                 (">= " + str(int(APPROVE_SCORE)), APPROVE_SCORE, 1e9)]
        band_sifati = []
        for nom, b_lo, b_hi in bands:
            grp = [y for s, y in rows if b_lo <= s < b_hi]
            band_sifati.append({
                "nom": nom, "n": len(grp),
                "defolt": round(sum(grp) / len(grp), 4) if grp else None,
            })

        out = {"taqsimot": hist, "band_sifati": band_sifati,
               "metrics": sc.metrics, "n_train": len(rows),
               "chegaralar": {"review": REVIEW_SCORE, "approve": APPROVE_SCORE},
               "holdout": self._holdout_metrics()}
        self._portfolio_cache = (cache_key, out)
        return out

    @staticmethod
    def _holdout_metrics() -> Optional[dict]:
        """`natija/metrikalar.json` (pipeline `--evaluate` bilan yozadi).

        Ekrandagi AUC — 5-fold CV (o'quv to'plamida). Hakam esa holdout
        natijasini so'raydi; ikkalasi yonma-yon turishi kerak.
        """
        from .config import OUT_DIR
        path = Path(OUT_DIR) / "metrikalar.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def score_of(self, application: dict) -> float:
        return self.scorecard.score(self.features_of(application)).score

    # -- versiyalar -----------------------------------------------------------
    def scorecard_by_version(self, version_id: int) -> Optional[Scorecard]:
        """Eski qarorni eski skorkarta bilan qayta hisoblash uchun."""
        if version_id in self._cache:
            return self._cache[version_id]
        row = db.get_version(self.conn, version_id)
        if row is None:
            return None
        sc = Scorecard.from_dict(json.loads(row["payload"]))
        self._cache[version_id] = sc
        return sc

    def rescore_with_version(self, application_id: str, version_id: int
                             ) -> Optional[dict]:
        """Ariza + tanlangan skorkarta versiyasi -> qayta hisoblangan qaror.

        Jurnalga YOZILMAYDI — bu "nima bo'lardi" tahlili, tarix o'zgarmas.
        """
        sc = self.scorecard_by_version(version_id)
        if sc is None:
            return None
        application = db.get_application(self.conn, application_id)
        if application is None:
            application = next((a for a in self.data.applications
                                if a["application_id"] == application_id), None)
        if application is None:
            return None
        feats = (self.features_of(application)
                 if application["applicant_id"] in self.data.applicants
                 else self.features_from_form(application)[1])
        d = self.decide(application, feats, scorecard=sc)
        out = d.to_dict()
        out["scorecard_version_id"] = version_id
        return out
