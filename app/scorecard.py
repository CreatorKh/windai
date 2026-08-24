r"""Skorkarta: WOE binning + logistik regressiya -> BALL va OMILLAR HISSASI.

Ball formulasi (sanoat standarti, "points to double the odds"):

    factor = PDO / ln(2)
    odds   = P(yaxshi) / P(yomon) = exp(-z),   z = a + SUM_j b_j * woe_j
    score  = BASE_SCORE + factor * ( ln(odds) - ln(BASE_ODDS) )
           = neytral_ball  +  SUM_j ( -factor * b_j * woe_j )
                              \________  omil hissasi  ________/

Ya'ni ball — omillar hissasining oddiy YIG'INDISI. Shuning uchun
"nega +18, nega −25" savoliga javob approksimatsiya emas, aniq arifmetika:
hissalar yig'indisi har doim yakuniy balni beradi (test bilan tekshiriladi).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .binning import FeatureBinning, fit_categorical, fit_numeric, iv_strength
from .config import BASE_ODDS, BASE_SCORE, MAX_BINS, PDO, SCORE_MAX, SCORE_MIN
from .model import LogisticRegression, sigmoid

# ---------------------------------------------------------------------------
# Modelga kiradigan belgilar. Tartib = skorkarta satrlari tartibi.
# (kalit, tur, inson o'qiydigan nom, format)
# ---------------------------------------------------------------------------
# HIMOYALANGAN BELGILAR. `jins` va `viloyat` nomzod sifatida ham kiritilmagan.
# `yosh` ham reyting omili EMAS: o'lchov bo'yicha u ballga 14.9 ball ta'sir
# qilardi (yoshlar -7.6, 50+ +7.3) va ma'qullash nisbatini 0.51 ga tushirardi,
# holbuki ochiq datasetda yoshlarning haqiqiy defolti past (8.45% / 9.58%).
# Uni olib tashlash AUC ni yomonlashtirmadi. Yosh faqat LAYOQAT chegarasi
# sifatida qoladi (app/decision.py::knockout_rules, 18-70).
FEATURE_SPEC: List[Tuple[str, str, str, str]] = [
    ("free_cash",        "numeric",     "To'lovlardan keyingi erkin pul",    "money"),
    ("dti",              "numeric",     "Umumiy qarz yuki (yangi kredit bilan)", "ratio"),
    ("dti_current",      "numeric",     "Mavjud qarz yuki (yangi kreditsiz)",    "ratio"),
    ("pti",              "numeric",     "Yangi to'lov / daromad (PTI)",      "ratio"),
    ("income_cv",        "numeric",     "Daromad o'zgaruvchanligi (CV)",     "ratio"),
    ("income_median",    "numeric",     "Oylik daromad medianasi",           "money"),
    ("income_trend",     "numeric",     "Daromad trendi (2-yarim/1-yarim)",  "ratio"),
    ("burn_ratio",       "numeric",     "Sarf intensivligi (chiqim/kirim)",  "ratio"),
    ("cash_ratio",       "numeric",     "Naqd yechish ulushi",               "ratio"),
    ("buffer_months",    "numeric",     "Moliyaviy yostiq (oy)",             "num"),
    ("max_delinq",       "numeric",     "O'tmishdagi maks. kechikish (kun)", "num"),
    ("active_count",     "numeric",     "Faol kreditlar soni",               "num"),
    ("balance_to_income","numeric",     "Qarz qoldig'i / yillik daromad",    "ratio"),
    ("loan_to_income",   "numeric",     "So'ralgan summa / yillik daromad",  "ratio"),
    ("ish_staji_oy",     "numeric",     "Ish staji (oy)",                    "num"),
    ("mijoz_boldi_oy",   "numeric",     "Bank bilan tarix (oy)",             "num"),
    ("income_per_capita","numeric",     "Jon boshiga daromad",               "money"),
    ("income_gap",       "numeric",     "Bank oqimi / deklaratsiya",         "ratio"),
    ("term_months",      "numeric",     "Kredit muddati (oy)",               "num"),
    ("bandlik",          "categorical", "Bandlik turi",                      "text"),
    ("talim",            "categorical", "Ma'lumot",                          "text"),
    ("maqsad",           "categorical", "Kredit maqsadi",                    "text"),
]

FACTOR = PDO / math.log(2.0)

# Domen bilimi bilan qo'lda berilgan chegaralar. Diskret yoki kuchli
# qiyshaygan belgilar uchun kvantil binning ma'noli segmentni yo'qotadi.
CUTS_OVERRIDE: Dict[str, List[float]] = {
    # Kechikish kunlari amalda {0, 15, 45, 95} — Bazel talqiniga mos kesimlar.
    "max_delinq": [1.0, 30.0, 90.0],
    # Kredit tarixi yo'q / bor / ko'p — 0 alohida ma'noga ega.
    "active_count": [1.0, 2.0, 3.0],
    # Barqaror maosh / o'rtacha o'zgaruvchan / kuchli suzuvchi daromad.
    # Chegaralar MONOTONLIK bo'yicha tanlangan: [0.05, 0.15, 0.25, 0.35] da
    # 41 kuzatuvli "0.05…0.15" bucket'i defolt ulushi 4.9% bilan chiqib,
    # "o'rtacha o'zgaruvchan daromad barqarordan XAVFSIZROQ" degan yolg'on
    # izohni keltirib chiqarardi. [0.15, 0.25] da bad-rate monoton o'sadi
    # (10.4% -> 13.1% -> 13.9%), eng kichik bucket 305 kuzatuv, AUC esa
    # o'zgarmaydi (0.7666 -> 0.7675).
    "income_cv": [0.15, 0.25],
}


class FactorContribution:
    """Bitta omilning qarordagi ulushi — UI shu obyektni ko'rsatadi."""

    __slots__ = ("key", "label", "value", "bin_label", "woe", "beta", "points", "fmt")

    def __init__(self, key, label, value, bin_label, woe, beta, points, fmt):
        self.key, self.label, self.value = key, label, value
        self.bin_label, self.woe, self.beta = bin_label, woe, beta
        self.points, self.fmt = points, fmt

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "value": self.value,
                "bin": self.bin_label, "woe": round(self.woe, 4),
                "beta": round(self.beta, 4), "points": round(self.points, 1),
                "fmt": self.fmt}


class ScoreResult:
    def __init__(self, score, pd, neutral, contributions, version):
        self.score = score
        self.pd = pd
        self.neutral = neutral
        self.contributions: List[FactorContribution] = contributions
        self.version = version

    def top_factors(self, n: int = 5, sign: Optional[int] = None
                    ) -> List[FactorContribution]:
        items = self.contributions
        if sign is not None:
            items = [c for c in items if (c.points < 0 if sign < 0 else c.points > 0)]
        return sorted(items, key=lambda c: -abs(c.points))[:n]

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "pd": round(self.pd, 6),
            "neytral_ball": round(self.neutral, 1),
            "scorecard_version": self.version,
            "omillar": [c.to_dict() for c in
                        sorted(self.contributions, key=lambda c: c.points)],
        }


class Scorecard:
    """Versiyalanadigan skorkarta: binning + koeffitsientlar + kalibrovka."""

    def __init__(self, binnings: Dict[str, FeatureBinning],
                 model: LogisticRegression, spec: List[Tuple[str, str, str, str]],
                 version: str = "v1", trained_on: int = 0,
                 metrics: Optional[dict] = None):
        self.binnings = binnings
        self.model = model
        self.spec = spec
        self.version = version
        self.trained_on = trained_on
        self.metrics = metrics or {}

    # -- o'rgatish -----------------------------------------------------------
    @staticmethod
    def fit(rows: List[dict], labels: List[int], version: str = "v1",
            spec: Optional[List[Tuple[str, str, str, str]]] = None,
            min_iv: float = 0.02, l2: float = 1.0,
            max_bins: int = MAX_BINS) -> "Scorecard":
        """rows = build_features() natijalari, labels = 1(defolt)/0(to'ladi).

        1) Har bir belgi uchun WOE binning quriladi.
        2) IV bo'yicha zaif belgilar tashlab yuboriladi (shovqinni kamaytirish).
        3) Qolganlari WOE ga aylantirilib, logistik regressiya o'rgatiladi.
        4) "Noto'g'ri ishora" (wrong sign) tozalash — pastga qarang.
        """
        spec = spec or FEATURE_SPEC
        binnings: Dict[str, FeatureBinning] = {}
        kept: List[Tuple[str, str, str, str]] = []
        for key, kind, label, fmt in spec:
            values = [r.get(key) for r in rows]
            if kind == "numeric":
                fb = fit_numeric(key, [float(v or 0.0) for v in values], labels,
                                 max_bins=max_bins,
                                 cuts_override=CUTS_OVERRIDE.get(key))
            else:
                fb = fit_categorical(key, [str(v) for v in values], labels)
            binnings[key] = fb
            if fb.iv >= min_iv:
                kept.append((key, kind, label, fmt))

        if not kept:                      # hech qanday belgi o'tmasa — hammasi
            kept = list(spec)

        # WOE ta'rifi bo'yicha "WOE kattaroq => defolt ehtimoli kattaroq".
        # Demak TO'G'RI o'rgatilgan skorkartada har bir beta >= 0 bo'lishi shart.
        # Manfiy beta — multikollinearlik alomati: model bir belgini ikkinchisini
        # "tuzatish" uchun teskari ishlatadi. Ball izohi shunda yolg'on bo'ladi
        # ("DTI yuqori — bu yaxshi"). Shuning uchun eng manfiy belgini olib
        # tashlab, qaytadan o'rgatamiz (sanoatda: wrong-sign elimination).
        model = None
        while kept:
            X = [[binnings[k].woe_of(_val(r, k, kind))[0]
                  for k, kind, _, _ in kept] for r in rows]
            model = LogisticRegression(l2=l2).fit(
                X, labels, [k for k, _, _, _ in kept])
            worst = min(range(len(model.coef)), key=lambda i: model.coef[i])
            if model.coef[worst] >= 0 or len(kept) <= 2:
                break
            kept.pop(worst)

        return Scorecard(binnings, model, kept, version, trained_on=len(rows))

    # -- ballash -------------------------------------------------------------
    def score(self, feats: dict) -> ScoreResult:
        """Bitta ariza -> ball, PD va omillar hissasi. O(k) (k <= 21)."""
        woes, bins = [], []
        for key, kind, _, _ in self.spec:
            w, b = self.binnings[key].woe_of(_val(feats, key, kind))
            woes.append(w)
            bins.append(b)

        z = self.model.decision_value(woes)
        pd = sigmoid(z)

        neutral = BASE_SCORE - FACTOR * (math.log(BASE_ODDS) + self.model.intercept)
        contributions: List[FactorContribution] = []
        for (key, kind, label, fmt), w, b, beta in zip(
                self.spec, woes, bins, self.model.coef):
            contributions.append(FactorContribution(
                key=key, label=label, value=feats.get(key),
                bin_label=b.label, woe=w, beta=beta,
                points=-FACTOR * beta * w, fmt=fmt,
            ))

        raw = neutral + sum(c.points for c in contributions)
        score = min(max(raw, SCORE_MIN), SCORE_MAX)
        return ScoreResult(score, pd, neutral, contributions, self.version)

    # -- diagnostika ---------------------------------------------------------
    def iv_table(self, base_rate: Optional[float] = None) -> List[dict]:
        """Belgilar jadvali — UI uchun INSON O'QIYDIGAN qo'shimchalar bilan.

        Xom WOE va "< 0.04" kabi yorliqlar faqat mutaxassisga tushunarli.
        Shu sababli har bucket uchun qo'shimcha hisoblanadi:
          * `human` — o'lchov birligidagi oraliq ("4% dan kam", "2.1 mln gacha");
          * `nisbat` — shu guruhdagi defolt ulushi PORTFEL o'rtachasiga nisbatan
            necha barobar ("o'rtachadan 2.7 barobar ko'p") — WOE ning
            jargonsiz muqobili.
        """
        # portfel o'rtacha defolt ulushi — barcha bucket'lardan tiklanadi
        if base_rate is None:
            n_all = sum(b.n for fb in self.binnings.values() for b in fb.bins) or 1
            bad_all = sum(b.bad for fb in self.binnings.values() for b in fb.bins)
            n_feat = max(1, len(self.binnings))
            base_rate = (bad_all / n_feat) / max(1.0, n_all / n_feat)

        betas = dict(zip(self.model.names, self.model.coef))
        out = []
        for key, kind, label, fmt in self.spec:
            fb = self.binnings[key]
            bins = []
            for b in fb.bins:
                d = b.to_dict()
                d["human"] = (b.label if kind == "categorical"
                              else _human_range(d["lo"], d["hi"], fmt))
                d["nisbat"] = (round(b.bad_rate / base_rate, 2)
                               if base_rate > 0 and b.n else None)
                bins.append(d)
            out.append({"key": key, "label": label, "iv": round(fb.iv, 4),
                        "kuch": iv_strength(fb.iv), "kind": kind, "fmt": fmt,
                        "beta": round(betas.get(key, 0.0), 4),
                        "base_rate": round(base_rate, 4),
                        "bins": bins})
        return sorted(out, key=lambda r: -r["iv"])

    # -- serializatsiya (SCD Type 2 uchun) -----------------------------------
    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "trained_on": self.trained_on,
            "metrics": self.metrics,
            "spec": [list(s) for s in self.spec],
            "model": self.model.to_dict(),
            "binnings": {k: v.to_dict() for k, v in self.binnings.items()},
            "calibration": {"base_score": BASE_SCORE, "base_odds": BASE_ODDS,
                            "pdo": PDO},
        }

    @staticmethod
    def from_dict(d: dict) -> "Scorecard":
        return Scorecard(
            binnings={k: FeatureBinning.from_dict(v)
                      for k, v in d["binnings"].items()},
            model=LogisticRegression.from_dict(d["model"]),
            spec=[tuple(s) for s in d["spec"]],
            version=d["version"],
            trained_on=d.get("trained_on", 0),
            metrics=d.get("metrics", {}),
        )


def _unit(v: float, fmt: str) -> str:
    """Bitta chegara qiymatini o'lchov birligida yozadi."""
    if fmt == "ratio":
        return f"{v * 100:.0f}%" if abs(v) >= 0.1 or v == 0 else f"{v * 100:.1f}%"
    if fmt == "money":
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:.1f} mln"
        if abs(v) >= 1000:
            return f"{v / 1000:.0f} ming"
        return f"{v:.0f}"
    if abs(v) >= 100:
        return f"{v:.0f}"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}"


def _human_range(lo, hi, fmt: str) -> str:
    """(lo, hi) -> "4% dan kam" / "4% – 17%" / "52% dan yuqori"."""
    if lo is None and hi is None:
        return "barcha qiymatlar"
    if lo is None:
        return f"{_unit(hi, fmt)} dan kam"
    if hi is None:
        return f"{_unit(lo, fmt)} dan yuqori"
    return f"{_unit(lo, fmt)} – {_unit(hi, fmt)}"


def _val(row: dict, key: str, kind: str):
    v = row.get(key)
    if kind == "numeric":
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return str(v if v is not None else "nomalum")
