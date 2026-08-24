"""Maksimal limitni binary search bilan topish — BONUS ALGORITM.

Muammo: qaysi eng katta summani bersak ham mijoz siyosat chegaralarida qoladi?

    ruxsat(S) = DTI(S) <= MAX_DTI  AND  PTI(S) <= MAX_PTI  AND  erkin_pul(S) >= 0

`ruxsat` MONOTON: S oshsa annuitet to'lov oshadi, DTI/PTI faqat o'sadi. Demak
predikat `True…True False…False` ko'rinishida va binary search to'g'ri ishlaydi.

Skorkarta bali esa WOE bucket'lar tufayli PILLAPOYA funksiya — u monoton
bo'lishi SHART emas. Shuning uchun ball/PD sharti binary search ichida EMAS,
undan keyin chegaralangan "qo'riqchi" tushish bilan tekshiriladi. Bu — nozik
joy: monoton bo'lmagan predikatda binary search jim turib xato javob beradi.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from .config import (ANNUAL_RATE, LIMIT_ABS_MAX, LIMIT_STEP, MAX_DTI, MAX_PD_APPROVE,
                     MAX_PTI, APPROVE_SCORE)
from .features import annuity_payment


class LimitSearch:
    """Bitta arizachi uchun limit qidiruvi natijasi va uning izohi."""

    def __init__(self, limit: float, binding: str, iterations: int,
                 payment: float, dti: float, pti: float, guard_steps: int = 0,
                 afford_limit: Optional[float] = None, score_gate_ok: bool = True):
        self.limit = limit              # ball/PD shartini ham qanoatlantiradi
        self.afford_limit = limit if afford_limit is None else afford_limit
        self.binding = binding          # qaysi cheklov "bog'lab qo'ydi"
        self.iterations = iterations
        self.payment = payment
        self.dti = dti
        self.pti = pti
        self.guard_steps = guard_steps
        self.score_gate_ok = score_gate_ok

    def to_dict(self) -> dict:
        return {"limit": round(self.limit),
                "tolov_qobiliyati_limiti": round(self.afford_limit),
                "cheklovchi_omil": self.binding,
                "ball_sharti": self.score_gate_ok,
                "iteratsiya": self.iterations, "qoriqchi_qadam": self.guard_steps,
                "oylik_tolov": round(self.payment),
                "dti": round(self.dti, 4), "pti": round(self.pti, 4)}


def affordability(amount: float, income: float, existing_debt: float,
                  term_months: float, annual_rate: float = ANNUAL_RATE) -> Dict[str, float]:
    """Berilgan summa uchun to'lov, DTI, PTI. O(1)."""
    payment = annuity_payment(amount, annual_rate, term_months)
    if income <= 0:
        return {"payment": payment, "dti": 99.0, "pti": 99.0, "free_cash": -payment}
    return {
        "payment": payment,
        "dti": (existing_debt + payment) / income,
        "pti": payment / income,
        "free_cash": income - existing_debt - payment,
    }


def binding_constraint(income: float, existing_debt: float, term_months: float,
                       annual_rate: float = ANNUAL_RATE) -> str:
    """Qaysi cheklov birinchi bo'lib ishga tushadi — izoh matni uchun."""
    if income <= 0:
        return "daromad tasdiqlanmagan"
    room_dti = MAX_DTI * income - existing_debt
    room_pti = MAX_PTI * income
    if room_dti <= 0:
        return "mavjud qarz yuklamasi DTI shiftidan oshgan"
    return "DTI shifti" if room_dti <= room_pti else "PTI shifti"


def max_limit(
    income: float,
    existing_debt: float,
    term_months: float,
    score_fn: Optional[Callable[[float], Tuple[float, float]]] = None,
    annual_rate: float = ANNUAL_RATE,
    step: float = LIMIT_STEP,
    hi: float = LIMIT_ABS_MAX,
    min_score: float = APPROVE_SCORE,
    max_pd: float = MAX_PD_APPROVE,
    max_guard_steps: int = 200,
) -> LimitSearch:
    """Siyosat chegarasidagi eng katta summa.

    score_fn(summa) -> (ball, pd); None bo'lsa faqat DTI/PTI ishlatiladi.

    Big-O: O(log(hi/step)) predikat chaqiruvi (bu yerda ~13 iteratsiya
    500 mln so'm / 100k qadam uchun) + qo'riqchi qadamlari O(g), g <= 200.
    Har bir predikat O(1), score_fn bo'lsa O(k) (k = belgilar soni).

    Chekka holatlar:
      * daromad <= 0 yoki mavjud yuk shiftdan oshgan -> limit 0;
      * `hi` ham ruxsat etilsa -> `hi` qaytadi (yuqori chegara);
      * step > 0 bo'lishi shart, aks holda cheksiz sikl.
    """
    if step <= 0:
        raise ValueError("step musbat bo'lishi kerak")

    def ok(amount: float) -> bool:
        a = affordability(amount, income, existing_debt, term_months, annual_rate)
        return a["dti"] <= MAX_DTI and a["pti"] <= MAX_PTI and a["free_cash"] >= 0

    if income <= 0 or not ok(step):
        return LimitSearch(0.0, binding_constraint(income, existing_debt, term_months),
                           0, 0.0, 99.0, 99.0, afford_limit=0.0,
                           score_gate_ok=False)

    # --- 1-bosqich: monoton predikat ustida binary search --------------------
    lo, high = step, hi
    iterations = 0
    if ok(high):
        lo = high
    else:
        while high - lo > step:
            mid = lo + (high - lo) / 2.0
            mid = round(mid / step) * step          # qadamga yaxlitlash
            if mid <= lo or mid >= high:            # yaxlitlash turg'unligi
                break
            iterations += 1
            if ok(mid):
                lo = mid
            else:
                high = mid
    afford = lo

    # --- 2-bosqich: skorkarta qo'riqchisi (monotonlik kafolatlanmagan) -------
    # Ball WOE bucket'lari tufayli pillapoya funksiya, shuning uchun uni
    # binary search predikatiga QO'SHIB BO'LMAYDI. Summani qadamma-qadam
    # kamaytirib tekshiramiz. Agar hech qanday summada ball sharti
    # bajarilmasa — bu limit muammosi emas, RISK muammosi: to'lov qobiliyati
    # limiti saqlanadi, ball darvozasi esa `score_gate_ok=False` bilan
    # belgilanadi va qarorni `decision` qatlami chiqaradi.
    limit, guard, gate_ok, binding = afford, 0, True, \
        binding_constraint(income, existing_debt, term_months)
    if score_fn is not None:
        gate_ok = False
        while limit > 0 and guard < max_guard_steps:
            score, pd = score_fn(limit)
            if score >= min_score and pd <= max_pd:
                gate_ok = True
                break
            limit -= step
            guard += 1
        if not gate_ok:
            limit = 0.0
            binding = "skorkarta bali / PD chegarasi"
        elif limit < afford:
            binding = "skorkarta bali (summa kamaytirildi)"

    a = affordability(afford, income, existing_debt, term_months, annual_rate)
    return LimitSearch(
        limit=max(0.0, limit), afford_limit=afford, binding=binding,
        iterations=iterations, payment=a["payment"],
        dti=a["dti"], pti=a["pti"], guard_steps=guard, score_gate_ok=gate_ok,
    )
