# WINDAI — Tushuntiriladigan kredit skoring va limit dvigateli

CBU Coding Hackathon 2026 · mavzu **A2**

Ariza asosida kredit qarorini chiqaradi va **har bir qarorni omillar hissasi
bilan izohlaydi**: nega +14 ball, nega −18 ball. Rad javobi hech qachon
sababsiz chiqmaydi.

```
Ariza formasi  →  Skorkarta (WOE + logistik regressiya)  →  Qaror + sabab
                            ↓                                     ↓
                  Limit (binary search)              O'zgarmas jurnal (hash zanjiri)
```

---

## Ishga tushirish

### Docker (tavsiya etiladi)

```bash
docker compose up --build
```

`batch` xizmati skorkartani o'rgatadi va `natija/kredit_qarorlari.csv` ni
yozadi, so'ng `web` ko'tariladi → **http://localhost:8000**

### Make

```bash
make run
```

(`make batch` — faqat natija fayli; `make serve` — faqat server;
`make test` — testlar; `make help` — barcha buyruqlar.)

### Qo'lda

```bash
pip install -r requirements.txt
python -m app.pipeline --evaluate          # natija/kredit_qarorlari.csv
python -m uvicorn app.api:app --port 8000  # http://localhost:8000
```

Yadro (skoring, binning, model, limit) **sof stdlib** da — `numpy`, `pandas`,
`sklearn` kerak emas. `requirements.txt` faqat HTTP qatlami va testlar uchun.

---

## Kirish (rollar)

Sahifa ochilganda login ekrani chiqadi. Demo hisoblar ekranning o'zida
ko'rsatilgan — istalgan kartochkani bossangiz kifoya:

| Login | Parol | Rol | Nima qila oladi |
|---|---|---|---|
| `aziza` | `aziza123` | Mijoz menejeri | ariza yuboradi, mijoz kartasi, what-if |
| `bekzod` | `bekzod123` | Underwriter | + qarorlar oqimi, portfel, skorkarta |
| `dilnoza` | `dilnoza123` | Risk menejeri | + skorkartani qayta o'rgatish |
| `admin` | `admin123` | Administrator | + xom audit jurnali, foydalanuvchilar |

Ruxsati yo'q bo'limlar yashirilmaydi — qulf bilan bloklanadi, shunda rol
modeli ko'rinib turadi. Har bir qaror jurnalga **kim** chiqargani bilan
yoziladi va bu hash zanjiriga kiradi.

---

## Natijalar

Ochiq datasetning test qismida (540 ariza, `_javob_kaliti` bilan tekshirilgan):

| Metrika | Qiymat |
|---|---|
| **AUC-ROC** | **0.7675** |
| **Gini** | **0.5349** |
| KS | 0.4796 |
| Brier | 0.0782 |
| 5-fold CV AUC (train) | 0.8033 |
| Shift — haqiqiy PD ning AUC si | 0.8042 |

Natijalar PD dan tasodifiy chiqarilgani uchun hech qanday model **0.8042** dan
oshib keta olmaydi; 0.7675 — bu shiftning **95%** i.

Qarorlarning haqiqiy natija bilan mosligi:

| Qaror | Soni | Haqiqiy defolt |
|---|---|---|
| Ma'qullandi | 151 | **4.0%** |
| Qo'lda ko'rib chiqish | 267 | 5.6% |
| Rad etildi | 122 | **28.7%** |

Ball bandlari bo'yicha (test to'plami):

| Ball | Arizalar | Haqiqiy defolt |
|---|---|---|
| < 580 | 79 | **39.2%** |
| 580–600 | 61 | 11.5% |
| 600–630 | 193 | 5.2% |
| >= 630 | 207 | **3.9%** |

---

## Ekranlar

**http://localhost:8000** — beshta ekran:

1. **Ariza formasi** *(mijoz tomoni)* — uchta **tayyor demo senariysi**
   (ishonchli mijoz / chegaraviy holat / yuqori xavf) bir bosishda uch xil
   qarorni ko'rsatadi. Yuborilgach: qaror **sodda tilda**, "nima qilsam
   bo'ladi" qadamlari, "yordam berdi / to'sqinlik qildi" ro'yxatlari va
   yig'iladigan **texnik tafsilot** (ball, waterfall, DTI/PTI, qoidalar).
2. **Underwriter paneli** *(bank tomoni)* — **portfel kesimi** (ball oshgani
   sari haqiqiy defolt ulushi qanday tushishi — skorkarta ishlayotganining
   bitta rasmdagi isboti), holdout metrikalari va qaror sifati, qarorlar
   oqimi, tanlangan ariza bo'yicha to'liq kesim: omillar hissasi, 12 oylik
   kirim grafigi, mavjud kreditlar, qarorlar tarixi hash'lari bilan.
3. **Skorkarta** — har bir belgining IV si, kuchi, β koeffitsienti va WOE
   bucket'lari (bad-rate bilan).
4. **What-if** *(bonus)* — daromadni/summani/yukni surganda ball, PD va
   **maksimal limit** qanday o'zgarishini real vaqtda ko'rsatadi.
5. **Versiyalar & jurnal** *(bonus)* — SCD Type 2 versiyalar jadvali, yangi
   versiya o'rgatish, bitta arizani ikki skorkarta bilan **omil-omil
   taqqoslash**, hash zanjiri holati.

---

## Natija fayli

`natija/kredit_qarorlari.csv` — barcha 540 test arizasi, ustunlar:
(`natija/metrikalar.json` — holdout AUC/Gini/KS va qaror sifati, UI shu fayldan o'qiydi)

| Ustun | Tavsif |
|---|---|
| `application_id` | Test arizasi ID si |
| `score` | Skorkarta bali (300–900) |
| `pd` | Defolt ehtimoli (0–1) |
| `qaror` | `MAQULLANDI` / `QOLDA_KORIB_CHIQISH` / `RAD_ETILDI` |
| `sabab` | **Inson tilida** izoh: nima bo'ldi, nega, nima qilish mumkin (hech qachon bo'sh emas) |
| `sabab_texnik` | Underwriter/regulyator uchun: foizlar, chegaralar, ball hissalari |
| `asosiy_omil` | Eng kuchli salbiy omil va uning ball hissasi |
| `tavsiya_summa`, `limit` | Tavsiya etilgan summa va hisoblangan limit |
| `dti`, `pti`, `income_cv` | Majburiy algoritmlarning chiqishi |
| `scorecard_version` | Qaysi skorkarta versiyasi ishlatilgan |

---

## Algoritmlar

**Majburiy**

| Algoritm | Kod | Big-O |
|---|---|---|
| DTI / PTI / mavjud DTI (annuitet to'lov bilan) | `app/features.py::dti_pti` | O(1) |
| Cash-flow: median, CV, trend, burn | `app/features.py::cash_flow` | O(m log m), m = 12 |

**Bonus**

| Algoritm | Kod | Big-O |
|---|---|---|
| WOE / IV binning | `app/binning.py` | O(n log n) |
| Logistik regressiya (damped Newton, L2) | `app/model.py` | O(iter·n·k²) |
| Limit qidiruvi (binary search) | `app/limit.py` | O(log(hi/step)) ≈ 13 iter |

Batafsil — **[DECISIONS.md](DECISIONS.md)**: nega shunday, chekka holatlar,
ishlatilgan pattern'lar va yo'l davomida topilgan uchta jiddiy bug.

---

## Baza

`kredit.db` (SQLite) — **ariza → qaror → tarix** zanjiri:

* `decision_journal` — **o'zgarmas**: `UPDATE`/`DELETE` SQLite trigger'lari
  bilan bloklangan, ustiga **SHA-256 hash zanjiri** (`prev_hash`), shuning
  uchun trigger chetlab o'tilsa ham buzilish oshkor bo'ladi.
* `scorecard_version` — **SCD Type 2** (`valid_from` / `valid_to` /
  `is_current`). Eski qaror **ayni o'sha eski versiya bilan** qayta
  hisoblanadi (UI dagi taqqoslash ekrani).
* `decision_factor` — har bir qarorning omil-omil hissasi (audit uchun).

---

## API

| Endpoint | Tavsif |
|---|---|
| `POST /api/ariza` | Ariza → qaror (jurnalga yoziladi) |
| `POST /api/simulyatsiya` | What-if: hisoblaydi, **yozmaydi** |
| `GET  /api/arizalar` | Qarorlar ro'yxati (filtr bilan) |
| `GET  /api/ariza/{id}` | To'liq kesim + qarorlar tarixi |
| `GET  /api/ariza/{id}/taqqoslash?a=1&b=2` | Ikki versiyani omil-omil solishtirish |
| `GET  /api/scorecard` | IV jadvali, β koeffitsientlar, metrikalar |
| `GET  /api/scorecard/versions` | SCD Type 2 versiyalar |
| `POST /api/scorecard/retrain` | Yangi versiya o'rgatish |
| `GET  /api/jurnal` | Hash zanjiri holati + statistika |

Interaktiv hujjat: **http://localhost:8000/docs**

---

## Testlar

```bash
make test
```

**138 ta test**, ~18 soniya. Muhimlari:

* `test_decision.py` — **izohlanuvchanlik shartnomasi**: har bir qarorda
  sabab bor; ball omillar hissasining aniq yig'indisi (1e-6 aniqlikda);
  WOE ishorasi ball ishorasiga mos.
* `test_limit.py` — binary search natijasi brute-force bilan mos va
  **bir qadam yuqorisi allaqachon cheklovni buzadi**.
* `test_db.py` — jurnalni o'zgartirib bo'lmaydi; trigger o'chirilsa ham
  hash zanjiri buzilishni topadi.
* `test_model.py` — to'liq ajralishda koeffitsientlar portlamaydi
  (regressiya testi).
* `test_pipeline.py` — barcha test arizalari faylda, qaytariluvchanlik,
  AUC chegarasi.
* `test_api.py` — HTTP qatlami uchdan-uchgacha: ariza → qaror → tarix,
  what-if jurnalga yozmaydi, retrain yangi SCD2 versiya ochadi.
* `test_explain.py` — mijoz matni: jargon yo'q, yosh/ma'lumot ishlatilmaydi,
  oylik to'lov tavsiya etilgan summaga mos, bajarib bo'lmaydigan va'da yo'q.
* `test_db.py::test_kop_oqimda_qulamaydi` — 6 o'quvchi + 3 yozuvchi oqim;
  tuzatishdan oldin bu test pytest ni **segfault** bilan o'ldirardi.

---

## Loyiha tuzilishi

```
app/
  config.py     siyosat chegaralari, kalibrovka — barcha sehrli sonlar
  loaders.py    CSV → indekslangan dataset
  features.py   MAJBURIY: dti_pti(), cash_flow()
  binning.py    WOE / IV binning
  model.py      logistik regressiya (damped Newton) + AUC/Gini/KS/Brier
  scorecard.py  binning + model → ball va omillar hissasi
  limit.py      binary search limit
  decision.py   knock-out + siyosat qoidalari → qaror va SABAB
  explain.py    qarorni MIJOZ TILIGA o'girish (ikkinchi izoh qatlami)
  db.py         SQLite: o'zgarmas jurnal + SCD Type 2
  engine.py     facade: API va CLI uchun yagona biznes mantiq
  api.py        FastAPI + statik frontend
  pipeline.py   CLI: o'rgatish → natija/kredit_qarorlari.csv
web/            frontend (build qadamisiz: HTML + CSS + vanilla JS)
tests/          138 ta test
data/a2_credit/ dataset
natija/         kredit_qarorlari.csv
```
