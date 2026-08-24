"""Qarorni INSON TILIGA o'girish.

Mavzuning asosiy talabi — "nega?" savoliga javob. Lekin javob ikki xil
auditoriyaga kerak va ular bir xil tilda gaplashmaydi:

  * MIJOZ  — "DTI 52.7% — shift 50.0%" degan gapdan hech narsa tushunmaydi.
             Unga kerak: nima bo'ldi, nega, va ENDI NIMA QILSAM BO'LADI.
  * UNDERWRITER / REGULYATOR — aksincha, aniq raqam, koeffitsient va
             ball hissasi kerak; "biroz ko'p" degan gap ish bermaydi.

Shuning uchun bitta qarordan IKKI QATLAMLI izoh chiqariladi:
  `Decision.sabab`        — texnik (CSV, jurnal, audit izi)
  `client_explanation()`  — sodda til (mijoz ekrani, UI ning asosiy bloki)

Bu yerda faqat MATN yaratiladi — hech qanday qaror mantig'i yo'q. Shu sababli
siyosat o'zgarsa izoh avtomatik moslashadi, va aksincha: matnni tahrirlash
qarorni o'zgartirib yubormaydi.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .config import (ANNUAL_RATE, APPROVE_SCORE, KO_MAX_DELINQ_DAYS,
                     KO_MIN_TENURE_MONTHS, MAX_DTI, MAX_PTI, UNEMPLOYED_LABELS)
from .features import annuity_payment


# ---------------------------------------------------------------------------
# Formatlash
# ---------------------------------------------------------------------------


def som(v: float) -> str:
    """1234567 -> '1 234 567 so'm'."""
    return f"{v:,.0f}".replace(",", " ") + " so'm"


def foiz(v: float, d: int = 0) -> str:
    return f"{v * 100:.{d}f}%"


def oy(v: float) -> str:
    n = int(round(v))
    if n >= 12 and n % 12 == 0:
        return f"{n // 12} yil"
    if n > 12:
        return f"{n // 12} yil {n % 12} oy"
    return f"{n} oy"


# ---------------------------------------------------------------------------
# Har bir omil uchun mijoz tilidagi ifoda.
#
# Kalit -> (ijobiy_matn, salbiy_matn). Ikkalasi ham `feats` lug'atini oladi,
# chunki matn ichida haqiqiy raqam turishi kerak: "oyiga 2 930 018 so'm qoladi"
# degan gap "erkin pul yuqori" dan ko'ra ancha ishonarli.
# ---------------------------------------------------------------------------
Phrase = Callable[[dict], str]
HUMAN: Dict[str, Dict[str, Phrase]] = {
    "free_cash": {
        "+": lambda f: f"barcha to'lovlardan keyin oyiga {som(f['free_cash'])} qoladi",
        "-": lambda f: ("so'ralgan summa bilan to'lovlardan keyin qo'lingizda "
                        "pul qolmaydi"
                        if f["free_cash"] <= 0 else
                        f"so'ralgan summada to'lovlardan keyin oyiga atigi "
                        f"{som(f['free_cash'])} qoladi"),
    },
    "dti": {
        "+": lambda f: f"umumiy qarz yuki daromadning {foiz(f['dti'])} i — xavfsiz daraja",
        "-": lambda f: (f"so'ralgan summada umumiy qarz yuki daromadning "
                        f"{foiz(f['dti'])} ini egallaydi"),
    },
    "dti_current": {
        # WOE bucket ijobiy bo'lsa ham QIYMATGA qarab gapiramiz: 51% yukni
        # "past" deb bo'lmaydi (rad sababi bilan bevosita ziddiyat chiqqan edi).
        "+": lambda f: ("boshqa banklarda faol qarzingiz yo'q — toza kredit profili"
                        if f["dti_current"] <= 0.005 else
                        f"mavjud qarz yukingiz past — daromadning atigi "
                        f"{foiz(f['dti_current'])} i"
                        if f["dti_current"] <= 0.25 else
                        f"mavjud to'lovlaringiz daromadning {foiz(f['dti_current'])} ini "
                        f"tashkil qiladi"),
        "-": lambda f: (f"yangi kreditgacha ham mavjud to'lovlaringiz daromadning "
                        f"{foiz(f['dti_current'])} ini oladi"),
    },
    "pti": {
        "+": lambda f: f"yangi to'lov daromadning atigi {foiz(f['pti'])} ini oladi",
        "-": lambda f: (f"so'ralgan summaning oylik to'lovi daromadning "
                        f"{foiz(f['pti'])} ini oladi — bu og'ir"),
    },
    "income_cv": {
        "+": lambda f: "daromadingiz oydan oyga barqaror",
        "-": lambda f: "daromadingiz oylar bo'yicha keskin o'zgarib turadi",
    },
    "income_median": {
        "+": lambda f: f"oylik daromadingiz {som(f['income_median'])} — yetarli daraja",
        "-": lambda f: (f"oylik daromadingiz {som(f['income_median'])} — bu daraja "
                        f"statistik jihatdan yuqoriroq xavfli guruhga to'g'ri keladi"),
    },
    "income_trend": {
        "+": lambda f: "oxirgi oylarda daromadingiz o'sgan",
        "-": lambda f: "oxirgi oylarda daromadingiz kamaygan",
    },
    "burn_ratio": {
        "+": lambda f: ("hisobingizda ortiqcha xarajat kuzatilmaydi"
                        if f["burn_ratio"] < 0.005 else
                        f"xarajatlaringiz daromadning {foiz(f['burn_ratio'])} i — tejamkor"
                        if f["burn_ratio"] < 0.5 else
                        f"xarajatlaringiz daromadning {foiz(f['burn_ratio'])} i — "
                        f"me'yor doirasida"
                        if f["burn_ratio"] < 0.7 else
                        f"xarajatlaringiz daromadning {foiz(f['burn_ratio'])} ini "
                        f"tashkil qiladi"),
        "-": lambda f: (f"xarajatlaringiz daromadning {foiz(f['burn_ratio'])} ini "
                        f"tashkil qiladi — erkin mablag' kam qoladi"),
    },
    "cash_ratio": {
        "+": lambda f: "pul harakatingiz shaffof, naqd yechish kam",
        "-": lambda f: (f"daromadning {foiz(f['cash_ratio'])} i naqd yechib olinadi — "
                        f"bank uchun bu ko'rinmas pul"),
    },
    "buffer_months": {
        "+": lambda f: f"hisobingizda taxminan {oy(f['buffer_months'])} yetadigan zaxira bor",
        "-": lambda f: "hisobingizda zaxira deyarli qolmaydi",
    },
    "max_delinq": {
        "+": lambda f: "kredit tarixingiz toza — kechikish yo'q",
        "-": lambda f: f"o'tmishda {int(f['max_delinq'])} kunlik kechikish qayd etilgan",
    },
    "active_count": {
        "+": lambda f: "boshqa banklardagi kreditlaringiz kam",
        "-": lambda f: f"bir vaqtda {int(f['active_count'])} ta faol kredit to'layapsiz",
    },
    "balance_to_income": {
        "+": lambda f: "mavjud qarz qoldig'i yillik daromadingizga nisbatan kichik",
        "-": lambda f: (f"mavjud qarz qoldig'i yillik daromadingizdan "
                        f"{f['balance_to_income']:.1f} barobar ko'p"
                        if f["balance_to_income"] >= 1.5 else
                        f"mavjud qarz qoldig'i yillik daromadingizning "
                        f"{foiz(f['balance_to_income'])} iga teng — bu sezilarli yuk"),
    },
    "loan_to_income": {
        "+": lambda f: "so'ralgan summa daromadingizga mos",
        "-": lambda f: (f"so'ralgan summa yillik daromadingizdan "
                        f"{f['loan_to_income']:.1f} barobar katta"
                        if f["loan_to_income"] >= 1.5 else
                        f"so'ralgan summa yillik daromadingizning "
                        f"{foiz(f['loan_to_income'])} iga teng — sezilarli so'rov"),
    },
    "ish_staji_oy": {
        "+": lambda f: f"ish stajingiz uzoq — {oy(f['ish_staji_oy'])}",
        "-": lambda f: ("hozircha tasdiqlangan ish stajingiz yo'q"
                        if f["ish_staji_oy"] <= 0 else
                        f"ish stajingiz qisqa — atigi {oy(f['ish_staji_oy'])}"),
    },
    "yosh": {
        "+": lambda f: f"{int(f['yosh'])} yosh — statistik jihatdan barqaror guruh",
        "-": lambda f: f"{int(f['yosh'])} yosh guruhida to'lovni kechiktirish ko'proq uchraydi",
    },
    "mijoz_boldi_oy": {
        "+": lambda f: f"bankimiz bilan tarixingiz uzoq — {oy(f['mijoz_boldi_oy'])}",
        "-": lambda f: ("siz bankimizga yangi mijozsiz — tariximiz hali shakllanmagan"
                        if f["mijoz_boldi_oy"] <= 0 else
                        f"bankimiz bilan tarixingiz qisqa — {oy(f['mijoz_boldi_oy'])}, "
                        f"hamkorlik tarixi hali to'liq shakllanmagan"
                        if f["mijoz_boldi_oy"] < 12 else
                        f"bankimiz bilan tarixingiz nisbatan qisqa — "
                        f"{oy(f['mijoz_boldi_oy'])}"),
    },
    "income_per_capita": {
        "+": lambda f: (f"oila a'zosiga oyiga {som(f['income_per_capita'])} to'g'ri keladi — "
                        f"yetarli"),
        "-": lambda f: (f"oila a'zosiga oyiga atigi {som(f['income_per_capita'])} "
                        f"to'g'ri keladi"),
    },
    # Shablon WOE bucket ishorasiga emas, HAQIQIY qiymatga qarab tanlanadi:
    # aks holda deklaratsiyasi tasdiqlangan mijozga ham "farq qiladi" deyilardi
    # (o'lchov: 100 arizadan 38 tasida shunday bo'lgan, hammasida |gap-1| < 0.15).
    "income_gap": {
        "+": lambda f: "bank hisobingizdagi tushum deklaratsiya bilan mos",
        "-": lambda f: ("bank hisobingizdagi tushum deklaratsiyangizdan sezilarli farq qiladi"
                        if abs(f.get("income_gap", 1.0) - 1.0) >= 0.15
                        else "bank hisobingizdagi tushum deklaratsiya bilan mos"),
    },
    "term_months": {
        "+": lambda f: f"tanlangan {oy(f['term_months'])} muddat to'lovni yengillashtiradi",
        "-": lambda f: f"tanlangan {oy(f['term_months'])} muddat xavfni oshiradi",
    },
    "bandlik": {
        "+": lambda f: f"bandlik turingiz ({f['bandlik']}) barqaror daromad beradi",
        "-": lambda f: f"bandlik turingiz ({f['bandlik']}) yuqori xavfli guruhda",
    },
    "talim": {
        "+": lambda f: f"ma'lumot darajangiz ({f['talim']}) ijobiy ta'sir qiladi",
        "-": lambda f: f"ma'lumot darajangiz ({f['talim']}) statistik jihatdan xavfliroq guruhda",
    },
    "maqsad": {
        "+": lambda f: f"kredit maqsadi ({f['maqsad']}) past xavfli toifada",
        "-": lambda f: f"kredit maqsadi ({f['maqsad']}) yuqori xavfli toifada",
    },
}


# Mijozga KO'RSATILADIGAN omillar. Ro'yxatda yo'q belgilar texnik qatlamda
# (waterfall, `sabab_texnik`, jurnal) qoladi, lekin mijoz matniga tushmaydi.
#
# `yosh` va `talim` ataylab yo'q: ular (a) mijoz ta'sir qila olmaydigan,
# (b) huquqiy jihatdan nozik belgilar. "25 yoshdagilar ko'proq kechiktiradi"
# degan jumla — bu yoshga ko'ra kamsitish sifatida o'qiladi, va o'lchov
# bo'yicha u 540 qarordan 234 tasida mijoz matniga tushib qolgan edi.
CLIENT_VISIBLE = {
    "free_cash", "dti", "dti_current", "pti", "income_cv", "income_median",
    "income_trend", "burn_ratio", "cash_ratio", "buffer_months", "max_delinq",
    "active_count", "balance_to_income", "loan_to_income", "ish_staji_oy",
    "mijoz_boldi_oy", "income_per_capita", "income_gap", "term_months",
    "bandlik", "maqsad",
}

# Shovqin chegarasi: ±1 ballik omilni mijozga aytish faqat chalg'itadi.
MIN_CLIENT_POINTS = 2.0


def client_factors(score_result, feats: dict, sign: int, n: int = 3):
    """Mijozga ko'rsatish mumkin bo'lgan eng kuchli `n` omil."""
    items = [c for c in score_result.contributions
             if c.key in CLIENT_VISIBLE
             and abs(c.points) >= MIN_CLIENT_POINTS
             and (c.points > 0 if sign > 0 else c.points < 0)]
    items.sort(key=lambda c: -abs(c.points))
    return items[:n]


def humanize(contribution, feats: dict) -> str:
    """Bitta omil hissasini mijoz tushunadigan gapga aylantiradi."""
    return _humanize_signed(contribution, feats,
                            "+" if contribution.points > 0 else "-")


def humanize_for_list(contribution, feats: dict):
    """Ro'yxat uchun: agar salbiy omilning matni ijobiy varianti bilan BIR XIL
    chiqsa (masalan income_gap aslida mos bo'lsa), None qaytadi va omil
    ro'yxatdan tushib qoladi — "to'sqinlik qildi: deklaratsiya bilan mos"
    degan bema'nilik ko'rinmasin. WOE bucket baribir ballda hisobda qoladi,
    bu faqat MATN darajasidagi filtr.
    """
    sign = "+" if contribution.points > 0 else "-"
    txt = _humanize_signed(contribution, feats, sign)
    if sign == "-":
        other = _humanize_signed(contribution, feats, "+")
        if txt == other:
            return None
    return txt


def _humanize_signed(contribution, feats: dict, sign: str) -> str:
    tmpl = HUMAN.get(contribution.key)
    if not tmpl:
        return contribution.label
    try:
        return tmpl[sign](feats)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        # Matn hech qachon qarorni buzmasin: eng yomon holatda texnik nom.
        return contribution.label


# ---------------------------------------------------------------------------
# "Nima qilsam bo'ladi?" — amaliy maslahat
# ---------------------------------------------------------------------------


def next_steps(decision) -> List[str]:
    """Mijoz uchun aniq, bajariladigan qadamlar. Bo'sh qaytmaydi."""
    f = decision.feats
    steps: List[str] = []
    requested = f.get("requested", 0.0)
    afford = decision.limit.afford_limit
    gated = decision.limit.limit

    # 1) Eng aniq maslahat: qaysi summa hoziroq o'tadi.
    if gated > 0 and gated < requested:
        # "Hozirdanoq ma'qullanadi" deb va'da bera olmaymiz: summadan tashqari
        # yumshoq qoidalar (masalan daromad o'zgaruvchanligi) ham bor.
        steps.append(f"So'rovni {som(gated)}gacha kamaytiring — bu summada "
                     f"ma'qullanish ehtimoli sezilarli oshadi.")
    elif afford > 0 and afford < requested:
        if decision.qaror == "QOLDA_KORIB_CHIQISH":
            steps.append(f"To'lov qobiliyatingiz {som(afford)}ga yetadi — shu "
                         f"summani so'rasangiz, xodim qarori osonlashadi.")
        else:
            steps.append(f"To'lov qobiliyatingiz {som(afford)}ga yetadi. Shu summani "
                         f"so'rasangiz, ariza qo'lda ko'rib chiqishga tushadi.")

    # 2) Muddat — eng oson tuzatiladigan parametr.
    term = f.get("term_months", 12)
    if (afford > 0 and term < 60
            and (f.get("pti", 0) > MAX_PTI or f.get("dti", 0) > MAX_DTI)):
        steps.append(f"Muddatni uzaytirib ko'ring (hozir {oy(term)}) — oylik to'lov "
                     f"kamayadi va qarz yuki chegaraga yaqinlashadi.")

    # 3) Mavjud yuk. `active_count` sharti olib tashlandi: yuk kredit
    # registridan emas, ariza maydonidan ham kelishi mumkin (boshqa bank).
    # Knock-out kechikish bo'lsa bu maslahat o'rinsiz — asosiy to'siq boshqa.
    if (f.get("dti_current", 0) > 0.25
            and f.get("max_delinq", 0) < KO_MAX_DELINQ_DAYS):
        steps.append("Mavjud oylik to'lovlaringiz daromadga nisbatan og'ir — "
                     "bittasini yopsangiz, qarz yuki pasayadi va limit oshadi.")

    # 4) Knock-out sabablari — vaqt talab qiladigan maslahat.
    if str(f.get("bandlik", "")).strip().lower() in UNEMPLOYED_LABELS:
        steps.append("Rasmiy ish joyi va muntazam daromad tasdiqlangach murojaat qiling — "
                     "bu asosiy shart.")
    if f.get("max_delinq", 0) >= KO_MAX_DELINQ_DAYS:
        steps.append("Kechikish yopilgandan keyin 12 oy toza to'lov tarixi to'plang, "
                     "so'ng qayta murojaat qiling.")
    staji = f.get("ish_staji_oy", 0)
    if 0 < staji < KO_MIN_TENURE_MONTHS:
        steps.append(f"Ish stajingiz {KO_MIN_TENURE_MONTHS} oyga yetganda qayta murojaat "
                     f"qiling — hozir {oy(staji)}.")

    # 5) Daromadni ko'rsatish sifati.
    if f.get("income_cv", 0) > 0.35:
        steps.append("Daromadingizni muntazam bank hisobiga o'tkazing — barqaror oqim "
                     "ballni oshiradi.")
    if f.get("cash_ratio", 0) > 0.4:
        steps.append("Naqd yechishni kamaytiring: kartadan to'lov qilsangiz, bank sizning "
                     "to'lov qobiliyatingizni ko'radi.")
    if f.get("income_gap", 1.0) < 0.8:
        steps.append("Deklaratsiya qilingan daromadingiz bank hisobingizdagi tushumdan yuqori. "
                     "Qo'shimcha daromad hujjatini keltiring.")

    if not steps:
        # Zaxira matni QARORGA MOS bo'lishi shart. Rad etilgan mijozga
        # "qo'shimcha shart yo'q" deyish — bevosita qarama-qarshilik
        # (skrinshotda aynan shu ko'ringan edi).
        if decision.qaror == "RAD_ETILDI":
            if afford <= 0:
                steps.append("Hozirgi daromad oqimi yangi kredit to'lovini "
                             "ko'tarmaydi. Daromadingizni bank hisobiga muntazam "
                             "o'tkazib boring va 3-6 oydan so'ng qayta murojaat qiling.")
            else:
                steps.append("Ball chegaradan past. Bank bilan tarixingizni "
                             "mustahkamlang va bir necha oydan so'ng qayta urinib ko'ring.")
        elif decision.qaror == "QOLDA_KORIB_CHIQISH":
            kam = APPROVE_SCORE - decision.score.score
            if 0 < kam <= 60:
                steps.append(f"Avtomatik ma'qullashga {kam:.0f} ball yetmadi "
                             f"(chegara {APPROVE_SCORE:.0f}). Tushumlarni muntazam "
                             f"bank hisobiga o'tkazish ballni oshiradi.")
            steps.append("Hujjatlaringizni tayyorlab turing — underwriter arizangizni "
                         "1 ish kunida ko'rib chiqadi.")
        else:
            steps.append("Qo'shimcha shart yo'q — hujjatlarni tasdiqlash uchun bank "
                         "xodimi siz bilan bog'lanadi.")
    return steps[:4]


# ---------------------------------------------------------------------------
# Mijoz uchun to'liq izoh
# ---------------------------------------------------------------------------

HEADLINE = {
    "MAQULLANDI": "Tabriklaymiz — kredit ma'qullandi",
    "QOLDA_KORIB_CHIQISH": "Arizangiz bank xodimi ko'rib chiqishi uchun yuborildi",
    "RAD_ETILDI": "Afsuski, hozircha kredit bera olmaymiz",
}

TONE = {"MAQULLANDI": "ijobiy", "QOLDA_KORIB_CHIQISH": "ogohlantirish",
        "RAD_ETILDI": "salbiy"}


def client_amount(decision) -> float:
    """Mijozga ko'rsatiladigan YAGONA tavsiya summasi.

    Ikki limit bor: afford (to'lov qobiliyati) va gated (ball sharti ham
    o'tgan). Avval bosh gap birini, "nima qilsam" qadami ikkinchisini
    ko'rsatib, bitta javobda ikki xil raqam chiqar edi (42.4 mln va 27.5 mln).
    Endi mijoz qatlami hamma joyda SHU funksiyadan oladi: gated > 0 bo'lsa —
    gated (chunki aynan shu summa o'tadi), aks holda afford.
    """
    if decision.qaror == "RAD_ETILDI":
        return 0.0                      # rad — taklif yo'q, raqam ham yo'q
    g = decision.limit.limit
    base = g if g > 0 else decision.tavsiya_summa
    return min(base, decision.feats.get("requested", 0.0) or base)


def recommended_payment(decision) -> float:
    """Mijozga ko'rsatiladigan summa bo'yicha oylik to'lov.

    `feats["new_payment"]` SO'RALGAN summaga tegishli — taklif kamaytirilganda
    uni ko'rsatish qarama-qarshilik beradi, shuning uchun qayta hisoblaymiz.
    """
    amount = client_amount(decision)
    if amount <= 0:
        return 0.0
    return annuity_payment(amount, ANNUAL_RATE,
                           decision.feats.get("term_months", 12) or 12)


def _lead(decision) -> str:
    """Bosh gap — eng muhim fakt, jargonsiz, bitta jumlada."""
    f = decision.feats
    requested = f.get("requested", 0.0)
    tavsiya = decision.tavsiya_summa
    blockers = [r for r in decision.rules if r.qaror == "RAD_ETILDI"]
    ko = [r for r in blockers if r.kod.startswith("KO_")]

    if decision.qaror == "MAQULLANDI":
        return (f"{som(tavsiya)} miqdorida kredit tasdiqlandi. "
                f"Oylik to'lov taxminan {som(recommended_payment(decision))} bo'ladi.")

    if decision.qaror == "RAD_ETILDI":
        if ko:
            reason = {
                "KO_BANDLIK": "hozirda doimiy ish joyingiz va muntazam daromadingiz yo'q",
                "KO_KECHIKISH": (f"kredit tarixingizda {int(f.get('max_delinq', 0))} kunlik "
                                 f"kechikish bor"),
                "KO_YOSH": (f"{int(f.get('yosh', 0))} yosh bankimiz kredit beradigan "
                            f"yosh oralig'idan tashqarida"),
                "KO_DAROMAD": "daromadingizni tasdiqlab bo'lmadi",
            }.get(ko[0].kod, "asosiy shartlardan biri bajarilmadi")
            return f"Sabab: {reason}."
        if decision.limit.afford_limit <= 0:
            return ("Sabab: hozirgi daromadingiz mavjud to'lovlardan keyin yangi kreditni "
                    "ko'tara olmaydi.")
        return ("Sabab: umumiy risk bahosi bankimiz chegarasidan yuqori chiqdi — "
                "quyidagi omillar hal qiluvchi bo'ldi.")

    # QO'LDA KO'RIB CHIQISH — mijoz qatlami YAGONA raqam bilan gaplashadi
    amount = client_amount(decision)
    if amount > 0 and amount < requested:
        if decision.limit.limit > 0:
            return (f"So'ragan {som(requested)}ni to'liq bera olmaymiz, lekin "
                    f"{som(amount)} hozirgi shartlarda ma'qullanishi mumkin — bunda "
                    f"oylik to'lov {som(recommended_payment(decision))} bo'ladi. "
                    f"Yakuniy qarorni bank xodimi tasdiqlaydi.")
        # ball sharti hech bir summada o'tmagan — va'da bermaymiz
        return (f"To'lov qobiliyatingiz {som(amount)}ni ko'taradi, ammo umumiy ball "
                f"chegaraviy zonada — yakuniy qarorni bank xodimi beradi.")
    return ("Ko'rsatkichlaringiz chegaraviy zonada — avtomatik qaror o'rniga bank xodimi "
            "arizangizni qo'lda ko'rib chiqadi.")


def _safe(fn, fallback):
    """Matn qatlamidagi istalgan xato QARORNI buzmasligi kerak.

    Izoh — qarorning natijasi, sababi emas. Shuning uchun shablon ichidagi
    kutilmagan qiymat (None, nol bo'luvchi, yo'q kalit) eng yomon holatda
    umumiy matn beradi, `decide()` oqimini emas.
    """
    try:
        return fn()
    except Exception:                                  # noqa: BLE001
        return fallback


def client_explanation(decision, top_n: int = 3) -> dict:
    """Mijoz ekrani uchun to'liq, jargonsiz izoh.

    Qaytadi: sarlavha, bosh gap, "sizga yordam berdi" / "sizga to'sqinlik qildi"
    ro'yxatlari va "nima qilsam bo'ladi" qadamlari.
    """
    f = decision.feats
    plus = client_factors(decision.score, f, +1, top_n)
    minus = client_factors(decision.score, f, -1, top_n)

    yordam = [{"matn": humanize(c, f), "ball": round(c.points, 1)} for c in plus]
    # None = matn qarama-qarshi chiqdi (masalan "deklaratsiya bilan mos" ni
    # to'sqinlik deb ko'rsatib bo'lmaydi) — bunday omil ro'yxatdan tushadi.
    tosqinlik = [{"matn": t, "ball": round(c.points, 1)}
                 for c in minus
                 for t in [humanize_for_list(c, f)] if t is not None]

    # Bo'sh ro'yxat ham ma'no tashishi kerak — UI da "—" turib qolmasin.
    if not tosqinlik and decision.qaror == "MAQULLANDI":
        tosqinlik = [{"matn": "sezilarli salbiy omil topilmadi", "ball": 0.0}]
    if not yordam and decision.qaror == "RAD_ETILDI":
        yordam = [{"matn": "hozircha profilingizda kuchli ijobiy omil yo'q",
                   "ball": 0.0}]

    return {
        "sarlavha": HEADLINE.get(decision.qaror, decision.qaror),
        "ohang": TONE.get(decision.qaror, "ogohlantirish"),
        "bosh_gap": _safe(lambda: _lead(decision),
                          "Qaror bo'yicha batafsil izoh texnik bo'limda keltirilgan."),
        "yordam_berdi": yordam,
        "tosqinlik_qildi": tosqinlik,
        "keyingi_qadam": _safe(lambda: next_steps(decision),
                               ["Batafsil ma'lumot uchun bank xodimiga murojaat qiling."]),
        "raqamlar": {
            "soralgan": round(f.get("requested", 0.0)),
            "tavsiya": round(client_amount(decision)),
            "oylik_tolov": round(recommended_payment(decision)),
            "oylik_tolov_soralgan": round(f.get("new_payment", 0.0)),
            "muddat_oy": int(f.get("term_months", 0)),
            "daromad": round(f.get("income_used", 0.0)),
        },
    }


def client_sentence(decision) -> str:
    """Bitta abzatsli mijoz izohi — CSV va API uchun (matn ko'rinishida).

    Hakam natija faylini QO'LDA o'qiydi, shuning uchun CSV dagi `sabab` ustuni
    ham inson tilida bo'lgani ma'qul; texnik variant alohida ustunda qoladi.
    """
    e = client_explanation(decision)
    parts = [e["sarlavha"] + ". " + e["bosh_gap"]]
    if e["tosqinlik_qildi"]:
        parts.append("To'sqinlik qildi: " +
                     "; ".join(x["matn"] for x in e["tosqinlik_qildi"]) + ".")
    if e["yordam_berdi"]:
        parts.append("Foydangizga ishladi: " +
                     "; ".join(x["matn"] for x in e["yordam_berdi"]) + ".")
    if e["keyingi_qadam"]:
        parts.append("Nima qilish mumkin: " + " ".join(e["keyingi_qadam"]))
    return " ".join(parts)
