# ERD — ma'lumotlar sxemasi

Ikki qatlam: **dataset** (CSV, faqat o'qish) va **operatsion baza** (SQLite).
Yadro talab: ariza → qaror → tarix zanjiri, o'zgarmas jurnal, SCD Type 2 versiyalar.

```mermaid
erDiagram
    %% ==================== DATASET (CSV, faqat o'qish) ====================
    APPLICANTS {
        string applicant_id PK
        string ism
        string jins
        int yosh
        string viloyat
        string bandlik
        int ish_staji_oy
        int deklaratsiya_daromad
        int oila_azolari
        string talim
        int mijoz_boldi_oy
    }
    MONTHLY_FLOWS {
        string applicant_id FK
        string oy
        int kirim
        int chiqim
        int naqd_yechish
        int oy_oxiri_qoldiq
    }
    EXISTING_LOANS {
        string applicant_id FK
        string loan_id PK
        string bank
        int summa
        int oylik_tolov
        int qoldiq
        int max_kechikish_kun
        string status
    }

    %% ==================== OPERATSION BAZA (SQLite) ====================
    APPLICATION {
        string application_id PK
        string applicant_id FK
        string manba "dataset | web"
        json payload
        datetime created_at
    }
    SCORECARD_VERSION {
        int id PK
        string version UK
        json payload "binning + koeffitsientlar"
        json metrics "AUC, KS, Gini"
        datetime valid_from "SCD Type 2"
        datetime valid_to "NULL = amalda"
        bool is_current
    }
    DECISION_JOURNAL {
        int id PK
        string application_id FK
        int version_id FK
        string qaror
        float ball
        float pd
        text sabab
        float tavsiya_summa
        json payload "omillar hissasi bilan"
        string kim "qaror chiqargan xodim"
        datetime created_at
        string prev_hash "oldingi yozuv hashi"
        string hash "SHA-256 zanjir"
    }
    DECISION_FACTOR {
        int id PK
        int decision_id FK
        string kalit
        string bucket
        float woe
        float beta
        float ball "omil hissasi"
    }
    APP_USER {
        int id PK
        string login UK
        string ism
        string rol "4 rol, ruxsatlar to'plami"
        string parol_hash "pbkdf2 200k"
        string parol_salt
        bool faol
    }
    APP_SESSION {
        string token PK
        int user_id FK
        datetime last_seen "sliding 60 min"
    }

    APPLICANTS ||--o{ MONTHLY_FLOWS : "12 oylik oqim"
    APPLICANTS ||--o{ EXISTING_LOANS : "mavjud kreditlar"
    APPLICANTS ||--o{ APPLICATION : "ariza beradi"
    APPLICATION ||--o{ DECISION_JOURNAL : "ariza -> qaror -> tarix"
    SCORECARD_VERSION ||--o{ DECISION_JOURNAL : "qaysi versiya bilan"
    DECISION_JOURNAL ||--o{ DECISION_FACTOR : "omillar hissasi"
    APP_USER ||--o{ APP_SESSION : "sessiyalar"
    APP_USER ||--o{ DECISION_JOURNAL : "kim (login)"
```

## Nega shunday

**O'zgarmaslik ikki qavat himoyada.** `decision_journal` ga UPDATE/DELETE
SQLite triggerlari bilan taqiqlangan (`RAISE(ABORT)`). Trigger o'chirilsa ham,
har bir yozuv o'zidan oldingi yozuvning SHA-256 hashini saqlaydi — bitta satr
almashtirilsa zanjir uziladi va `verify_chain()` buni topadi (testda isbotlangan).

**SCD Type 2 skorkartada.** Yangi versiya eskisini O'CHIRMAYDI: eski satrga
`valid_to` yoziladi, xolos. Har qaror `version_id` ni ko'rsatadi, shuning uchun
istalgan eski qarorni AYNAN o'sha paytdagi skorkarta bilan qayta hisoblash
mumkin (`/api/ariza/{id}/taqqoslash`).

**`kim` ustuni hash zanjiri ICHIDA.** Regulyator "bu qarorni kim chiqargan"
deb so'raganda javob ham bor, ham keyinchalik almashtirib bo'lmaydi.

**Dataset alohida qatlamda.** CSV'lar bazaga ko'chirilmaydi — ular manba,
baza esa faqat operatsion iz (arizalar, qarorlar, versiyalar, foydalanuvchilar).
2-kun yashirin dataset `DATA_DIR` bilan almashtiriladi, sxema o'zgarmaydi.
