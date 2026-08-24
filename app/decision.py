"""Qaror dvigateli: ball + siyosat qoidalari -> QAROR va uning SABABI.

Mavzu tuzog'i shu yerda hal qilinadi: hech qanday qaror sababsiz chiqmaydi.
Har bir qaror uchta qatlamdan iborat:

  1. Knock-out qoidalari  — qattiq to'siqlar (yosh, 90+ kun kechikish, ...).
     Ular ballni umuman ko'rmaydi va o'z sababini o'zi keltiradi.
  2. Skorkarta bali       — omillar hissasi yig'indisi (nega +18, nega −25).
  3. Siyosat shiftlari    — DTI/PTI/PD chegaralari va limit qidiruvi.

Natijada `Decision.sabab` — bo'sh bo'lishi MUMKIN EMAS: rad ham, ma'qullash
ham izohlanadi.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .config import (APPROVE_SCORE, KO_MAX_AGE, KO_MAX_DELINQ_DAYS, KO_MIN_AGE,
                     KO_MIN_TENURE_MONTHS, MAX_DTI, MAX_PD_APPROVE, MAX_PTI,
                     REVIEW_SCORE, UNEMPLOYED_LABELS)
from .explain import client_explanation, client_sentence
from .limit import LimitSearch, max_limit
from .scorecard import ScoreResult, Scorecard

APPROVE = "MAQULLANDI"
REVIEW = "QOLDA_KORIB_CHIQISH"
DECLINE = "RAD_ETILDI"


def _money(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ") + " so'm"


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


class Rule:
    """Bitta siyosat qoidasi va uning natijasi (jurnalga yoziladi)."""

    __slots__ = ("kod", "matn", "qaror", "ogirlik")

    def __init__(self, kod: str, matn: str, qaror: str, ogirlik: str = "qattiq"):
        self.kod, self.matn, self.qaror, self.ogirlik = kod, matn, qaror, ogirlik

    def to_dict(self) -> dict:
        return {"kod": self.kod, "matn": self.matn, "qaror": self.qaror,
                "ogirlik": self.ogirlik}


class Decision:
    def __init__(self, application_id: str, qaror: str, score: ScoreResult,
                 limit: LimitSearch, rules: List[Rule], sabab: str,
                 sorlgan_summa: float, tavsiya_summa: float, feats: dict):
        self.application_id = application_id
        self.qaror = qaror
        self.score = score
        self.limit = limit
        self.rules = rules
        self.sabab = sabab
        self.sorlgan_summa = sorlgan_summa
        self.tavsiya_summa = tavsiya_summa
        self.feats = feats

    # -- izohlash ------------------------------------------------------------
    def mijoz_izohi(self) -> dict:
        """Mijoz ekrani uchun jargonsiz izoh (app/explain.py)."""
        return client_explanation(self)

    def mijoz_sababi(self) -> str:
        """Bitta abzatsli inson tilidagi sabab — CSV va API uchun."""
        return client_sentence(self)

    def musbat_omillar(self, n: int = 3):
        return self.score.top_factors(n, sign=+1)

    def manfiy_omillar(self, n: int = 3):
        return self.score.top_factors(n, sign=-1)

    def to_dict(self) -> dict:
        return {
            "application_id": self.application_id,
            "qaror": self.qaror,
            # Ikki qatlamli izoh: `sabab` — texnik (audit izi, regulyator),
            # `mijoz_izohi` — sodda til (UI ning asosiy bloki).
            "sabab": self.sabab,
            "mijoz_izohi": self.mijoz_izohi(),
            "ball": round(self.score.score, 1),
            "pd": round(self.score.pd, 6),
            "sorlgan_summa": round(self.sorlgan_summa),
            "tavsiya_summa": round(self.tavsiya_summa),
            "limit": self.limit.to_dict(),
            "qoidalar": [r.to_dict() for r in self.rules],
            "skoring": self.score.to_dict(),
            "korsatkichlar": {
                "dti": round(self.feats.get("dti", 0.0), 4),
                "pti": round(self.feats.get("pti", 0.0), 4),
                "dti_current": round(self.feats.get("dti_current", 0.0), 4),
                "income_median": round(self.feats.get("income_median", 0.0)),
                "income_cv": round(self.feats.get("income_cv", 0.0), 4),
                "free_cash": round(self.feats.get("free_cash", 0.0)),
                "max_delinq": self.feats.get("max_delinq", 0.0),
                "ish_staji_oy": self.feats.get("ish_staji_oy", 0.0),
                "bandlik": self.feats.get("bandlik", ""),
                "new_payment": round(self.feats.get("new_payment", 0.0)),
            },
        }


# ---------------------------------------------------------------------------
# Knock-out qoidalari — ballgacha tekshiriladi
# ---------------------------------------------------------------------------


def knockout_rules(feats: dict) -> List[Rule]:
    out: List[Rule] = []
    yosh = feats.get("yosh", 0)
    if yosh and not (KO_MIN_AGE <= yosh <= KO_MAX_AGE):
        out.append(Rule("KO_YOSH",
                        f"Yosh {yosh:.0f} — ruxsat etilgan oraliq "
                        f"{KO_MIN_AGE}–{KO_MAX_AGE}", DECLINE))
    if feats.get("max_delinq", 0) >= KO_MAX_DELINQ_DAYS:
        out.append(Rule("KO_KECHIKISH",
                        f"O'tmishda {feats['max_delinq']:.0f} kunlik kechikish "
                        f"({KO_MAX_DELINQ_DAYS}+ kun — qattiq to'siq)", DECLINE))
    if str(feats.get("bandlik", "")).strip().lower() in UNEMPLOYED_LABELS:
        out.append(Rule("KO_BANDLIK",
                        "Bandlik holati: ishsiz — doimiy daromad manbai yo'q",
                        DECLINE))
    if feats.get("income_used", 0) <= 0:
        out.append(Rule("KO_DAROMAD",
                        "Daromad tasdiqlanmadi (bank oqimi ham, deklaratsiya ham bo'sh)",
                        DECLINE))
    if 0 < feats.get("ish_staji_oy", 0) < KO_MIN_TENURE_MONTHS:
        out.append(Rule("KO_STAJ",
                        f"Ish staji {feats['ish_staji_oy']:.0f} oy — minimal talab "
                        f"{KO_MIN_TENURE_MONTHS} oy", REVIEW))
    return out


def policy_rules(feats: dict, score: ScoreResult,
                 afford_limit: float = 0.0) -> List[Rule]:
    """Siyosat shiftlari.

    Muhim nuance: DTI/PTI shiftidan oshish — RAD emas. Bu "so'ralgan summa
    katta" degani, va to'g'ri javob — kamaytirilgan taklif (counter-offer).
    Rad faqat to'lov qobiliyati umuman qolmaganda (afford_limit == 0) yoki
    risk chegaralari (ball / PD) buzilganda beriladi.
    """
    out: List[Rule] = []
    dti, pti, pd = feats.get("dti", 0.0), feats.get("pti", 0.0), score.pd
    if dti > MAX_DTI:
        out.append(Rule("POL_DTI",
                        f"So'ralgan summada DTI {_pct(dti)} — shift {_pct(MAX_DTI)}"
                        + (f"; taklif: {_money(afford_limit)}" if afford_limit > 0
                           else "; to'lov qobiliyati qolmagan"),
                        REVIEW if afford_limit > 0 else DECLINE,
                        "yumshoq" if afford_limit > 0 else "qattiq"))
    if pti > MAX_PTI:
        out.append(Rule("POL_PTI",
                        f"Yangi to'lov daromadning {_pct(pti)} ini oladi — "
                        f"shift {_pct(MAX_PTI)}",
                        REVIEW if afford_limit > 0 else DECLINE,
                        "yumshoq" if afford_limit > 0 else "qattiq"))
    if pd > MAX_PD_APPROVE:
        out.append(Rule("POL_PD",
                        f"Defolt ehtimoli {_pct(pd)} — shift {_pct(MAX_PD_APPROVE)}",
                        DECLINE))
    if score.score < REVIEW_SCORE:
        out.append(Rule("POL_BALL",
                        f"Ball {score.score:.1f} — minimal chegara {REVIEW_SCORE:.0f}",
                        DECLINE))
    elif score.score < APPROVE_SCORE:
        out.append(Rule("POL_BALL_ORTA",
                        f"Ball {score.score:.0f} — avtomatik ma'qullash chegarasi "
                        f"{APPROVE_SCORE:.0f} dan past", REVIEW, "yumshoq"))
    if feats.get("income_cv", 0) > 0.35:
        out.append(Rule("POL_CV",
                        f"Daromad juda o'zgaruvchan (CV "
                        f"{feats['income_cv']:.2f}) — barqarorlik past",
                        REVIEW, "yumshoq"))
    return out


# ---------------------------------------------------------------------------
# Asosiy dvigatel
# ---------------------------------------------------------------------------


def decide(feats: dict, scorecard: Scorecard,
           rebuild_features=None) -> Decision:
    """Belgilar + skorkarta -> to'liq izohlangan qaror.

    `rebuild_features(summa) -> feats` berilsa, limit qidiruvi skorkartani
    ham hisobga oladi (har bir summa uchun qayta ballash). Berilmasa —
    faqat DTI/PTI cheklovlari.
    """
    score = scorecard.score(feats)
    income = feats.get("income_used", 0.0)
    existing = max(0.0, feats.get("income_used", 0.0) * feats.get("dti_current", 0.0))
    term = feats.get("term_months", 12) or 12

    score_fn = None
    if rebuild_features is not None:
        def score_fn(amount: float):
            r = scorecard.score(rebuild_features(amount))
            return r.score, r.pd

    ko = knockout_rules(feats)
    hard_ko = any(r.qaror == DECLINE for r in ko)
    if hard_ko:
        limit = LimitSearch(0.0, "qattiq to'siq", 0, 0.0, feats.get("dti", 0.0),
                            feats.get("pti", 0.0), afford_limit=0.0,
                            score_gate_ok=False)
    else:
        limit = max_limit(income, existing, term, score_fn=score_fn)

    rules = ko + policy_rules(feats, score, limit.afford_limit)

    # --- yakuniy qaror -------------------------------------------------------
    requested = feats.get("requested", 0.0)
    if any(r.qaror == DECLINE for r in rules):
        qaror, tavsiya = DECLINE, 0.0
    elif any(r.qaror == REVIEW for r in rules):
        qaror = REVIEW
        tavsiya = min(limit.afford_limit, requested)
    else:
        qaror = APPROVE
        tavsiya = min(limit.limit, requested)

    if qaror == APPROVE and tavsiya < requested:
        qaror = REVIEW      # to'liq summa berilmasa — underwriter tasdiqlasin

    sabab = build_reason(qaror, score, rules, limit, requested, tavsiya, feats)
    return Decision(feats.get("application_id", ""), qaror, score, limit, rules,
                    sabab, requested, tavsiya, feats)


def build_reason(qaror: str, score: ScoreResult, rules: List[Rule],
                 limit: LimitSearch, requested: float, tavsiya: float,
                 feats: dict) -> str:
    """Inson o'qiydigan, hech qachon bo'sh bo'lmaydigan sabab matni."""
    blockers = [r for r in rules if r.qaror == DECLINE]
    soft = [r for r in rules if r.qaror == REVIEW]

    if qaror == DECLINE:
        head = "; ".join(r.matn for r in blockers[:2]) or "siyosat chegaralari buzildi"
        neg = score.top_factors(2, sign=-1)
        detail = ", ".join(f"{c.label} ({c.points:+.0f} ball)" for c in neg)
        tail = f". Ballga eng ko'p salbiy ta'sir: {detail}" if detail else ""
        return f"Rad etildi: {head}{tail}. Yakuniy ball {score.score:.0f}."

    if qaror == REVIEW:
        why = "; ".join(r.matn for r in (blockers + soft)[:2])
        if not why and tavsiya < requested:
            why = (f"so'ralgan {_money(requested)} o'rniga to'lov qobiliyati "
                   f"{_money(tavsiya)} ga yetadi ({limit.binding})")
        neg = score.top_factors(2, sign=-1)
        detail = ", ".join(f"{c.label} ({c.points:+.0f})" for c in neg)
        tail = f". Diqqat talab qiladigan omillar: {detail}" if detail else ""
        return (f"Qo'lda ko'rib chiqish: {why or 'chegaraviy ball'}{tail}. "
                f"Ball {score.score:.0f}, tavsiya etilgan limit {_money(tavsiya)}.")

    pos = score.top_factors(3, sign=+1)
    detail = ", ".join(f"{c.label} ({c.points:+.0f} ball)" for c in pos)
    return (f"Ma'qullandi: ball {score.score:.0f} (PD {_pct(score.pd)}), "
            f"DTI {_pct(feats.get('dti', 0.0))} shift ichida. "
            f"Asosiy ijobiy omillar: {detail or 'barqaror profil'}. "
            f"Tasdiqlangan summa {_money(tavsiya)}.")
