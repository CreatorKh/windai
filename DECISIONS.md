# DECISIONS.md — muhandislik qarorlari

CBU Coding Hackathon 2026 · A2 — *Tushuntiriladigan kredit skoring va limit dvigateli*

Hujjat ikkita **majburiy** algoritmni batafsil, keyin bonus algoritmlarni va
arxitektura qarorlarini qisqacha yoritadi.

---

## 1. Majburiy algoritm #1 — DTI / PTI hisobi

**Kod:** [`app/features.py`](app/features.py) → `dti_pti()`, `annuity_payment()`
**Testlar:** [`tests/test_features.py`](tests/test_features.py) (8 ta test)

### Nega shunday

Qarz yuklamasi nisbati kredit qarorining eng eski va eng barqaror o'lchovi.
Uchta nisbatni alohida hisoblaymiz, chunki ular **turli savollarga** javob
beradi va underwriter ularni aralashtirmasligi kerak:

| Ko'rsatkich   | Formula                                   | Savol |
|---------------|-------------------------------------------|-------|
| `dti_current` | mavjud to'lovlar / daromad                | Mijoz hozir qanchalik yuklangan? |
| `pti`         | yangi to'lov / daromad                    | Yangi kredit o'zi qanchalik og'ir? |
| `dti`         | (mavjud + yangi) / daromad                | Kredit berilgandan keyin qanday bo'ladi? |

Yangi to'lov **annuitet formulasi** bilan hisoblanadi
(`P = S·i / (1 − (1+i)^(−n))`), so'ralgan summani muddatga bo'lish bilan emas —
aks holda uzoq muddatli kreditlarda foiz e'tibordan chetda qolib, DTI
sun'iy ravishda past chiqadi va 60 oylik ariza 6 oylikdan "arzonroq"
ko'rinadi.

**Daromad qaysi manbadan olinadi.** Deklaratsiya va bank oqimidan
konservativ kesishma olinadi:

```
income = clamp(median(bank kirimi),  0.5 × deklaratsiya,  1.5 × deklaratsiya)
```

Sabab: sof deklaratsiyaga ishonish — o'zini oshirib ko'rsatishga ochiq eshik;
sof bank oqimiga ishonish esa naqd iqtisodiyotda ishlaydigan mijozni
nohaq jazolaydi. Ikkalasining nisbati (`income_gap`) alohida belgi sifatida
modelga beriladi — u kuchli signal bo'lib chiqdi.

**Mavjud yuk** ariza maydoni (`mavjud_oylik_yuk`) va kredit registri
(`existing_loans.csv` faol kreditlar yig'indisi) dan **kattarog'i** olinadi.
Ikkalasi kelishmasa, ehtiyotkor variant tanlanadi.

### Big-O

**O(1)** vaqt, **O(1)** xotira. Bitta ariza uchun bir nechta arifmetik amal.
Butun test to'plami (540 ariza) uchun bu qism o'lchanadigan vaqt olmaydi.

### Chekka holatlar

| Holat | Xatti-harakat | Nega |
|---|---|---|
| `daromad = 0` yoki manfiy | `dti = pti = 1.0`, `income_missing = 1` | `ZeroDivisionError` yoki `inf` o'rniga aniq "maksimal xavf" qiymati. `inf` keyinchalik binning'da NaN ga aylanib, jimgina modelni buzardi. |
| Manfiy to'lov qiymatlari | `max(0, ...)` bilan qisqartiriladi | Buzuq CSV satri qarzni "kamaytirib" yubormasin. |
| Juda katta yuk | 5.0 (500%) da shiftlanadi | Outlier WOE bucket'ini buzmasin. |
| `muddat <= 0` | To'liq summa bir to'lovda | Nolga bo'lishdan himoya. |
| Annuitetda `i = 0` | `S / n` ga tushadi | `(1+i)^(−n) = 1` bo'lib, maxraj nolga aylanadi. |

### Ishlatilgan pattern

**Pure function** — global holat yo'q, kirish → chiqish. Shu sababli
`max_limit()` uni sekundiga minglab marta xavfsiz chaqira oladi va
har bir chaqiruv takrorlanuvchan (testda ham, prodda ham bir xil).

---

## 2. Majburiy algoritm #2 — Cash-flow tahlili

**Kod:** [`app/features.py`](app/features.py) → `cash_flow()`, `median()`, `stdev()`
**Testlar:** [`tests/test_features.py`](tests/test_features.py) (9 ta test)

### Nega shunday

12 oylik bank oqimidan **daraja** emas, **barqarorlik** o'lchanadi:

```
income_median = median(kirim)                      # outlier'ga chidamli daraja
income_cv     = stdev(kirim) / mean(kirim)         # o'zgaruvchanlik
income_trend  = median(oxirgi 6 oy) / median(birinchi 6 oy)
burn_ratio    = mean(chiqim) / mean(kirim)
cash_ratio    = mean(naqd_yechish) / mean(kirim)
buffer_months = mean(oy oxiri qoldiq) / mean(chiqim)
zero_months   = kirim = 0 bo'lgan oylar soni
```

**Nega median, o'rtacha emas.** Bitta bonus oyi yoki bir martalik tushum
o'rtachani 30-40% ga surib yuboradi va to'lov qobiliyatini oshirib
ko'rsatadi. Median bunga sezgir emas.

**Nega CV, sof `stdev` emas.** Standart chetlanish daromad darajasiga
bog'liq: 10 mln so'mlik maoshda ±500k normal, 1 mln so'mlikda — falokat.
CV = σ/μ o'lchamsiz bo'lgani uchun turli daromad darajalarini bir shkalada
taqqoslaydi. Ochiq datasetda bu ikki rejimni aniq ajratdi: budjet maoshi
(CV ≈ 0.03) va suzuvchi daromad (CV > 0.1) — shuning uchun `income_cv`
uchun qo'lda chegaralar berilgan (`CUTS_OVERRIDE`, quyida).

**Nega `zero_months` alohida.** Daromadning uzilishi CV ga qo'shilib
ketadi, lekin bank uchun bu boshqa hodisa: 2 oy daromadsizlik "o'zgaruvchan
daromad" emas, "ishdan ayrilish" signali.

### Big-O

**O(m log m)**, m = oylar soni (bu yerda doim 12) — median uchun saralash.
Xotira **O(m)**. m konstanta bo'lgani uchun amalda ariza boshiga O(1);
butun dataset uchun **O(n·m log m)** ≈ 2700 × 12 × log 12 → ~0.1 soniya.

Sof `numpy` siz stdlib da yozilgan: 12 elementli massivda vektorlash
foydasi manfiy (chaqiruv overhead'i hisobdan katta), Docker obrazi esa
~180 MB ga yengillashadi.

### Chekka holatlar

| Holat | Xatti-harakat | Nega |
|---|---|---|
| Oqim tarixi yo'q | Barcha nol, `flows_missing = 1`, `income_cv = 1.5` | Ma'lumot yo'qligi neytral emas — bu o'zi risk signali. |
| `mean(kirim) = 0` | CV = 1.5 (yuqori xavf) | `0/0` → NaN o'rniga aniq qiymat. |
| Bitta oy (n < 2) | `stdev = 0` → CV = 0 | Namunaviy dispersiya (n−1) aniqlanmagan; NaN qaytarish taqiqlangan. |
| Birinchi yarim yil medianasi 0 | `trend = 1.0` (neytral) | Nolga bo'lish. |
| Barcha nisbatlar | 1.5–3.0 oralig'ida shiftlangan | Bitta anomal satr WOE bucket chegaralarini surib yubormasin. |

### Ishlatilgan pattern

**Value object** — `cash_flow()` bitta o'zgarmas lug'at qaytaradi; chaqiruvchi
faqat kerakli kalitni oladi. Belgi qo'shish signaturani buzmaydi.

---

## 3. Bonus algoritmlar

### 3.1 WOE / IV binning — `app/binning.py`

```
WOE_i = ln( (bad_i/bad_total) / (good_i/good_total) )      Laplace α = 0.5
IV    = Σ_i (p_bad_i − p_good_i) · WOE_i
```

* **Kvantil (equal-frequency) binning**, teng kenglikdagi emas: daromad va DTI
  taqsimoti kuchli qiyshaygan, teng kenglik bo'sh bucket'lar beradi.
* **Laplace tekislash** — bucket'da 0 ta defolt bo'lsa `ln(0) = −∞` bo'lardi;
  α = 0.5 buni chekli ushlab turadi (test: `test_woe_chekli_son_har_doim`).
* **Kichik bucket'larni birlashtirish** — 3 ta kuzatuvli bucket ekstremal WOE
  beradi va modelni chalg'itadi. Sonli belgilarda chegara **nisbiy** (5%),
  kategoriyalarda esa **absolyut** (30 kuzatuv) — sababi quyida.
* **`CUTS_OVERRIDE` — domen bilimi.** Diskret belgilarda kvantil yaroqsiz.
  `max_delinq` amalda faqat {0, 15, 45, 95} qiymatlarini oladi va
  kuzatuvlarning 79% i nolda. Kvantil ularni bitta bucket'ga tiqib,
  90+ kun segmentini (defolt ulushi **27.9%**) yo'qotardi. Qo'lda berilgan
  Bazel kesimlari (1 / 30 / 90 kun) uni saqlaydi.
* Big-O: **O(n log n)** saralashga, **O(n)** taqsimlashga; bin izlash **O(k)**, k ≤ 6.

> **BUG #1 — jim sifat yo'qotishi.** Dastlab kategoriyalarga ham nisbiy 5% chegarasi
> qo'llanilgan edi. 2160 ta o'quv satrida bu 108 ta kuzatuv degani, `ishsiz`
> toifasida esa atigi **79** ta — u "kam uchraydigan" deb qo'shnisiga
> qo'shib yuborildi. Holbuki bu toifada defolt ulushi **63%** (portfel
> o'rtachasi 11.5%) va u IV 0.54 lik eng kuchli kategorik signal.
> Natijada test AUC 0.7493 → 0.7444, CV AUC 0.7959 → 0.7757 ga tushdi va
> hech qanday xato xabari chiqmadi. Xulosa: bucket birlashtirish mezoni
> **hajm** bo'yicha emas, **statistik barqarorlik** bo'yicha bo'lishi kerak —
> 79 ta kuzatuvda 63% bad-rate mutlaqo barqaror baho.
> Regressiya testi: `test_kichik_lekin_ajratuvchi_toifa_yutilmaydi`.

### 3.2 Logistik regressiya — `app/model.py`

WOE belgilar ustida **damped Newton (IRLS + step-halving line search)**,
L2 regulyarizatsiya bilan. Big-O: **O(iter · n · k²)** Gessian yig'ishga,
**O(iter · k³)** yechishga; k ≈ 16, iter ≈ 5–7.

> **BUG #2 — yaqinlashuvning portlashi.** Sof Newton (line search'siz)
> kredit ma'lumotlarida odatiy bo'lgan *quasi-complete separation* da
> portlaydi: `bandlik = ishsiz` belgisi defoltni juda kuchli ajratadi
> (defolt ulushi 63%), qadam oshib ketadi, p → 0/1, IRLS vazni
> w = p(1−p) → 0, Gessian singular bo'ladi va koeffitsientlar ~100 gacha
> o'sadi. Natija: barcha bashoratlar to'yinadi, **AUC 0.5 ga tushadi** —
> jim, ammo halokatli xato. Har qadamda jarima qo'shilgan log-ehtimollik
> kamayishini talab qilish (kerak bo'lsa qadamni ikkiga bo'lish) buni
> hal qildi: 50 iteratsiya / AUC 0.50 → **5 iteratsiya / AUC 0.79**.
> Regressiya testi: `tests/test_model.py::test_toliq_ajralishda_portlamaydi`.

**Tezlik.** Line search har bir yarimlashda `z` ni noldan hisoblasa, bu
O(n·k) turadi va Newton iteratsiyasida o'nlab marta takrorlanadi. Yo'nalish
bo'yicha hosila `dz = step · [1, x]` bir marta hisoblanib, har bir sinov
`z + t·dz` ga aylantirildi — bitta skorkarta o'rgatish **17.8 s → 0.54 s**
(33×), butun test to'plami 146 s → 18 s. Natija bit-ma-bit bir xil
(etalon implementatsiya bilan solishtirilganda koeffitsient farqi 2·10⁻¹⁶).

**Wrong-sign elimination.** WOE ta'rifi bo'yicha "WOE kattaroq ⇒ xavf
yuqoriroq", demak to'g'ri skorkartada **har bir β ≥ 0**. Manfiy β —
multikollinearlik alomati: model bir belgini boshqasini "tuzatish" uchun
teskari ishlatadi. Bu ballni biroz yaxshilashi mumkin, lekin **izohni
yolg'onga aylantiradi** ("DTI yuqori bo'lgani uchun +10 ball"). Shuning
uchun eng manfiy belgi olib tashlanib, model qayta o'rgatiladi. 21 nomzod
belgidan **15 tasi** qoldi; AUC deyarli o'zgarmadi, izoh esa halol bo'ldi.
Test: `test_barcha_beta_manfiy_emas`, `test_hissa_belgisi_woe_ga_mos`.

### 3.3 Limit qidiruvi (binary search) — `app/limit.py`

```
ruxsat(S) = DTI(S) ≤ 50%  AND  PTI(S) ≤ 35%  AND  erkin_pul(S) ≥ 0
```

`ruxsat` **monoton**: S oshsa annuitet to'lov oshadi, nisbatlar faqat o'sadi.
Predikat `True…True False…False` ko'rinishida — binary search to'g'ri ishlaydi.
Big-O: **O(log(hi/step))** ≈ 13 iteratsiya (500 mln so'm / 100k qadam).

> **BUG #3 — nozik joy.** Skorkarta bali WOE bucket'lar tufayli **pillapoya funksiya**
> va monotonligi kafolatlanmagan. Uni binary search predikatiga qo'shish —
> jim xato manbai: monoton bo'lmagan predikatda binary search noto'g'ri
> javob beradi va buni hech kim sezmaydi. Shuning uchun ball/PD sharti
> qidiruvdan **keyin**, chegaralangan "qo'riqchi" tushish bilan tekshiriladi.
>
> Birinchi versiyada qo'riqchi ball darvozasi hech qachon ochilmaydigan
> holatda limitni 0 ga surib yuborardi — 540 arizadan atigi **1 tasi**
> ma'qullangan edi. Endi to'lov qobiliyati limiti (`afford_limit`) alohida
> saqlanadi: "siz 3.4 mln so'm ko'tara olasiz, lekin ball darvozasi yopiq"
> — bu ikki xil xabar va ular aralashmasligi kerak.

Testlar brute-force bilan solishtiradi va **bir qadam yuqorisi allaqachon
cheklovni buzishini** tekshiradi — ya'ni topilgan qiymat haqiqatan maksimal.

---

## 4. Ball shkalasi va kalibrovka

```
factor = PDO / ln 2
score  = BASE_SCORE + factor · ( ln(odds) − ln(BASE_ODDS) )
       = neytral_tayanch + Σ_j ( −factor · β_j · WOE_j )
                            \____ omil hissasi ____/
```

Ball — omillar hissasining **aniq yig'indisi**, approksimatsiya emas
(SHAP/LIME kabi taxminiy usul kerak emas: model chiziqli, dekompozitsiya
matematik jihatdan to'liq). Test `test_hissalar_yigindisi_ballni_beradi`
buni har bir arizada 1e-6 aniqlikda tekshiradi.

**`BASE_ODDS = 8`, `BASE_SCORE = 600`, `PDO = 20`.** Boshida
`BASE_ODDS = 50` (kitobiy qiymat) qo'yilgan edi — natijada butun portfel
600 ballning ostiga tushdi va 620 chegarasi hech kimni o'tkazmadi
(540 dan 1 ta ma'qullash). Portfelning haqiqiy odds i 7.7:1 (defolt
ulushi 11.5%), shkala shunga bog'landi.

**Chegaralar taqsimotdan tanlangan, "chiroyli son" bo'lgani uchun emas:**

| Ball oralig'i | Arizalar | Haqiqiy defolt |
|---|---|---|
| < 580 | 88 | **31.8%** |
| 580–600 | 68 | 13.2% |
| 600–630 | 205 | 5.9% |
| ≥ 630 | 179 | **3.9%** |

580 — risk sakraydigan haqiqiy uzilish nuqtasi (13% → 32%), shuning uchun
`REVIEW_SCORE`. `APPROVE_SCORE = 630`.

---

## 5. Qaror siyosati: nega DTI oshishi RAD emas

Birinchi versiyada DTI/PTI shiftidan oshish avtomatik rad edi. Bu
**mahsulot xatosi**: mijoz 100 mln so'm so'radi, 30 mln ko'tara oladi —
to'g'ri javob "yo'q" emas, **kamaytirilgan taklif**. Endi:

1. **Knock-out** (yosh, 90+ kun kechikish, ishsizlik, daromad yo'q) → rad.
2. **Risk darvozasi** (ball < 580 yoki PD > 20%) → rad.
3. **DTI/PTI shifti** → to'lov qobiliyati bor bo'lsa counter-offer (qo'lda
   ko'rib chiqish), bo'lmasa rad.
4. Ball 580–630 → qo'lda ko'rib chiqish.
5. Aks holda → ma'qullash.

Natija ochiq datasetda (540 test arizasi):

| Qaror | Soni | Haqiqiy defolt |
|---|---|---|
| Ma'qullandi | 151 | **4.0%** |
| Qo'lda ko'rib chiqish | 267 | 5.6% |
| Rad etildi | 122 | **28.7%** |

Test `test_maqullanganlar_rad_etilganlardan_xavfsizroq` bu tartibni
qo'riqlaydi.

---

## 6. Baza: o'zgarmas jurnal va SCD Type 2

**Kod:** [`app/db.py`](app/db.py) · **Testlar:** [`tests/test_db.py`](tests/test_db.py)

### Immutability — ikki qatlamli

1. **SQLite trigger'lari** `decision_journal` ustida `UPDATE` va `DELETE` ni
   `RAISE(ABORT)` bilan bloklaydi. ORM chetlab o'tolmaydi — qoida bazaning
   o'zida.
2. **Hash zanjiri**: har bir yozuv `prev_hash` orqali oldingisiga bog'langan
   (`SHA-256`). Kimdir trigger'ni o'chirib satrni almashtirsa ham,
   `verify_chain()` buzilgan yozuvning aniq `id` sini ko'rsatadi.

> Nega ikkalasi ham kerak: trigger *tasodifiy* buzilishdan himoya qiladi,
> hash zanjiri esa *ataylab* buzilishni **oshkor qiladi**. Regulyator uchun
> muhimi — ikkinchisi. Test `test_zanjir_buzilishini_topadi` trigger'ni
> ataylab o'chirib, "ichki buzg'unchi" ni modellashtiradi.

### SCD Type 2

`scorecard_version(version, payload, valid_from, valid_to, is_current)`.
Yangi versiya ochilganda eskisi **yopiladi, o'chirilmaydi**. Har bir qaror
`version_id` ni saqlaydi, shuning uchun eski qarorni **ayni o'sha eski
skorkarta bilan** qayta hisoblash mumkin: `engine.rescore_with_version()`
→ UI dagi "Versiyalarni taqqoslash" ekrani (omil-omil ball farqi bilan).

Qayta hisoblash jurnalga **yozilmaydi** — bu "nima bo'lardi" tahlili, tarix
o'zgarmas bo'lib qoladi.

---

## 6a. Ko'p oqimli xavfsizlik — eng qimmat bug

Server demo paytida 30–60 soniyada jim o'lardi. Uzunroq tekshiruvda sabab
topildi: `EXIT_STATUS=139`, ya'ni **SIGSEGV**. To'liq stek:

```
Thread 1 Crashed:
0  libsqlite3.dylib  sqlite3DbMallocRawNNTyped + 52
1  libsqlite3.dylib  sqlite3VdbeMemGrow + 184
3  libsqlite3.dylib  sqlite3GenerateColumnNames + 152
8  libsqlite3.dylib  sqlite3LockAndPrepare + 224
9  _sqlite3.cpython-39-darwin.so
```

Sabab: `CreditEngine` BITTA `sqlite3.Connection` obyektini saqlar va uni
`check_same_thread=False` bilan ochar edi. Bu bayroq — **faqat Python
darajasidagi tekshiruvni o'chiradi**; C darajasida hech qanday himoya
bermaydi. FastAPI esa `def` (sync) endpointlarni **threadpool** da bajaradi,
ya'ni parallel so'rovlar ayni bir ulanishga tushib, sqlite ichki holatini
buzardi.

Bu — hakatonda eng qimmat turdagi xato: testlar yashil, bir foydalanuvchi
qo'lda bosganda hammasi ishlaydi, lekin hakam sahifani yangilagan yoki ikki
kishi bir vaqtda ochgan zahoti server qulaydi.

**Yechim** (`app/db.py::Database`):
* ulanish `threading.local()` orqali **har bir oqimga alohida** ochiladi;
* yozuvlar `write_lock` bilan ketma-ketlashtiriladi — hash zanjiri uchun
  "oxirgi hash ni o'qish + yangi satr qo'shish" atomar bo'lishi shart;
* o'qishlar WAL rejimida parallel ketaveradi, `busy_timeout = 30s`.

**Tekshiruv:** 10 o'quvchi + 4 yozuvchi oqim, 0 xato, zanjir butun
(`tests/test_db.py::test_kop_oqimda_qulamaydi` — tuzatishdan oldin bu test
pytest ni segfault bilan o'ldirardi). HTTP darajasida: 120 parallel so'rov,
server tirik.

---

## 6b. Izohning ikki qatlami

`Decision.sabab` (texnik) va `app/explain.py::client_explanation()` (mijoz tili)
bir manbadan chiqadi, lekin ikki xil auditoriyaga mo'ljallangan:

| | Texnik | Mijoz |
|---|---|---|
| Kim o'qiydi | underwriter, regulyator, audit | ariza beruvchi |
| Namuna | "DTI 52.7% — shift 50.0%; taklif 39 500 000" | "So'ragan 45 mln ni to'liq bera olmaymiz, lekin 39.5 mln to'lov qobiliyatingizga to'g'ri keladi" |
| Qayerda | jurnal, `sabab_texnik` ustuni, UI ning yig'iladigan bo'limi | UI ning asosiy bloki, CSV dagi `sabab` |

Har bir omil uchun ikkita ifoda yozilgan (ijobiy/salbiy) va ular haqiqiy
raqamni ichiga oladi: "erkin pul yuqori" emas, "to'lovlardan keyin oyiga
5 477 232 so'm qoladi".

Qo'shimcha: **"Nima qilsam bo'ladi?"** — har bir rad yoki chegaraviy javob
amaliy qadam bilan tugaydi (qaysi summa o'tadi, muddatni uzaytirish, mavjud
kreditni yopish, stajni to'ldirish). Rad javobi "yo'q" bilan tugamaydi.

Testlar buni qo'riqlaydi: `test_mijoz_izohida_jargon_yoq` mijoz matnida
"DTI", "WOE", "PD", "shift" kabi atamalar yo'qligini,
`test_har_bir_belgi_uchun_inson_ifodasi_bor` esa `FEATURE_SPEC` ga yangi
belgi qo'shilganda matni ham yozilganini tekshiradi.

---

## 6c. Himoyalangan belgilar va adolat (fairness)

| Belgi | Modelda | Nega |
|---|---|---|
| `jins` | **nomzod ham emas** | `FEATURE_SPEC` ga umuman kiritilmagan — "IV filtri tashlab yuboradi" degandan kuchliroq kafolat. |
| `viloyat` | **nomzod ham emas** | Xuddi shunday: hududiy kamsitish uchun eshik ochmaymiz. |
| `yosh` | **reyting omili EMAS**, faqat layoqat chegarasi | Pastga qarang. |
| `bandlik` | ha | Bu — daromad barqarorligi o'lchovi, himoyalangan toifa emas. |

**Nega `yosh` olib tashlandi.** U modelda qolganida ballga **14.9 ball**
ta'sir qilardi (27 yoshgacha −7.6, 49–56 oralig'ida +7.3), va ma'qullash
nisbati yoshlar / 50+ = **0.51** bo'lardi — ya'ni AQSh amaliyotidagi 4/5
qoidasidan ancha past. Holbuki ochiq datasetda **yoshlarning haqiqiy
defolti past**: 30 gacha 8.45%, 50+ 9.58%. Ya'ni model yoshlarni haqiqiy
xavf uchun emas, korrelyatsiya uchun jazolardi. Olib tashlash AUC ni
yomonlashtirmadi (o'lchov: 0.7657 → 0.7666).

Yosh **layoqat** (eligibility) sharti sifatida qoladi: 18–70 oralig'idan
tashqarida kredit berilmaydi (`KO_YOSH`) — bu reyting emas, huquqiy talab.

> Himoyada aniq formulirovka: *"yoshni reyting omili sifatida
> ishlatmaymiz; qolgan farq daromad va staj kabi haqiqiy risk
> omillarining yosh bilan korrelyatsiyasidan kelib chiqadi"*. To'liq
> paketda o'lchangan adverse impact ratio **0.799** — bu 4/5 chegarasiga
> teng, undan yuqori emas, shuning uchun "0.80 dan yuqori" deb va'da
> berilmaydi.

**`dti_current` qo'shildi.** Belgi allaqachon hisoblanardi (`features.py`),
lekin skorkartaga ulanmagan edi. Uni qo'shish o'lchangan yutuq berdi:
AUC 0.7493 → **0.7675**, Gini 0.4986 → 0.5349, KS 0.4460 → 0.4796,
CV AUC 0.7959 → 0.8033. Kollinearlik yuzaga kelmadi (barcha beta ≥ 0
saqlanib qoldi). `dti` bilan chalkashmasligi uchun nomlar aniq ajratildi:
"Umumiy qarz yuki (yangi kredit bilan)" va "Mavjud qarz yuki (yangi
kreditsiz)".

---

## 7. Arxitektura qarorlari

| Qaror | Nega |
|---|---|
| **Yadro stdlib da** (numpy/pandas/sklearn yo'q) | Docker obrazi yengil, natija bit-ma-bit takrorlanuvchan, versiya konfliktlari yo'q. Belgilar soni ~20, oylar 12 — vektorlash foydasi yo'q. |
| **SQLite, ORM siz** | Bitta fayl, migratsiya yo'q, trigger'lar to'g'ridan-to'g'ri sxemada ko'rinadi. |
| **Frontend build qadamisiz** | Vanilla JS + bitta CSS. `npm install` yo'q — `docker compose up` bitta buyruq bo'lib qoladi. Uslub — FindDroppers dizayn tizimi (Inter Variable, `#d1fe17`, radius 0, hard-shadow). |
| **Facade pattern** (`CreditEngine`) | API va CLI bitta biznes mantiqdan foydalanadi — pipeline va veb qarorlari farq qilmaydi. |
| **Strategy pattern** (`FEATURE_SPEC`) | Belgi qo'shish = ro'yxatga bitta satr; binning va scorecard avtomatik moslashadi. `/api/scorecard/retrain` cheklangan belgi to'plami bilan yangi versiya o'rgata oladi. |
| **Repository pattern** (`app/db.py`) | SQL bitta modulda; qolgan kod `sqlite3` ni ko'rmaydi. |

---

## 8. Nima qilinmadi (va nega)

* **Gradient boosting** — AUC ni ~0.01–0.02 ga ko'tarishi mumkin edi, lekin
  mavzuning asosiy talabi izohlanuvchanlik. Chiziqli skorkartada hissalar
  yig'indisi **aniq**, GBM da esa SHAP taxminiy va sekin.
* **Kalibrovkani izotonik regressiya bilan yaxshilash** — Brier 0.080 allaqachon
  maqbul, vaqt boshqa joyga ketdi.
* **Foydalanuvchilar/rollar** — MVP doirasidan tashqarida.

---

## 9. Sifat ko'rsatkichlari

Ochiq datasetning **yopiq** test qismida (540 ariza, javob kaliti bilan):

| Metrika | Qiymat |
|---|---|
| AUC-ROC | **0.7675** |
| Gini | **0.5349** |
| KS | 0.4796 |
| Brier | 0.0782 |
| 5-fold CV AUC (train) | 0.8033 |
| **Shift** (haqiqiy PD ning o'zi bergan AUC) | 0.8042 |

Oxirgi satr muhim: natijalar PD dan tasodifiy chiqarilgani uchun **hech
qanday model 0.804 dan oshib keta olmaydi**. 0.7675 — bu shiftning **95%** i.

Testlar: **138 ta**, `make test` ≈ 18 soniya.
