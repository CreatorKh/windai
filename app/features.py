"""Belgi (feature) muhandisligi.

Bu yerda ikkita MAJBURIY algoritm yashaydi:
  1. `dti_pti()`      — qarz yuklamasining daromadga nisbati (DTI / PTI).
  2. `cash_flow()`    — oylik kirim medianasi va o'zgaruvchanligi (CV).

Ikkalasi ham sof funksiya: kirish -> chiqish, global holat yo'q.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from .config import ACTIVE_LOAN_STATUSES, ANNUAL_RATE

# ---------------------------------------------------------------------------
# Kichik statistik yordamchilar (stdlib statistics ga bog'lanmasdan — chekka
# holatlarni o'zimiz boshqarishimiz kerak: bo'sh ro'yxat, bitta element).
# ---------------------------------------------------------------------------


def median(values: Sequence[float]) -> float:
    """O(n log n). Bo'sh ro'yxat -> 0.0 (chaqiruvchi joyda ZeroDivision bo'lmasin)."""
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: Sequence[float]) -> float:
    """Namunaviy (n-1) standart chetlanish. n < 2 -> 0.0."""
    n = len(values)
    if n < 2:
        return 0.0
    mu = mean(values)
    var = sum((v - mu) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def trimmed_mean(values: Sequence[float], trim: float = 0.1) -> float:
    """Ikki uchidan `trim` ulushini kesib tashlab o'rtacha — outlier'ga chidamli."""
    n = len(values)
    if n == 0:
        return 0.0
    k = int(n * trim)
    s = sorted(values)
    core = s[k:n - k] if n - 2 * k > 0 else s
    return mean(core)


# ---------------------------------------------------------------------------
# MAJBURIY ALGORITM #1 — DTI / PTI
# ---------------------------------------------------------------------------


def annuity_payment(principal: float, annual_rate: float, months: float) -> float:
    """Annuitet oylik to'lovi.

    P = S * i / (1 - (1+i)^-n),  i = annual_rate / 12.
    Chekka holat: i == 0 -> oddiy bo'lish; months <= 0 -> to'liq summa.
    """
    if months is None or months <= 0:
        return float(principal)
    i = annual_rate / 12.0
    if i <= 0:
        return principal / months
    factor = 1.0 - (1.0 + i) ** (-months)
    if factor <= 0:                      # son jihatdan buzilish himoyasi
        return principal / months
    return principal * i / factor


def dti_pti(
    monthly_income: float,
    existing_monthly_debt: float,
    new_payment: float,
) -> Dict[str, float]:
    """DTI/PTI hisobi — MAJBURIY ALGORITM #1.

    DTI (Debt-to-Income)     = (mavjud to'lovlar + yangi to'lov) / daromad
    PTI (Payment-to-Income)  = faqat yangi to'lov / daromad
    dti_current              = so'rovdan oldingi holat (mavjud yuk / daromad)

    Big-O: O(1) vaqt, O(1) xotira.
    Chekka holat: daromad <= 0 bo'lsa nisbat aniqlanmagan -> 1.0 (maksimal
    xavf) qaytariladi, `income_missing` bayrog'i bilan. Bu `inf` yoki
    ZeroDivisionError dan ko'ra xavfsizroq: pastki oqim (scorecard) uni
    oddiy "juda yomon" qiymat sifatida qabul qiladi.
    """
    income_missing = monthly_income is None or monthly_income <= 0
    if income_missing:
        return {
            "dti": 1.0,
            "pti": 1.0,
            "dti_current": 1.0,
            "free_cash": 0.0,
            "income_missing": 1.0,
        }
    total_debt = max(0.0, existing_monthly_debt) + max(0.0, new_payment)
    return {
        "dti": min(total_debt / monthly_income, 5.0),           # shift: 500%
        "pti": min(max(0.0, new_payment) / monthly_income, 5.0),
        "dti_current": min(max(0.0, existing_monthly_debt) / monthly_income, 5.0),
        "free_cash": monthly_income - total_debt,
        "income_missing": 0.0,
    }


# ---------------------------------------------------------------------------
# MAJBURIY ALGORITM #2 — Cash-flow tahlili
# ---------------------------------------------------------------------------


def cash_flow(flows: List[dict]) -> Dict[str, float]:
    """Oylik kirim medianasi va o'zgaruvchanligi — MAJBURIY ALGORITM #2.

    Qaytadi:
      income_median   — mediana kirim (outlier'ga chidamli "haqiqiy" daromad)
      income_cv       — variatsiya koeffitsienti = std/mean (barqarorlik o'lchovi)
      income_trend    — oxirgi 6 oy / birinchi 6 oy medianasi (o'sish/pasayish)
      burn_ratio      — chiqim / kirim (sarf intensivligi)
      cash_ratio      — naqd yechish / kirim (kuzatilmaydigan pul ulushi)
      zero_months     — kirim 0 bo'lgan oylar soni (uzilish)
      buffer_months   — o'rtacha oy oxiri qoldiq / o'rtacha chiqim ("yostiq")

    Big-O: O(n log n) — median uchun saralash; n = oylar soni (bu yerda 12),
    ya'ni amalda konstanta. Xotira O(n).
    Chekka holat: bo'sh tarix -> barcha nol, `flows_missing = 1`; mean == 0
    bo'lsa CV aniqlanmagan -> 1.5 (yuqori xavf sifatida) qo'yiladi.
    """
    if not flows:
        return {
            "income_median": 0.0, "income_mean": 0.0, "income_cv": 1.5,
            "income_trend": 1.0, "burn_ratio": 1.0, "cash_ratio": 0.0,
            "zero_months": 12.0, "buffer_months": 0.0, "months_observed": 0.0,
            "flows_missing": 1.0, "net_flow": 0.0,
        }

    inflow = [f["kirim"] for f in flows]
    outflow = [f["chiqim"] for f in flows]
    cash = [f["naqd_yechish"] for f in flows]
    balance = [f["oy_oxiri_qoldiq"] for f in flows]

    inc_med = median(inflow)
    inc_mean = mean(inflow)
    cv = (stdev(inflow) / inc_mean) if inc_mean > 0 else 1.5

    half = max(1, len(inflow) // 2)
    early, late = median(inflow[:half]), median(inflow[half:])
    trend = (late / early) if early > 0 else 1.0

    out_mean = mean(outflow)
    return {
        "income_median": inc_med,
        "income_mean": inc_mean,
        "income_cv": min(cv, 3.0),
        "income_trend": min(max(trend, 0.0), 3.0),
        "burn_ratio": min(out_mean / inc_mean, 3.0) if inc_mean > 0 else 1.0,
        "cash_ratio": min(mean(cash) / inc_mean, 1.5) if inc_mean > 0 else 0.0,
        "zero_months": float(sum(1 for v in inflow if v <= 0)),
        "buffer_months": min(mean(balance) / out_mean, 24.0) if out_mean > 0 else 0.0,
        "months_observed": float(len(flows)),
        "flows_missing": 0.0,
        "net_flow": inc_mean - out_mean,
    }


# ---------------------------------------------------------------------------
# Mavjud kreditlar kesimi
# ---------------------------------------------------------------------------


def loan_burden(loans: List[dict]) -> Dict[str, float]:
    """Faol kreditlar bo'yicha yuk va kechikish tarixi. O(n)."""
    if not loans:
        return {
            "active_payment": 0.0, "active_count": 0.0, "total_balance": 0.0,
            "max_delinq": 0.0, "ever_delinq_30": 0.0, "ever_delinq_90": 0.0,
            "closed_count": 0.0, "bank_count": 0.0, "has_credit_history": 0.0,
        }
    active = [l for l in loans
              if str(l.get("status", "")).strip().lower() in ACTIVE_LOAN_STATUSES]
    max_delinq = max((l["max_kechikish_kun"] for l in loans), default=0.0)
    return {
        "active_payment": sum(l["oylik_tolov"] for l in active),
        "active_count": float(len(active)),
        "total_balance": sum(l["qoldiq"] for l in active),
        "max_delinq": max_delinq,
        "ever_delinq_30": 1.0 if max_delinq >= 30 else 0.0,
        "ever_delinq_90": 1.0 if max_delinq >= 90 else 0.0,
        "closed_count": float(len(loans) - len(active)),
        "bank_count": float(len({l["bank"] for l in loans})),
        "has_credit_history": 1.0,
    }


# ---------------------------------------------------------------------------
# Yig'uvchi: bitta ariza -> to'liq belgi vektori
# ---------------------------------------------------------------------------


def build_features(application: dict, profile: dict) -> Dict[str, object]:
    """Ariza + arizachi profilidan yagona, izohlanuvchi belgi lug'ati.

    Big-O: O(m log m), m = oylar soni (=12). Amalda ariza boshiga konstanta.
    """
    app_row = application
    applicant = profile.get("applicant") or {}
    flows = profile.get("flows") or []
    loans = profile.get("loans") or []

    cf = cash_flow(flows)
    lb = loan_burden(loans)

    # Daromad: deklaratsiya va bank oqimining ehtiyotkor (konservativ) kesishmasi.
    declared = applicant.get("deklaratsiya_daromad", 0.0) or 0.0
    observed = cf["income_median"]
    if observed > 0 and declared > 0:
        income = min(observed, declared * 1.5)      # deklaratsiyadan 50% dan ortiq oshmasin
        income = max(income, declared * 0.5)        # va undan 2 barobar past ham tushmasin
    else:
        income = observed or declared
    income_gap = (observed / declared) if declared > 0 else 1.0

    # Mavjud oylik yuk: ariza maydoni va kredit registri — kattarog'ini olamiz.
    existing_debt = max(app_row.get("mavjud_oylik_yuk", 0.0), lb["active_payment"])

    term = app_row.get("muddat_oy", 12) or 12
    requested = app_row.get("sorlgan_summa", 0.0)
    new_payment = annuity_payment(requested, ANNUAL_RATE, term)

    dp = dti_pti(income, existing_debt, new_payment)

    annual_income = income * 12.0
    return {
        # identifikatorlar
        "application_id": app_row["application_id"],
        "applicant_id": app_row["applicant_id"],
        # majburiy algoritm #1
        "dti": dp["dti"],
        "pti": dp["pti"],
        "dti_current": dp["dti_current"],
        "free_cash": dp["free_cash"],
        "free_cash_ratio": (dp["free_cash"] / income) if income > 0 else -1.0,
        "income_missing": dp["income_missing"],
        # majburiy algoritm #2
        "income_median": cf["income_median"],
        "income_cv": cf["income_cv"],
        "income_trend": cf["income_trend"],
        "burn_ratio": cf["burn_ratio"],
        "cash_ratio": cf["cash_ratio"],
        "zero_months": cf["zero_months"],
        "buffer_months": cf["buffer_months"],
        "net_flow": cf["net_flow"],
        # kredit tarixi
        "max_delinq": lb["max_delinq"],
        "ever_delinq_30": lb["ever_delinq_30"],
        "ever_delinq_90": lb["ever_delinq_90"],
        "active_count": lb["active_count"],
        "bank_count": lb["bank_count"],
        "has_credit_history": lb["has_credit_history"],
        "balance_to_income": (lb["total_balance"] / annual_income) if annual_income > 0 else 3.0,
        # ariza parametrlari
        "requested": requested,
        "term_months": float(term),
        "new_payment": new_payment,
        "loan_to_income": (requested / annual_income) if annual_income > 0 else 5.0,
        "maqsad": app_row.get("maqsad", "nomalum"),
        # demografiya / bandlik
        "yosh": float(applicant.get("yosh", 0)),
        "ish_staji_oy": float(applicant.get("ish_staji_oy", 0.0)),
        "bandlik": applicant.get("bandlik", "nomalum"),
        "talim": applicant.get("talim", "nomalum"),
        "oila_azolari": float(applicant.get("oila_azolari", 1)),
        "mijoz_boldi_oy": float(applicant.get("mijoz_boldi_oy", 0.0)),
        "viloyat": applicant.get("viloyat", "nomalum"),
        # daromad sifati
        "income_used": income,
        "declared_income": declared,
        "income_gap": min(income_gap, 3.0),
        "income_per_capita": income / max(1.0, float(applicant.get("oila_azolari", 1))),
    }
