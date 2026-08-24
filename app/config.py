"""Yagona konfiguratsiya nuqtasi — barcha sehrli sonlar shu yerda."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data" / "a2_credit"))
OUT_DIR = Path(os.getenv("OUT_DIR", BASE_DIR / "natija"))
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "kredit.db"))

# --- Scorecard kalibrovkasi (sanoat standarti) -------------------------------
# score = BASE_SCORE + PDO/ln(2) * (ln(BASE_ODDS) - ln(odds))
BASE_SCORE = 600.0      # BASE_ODDS nisbatida beriladigan tayanch ball
# 8:1 — o'quv portfelining haqiqiy odds i (defolt ulushi 11.5% => 7.7:1).
# Shkalani portfelga bog'lash muhim: aks holda barcha arizalar 600 dan past
# tushib qoladi va chegaralar ma'nosini yo'qotadi (birinchi kalibrovkada
# 540 ta test arizasidan atigi 1 tasi ma'qullangan edi).
BASE_ODDS = 8.0
PDO = 20.0              # Points to Double the Odds

SCORE_MIN, SCORE_MAX = 300.0, 900.0

# --- Qaror siyosati (policy) -------------------------------------------------
# Chegaralar train taqsimoti bo'yicha tanlangan: 580 dan past segmentda
# defolt ulushi 36.5%, 600 dan yuqorida ~5-6% — ya'ni 580 haqiqiy uzilish nuqtasi.
APPROVE_SCORE = 630.0   # >= shu ball -> avtomatik ma'qullash mumkin
REVIEW_SCORE = 580.0    # [REVIEW, APPROVE) -> qo'lda ko'rib chiqish
MAX_DTI = 0.50          # jami DTI (mavjud + yangi to'lov) shiftlari
MAX_PTI = 0.35          # faqat yangi to'lov / daromad
MAX_PD_APPROVE = 0.20   # PD shifti

# Qattiq to'siqlar (knock-out) — ball qanday bo'lishidan qat'i nazar rad
KO_MAX_DELINQ_DAYS = 90     # 90+ kun kechikish tarixi
KO_MIN_AGE, KO_MAX_AGE = 18, 70
KO_MIN_TENURE_MONTHS = 3    # ish staji

# --- Limit qidiruvi ----------------------------------------------------------
ANNUAL_RATE = 0.28          # yillik nominal stavka (annuitet uchun)
LIMIT_STEP = 100_000        # limit yaxlitlash qadami (so'm)
LIMIT_ABS_MAX = 500_000_000 # binary search yuqori chegarasi

# --- Binning -----------------------------------------------------------------
MAX_BINS = 6
MIN_BIN_FRACTION = 0.05     # sonli bin kamida 5% kuzatuvni ushlashi kerak
# Kategoriyalar uchun ABSOLYUT minimum. Nisbiy 5% juda qo'pol: "ishsiz"
# toifasida 79 ta kuzatuv bor (defolt ulushi 63% — eng kuchli signal), lekin
# 2160 ta o'quv satrining 5% i = 108, ya'ni u "kam uchraydigan" deb qo'shnisiga
# qo'shilib ketardi va IV 0.54 lik belgi yo'qolardi. WOE ni barqaror baholash
# uchun 30 kuzatuv yetarli.
MIN_CATEGORY_N = 30
LAPLACE = 0.5               # WOE uchun tekislash (nol bo'linishdan himoya)

# --- Lug'atlar ---------------------------------------------------------------
# Yopiq datasetda yozilish biroz farq qilishi mumkin (registr, sinonim).
# Qattiq `== "faol"` taqqoslash jim degradatsiya beradi: kredit faol emas deb
# hisoblanadi -> qarz yuki past chiqadi -> limit oshib ketadi.
ACTIVE_LOAN_STATUSES = {"faol", "ochiq", "active", "open"}
UNEMPLOYED_LABELS = {"ishsiz", "ishsizman", "band emas", "bandemas", "unemployed"}

RANDOM_SEED = 42
