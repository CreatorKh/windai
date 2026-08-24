"""HTTP API + statik frontend.

Endpointlar:
  GET  /api/meta                     — lug'atlar (bandlik, maqsad, viloyat) + siyosat
  GET  /api/scorecard                — amaldagi skorkarta: IV jadvali, koeffitsientlar
  GET  /api/scorecard/versions       — barcha versiyalar (SCD Type 2)
  POST /api/scorecard/retrain        — yangi versiya o'rgatish
  POST /api/ariza                    — ariza yuborish -> qaror (jurnalga yoziladi)
  POST /api/simulyatsiya             — "what-if": jurnalga YOZILMAYDI
  GET  /api/arizalar                 — underwriter paneli uchun ro'yxat
  GET  /api/ariza/{id}               — bitta arizaning to'liq kesimi + tarixi
  GET  /api/ariza/{id}/taqqoslash    — ikki skorkarta versiyasini solishtirish
  GET  /api/mijozlar                 — datasetdagi arizachilar (avtoto'ldirish)
  GET  /api/jurnal                   — oxirgi qarorlar + hash zanjiri holati
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import auth, db
from .config import (APPROVE_SCORE, BASE_ODDS, BASE_SCORE, DATA_DIR, DB_PATH,
                     KO_MAX_DELINQ_DAYS, MAX_DTI, MAX_PD_APPROVE, MAX_PTI, PDO,
                     REVIEW_SCORE)
from .engine import CreditEngine
from .limit import max_limit

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

engine: CreditEngine = CreditEngine()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Amaldagi skorkartani bazadan oladi; bo'lmasa — o'rgatadi (~2 s).
    if engine.ensure_scorecard(version="v1", izoh="startup — avtomatik o'rgatish") is None:
        # Belgilangan ma'lumot ham, saqlangan versiya ham yo'q: server ko'tariladi,
        # lekin skoring endpointlari 503 qaytaradi (pastdagi tekshiruvlar).
        print("OGOHLANTIRISH: skorkarta o'rgatilmadi — o'quv to'plami bo'sh "
              "va bazada versiya yo'q.")
    yield


app = FastAPI(title="Kredit skoring va limit dvigateli",
              description="CBU Coding Hackathon 2026 — A2", version="1.0.0",
              lifespan=lifespan)


# ---------------------------------------------------------------------------
# Modellar
# ---------------------------------------------------------------------------


class ArizaForm(BaseModel):
    # inf/NaN 500 bermasin (422 bo'lsin); pul maydonlariga real yuqori chegara —
    # 1e308 kabi chekli-lekin-absurd qiymat median() da inf ga oshib ketardi.
    model_config = ConfigDict(allow_inf_nan=False)

    """Veb-forma. Chegaralar Pydantic darajasida — noto'g'ri kirish API ga
    umuman kirmasin.

    Nega kerak: validatsiyasiz `sorlgan_summa = -5 000 000` 200 OK va
    MAQULLANDI qaytarardi (tavsiya_summa ham manfiy). Endi FastAPI 422 beradi.
    """

    applicant_id: Optional[str] = Field(None, description="mavjud mijoz ID si")
    ism: Optional[str] = ""
    yosh: float = Field(30, ge=0, le=120)
    jins: Optional[str] = "M"
    viloyat: Optional[str] = "Toshkent"
    bandlik: str = "xususiy"
    talim: str = "orta"
    ish_staji_oy: float = Field(12, ge=0, le=720)
    oila_azolari: int = Field(2, ge=1, le=30)
    mijoz_boldi_oy: float = Field(0, ge=0, le=720)
    deklaratsiya_daromad: float = Field(0, ge=0, le=1e13)
    oylik_daromad: float = Field(0, ge=0, le=1e13)
    oylik_chiqim: float = Field(0, ge=0, le=1e13)
    naqd_yechish: float = Field(0, ge=0, le=1e13)
    oy_oxiri_qoldiq: float = Field(0, ge=0, le=1e13)
    kirim_seriya: Optional[List[float]] = None
    mavjud_oylik_yuk: float = Field(0, ge=0, le=1e13)
    mavjud_kredit_soni: int = Field(0, ge=0, le=50)
    kredit_qoldigi: float = Field(0, ge=0, le=1e13)
    max_kechikish_kun: float = Field(0, ge=0, le=3650)
    sorlgan_summa: float = Field(0, ge=0, le=1e13)
    muddat_oy: float = Field(12, ge=1, le=360)
    maqsad: str = "iste'mol"


class LoginReq(BaseModel):
    login: str
    password: str


class RetrainReq(BaseModel):
    version: str
    l2: float = 3.0
    izoh: str = ""
    belgilar: Optional[List[str]] = None    # cheklangan belgi to'plami


# ---------------------------------------------------------------------------
# Autentifikatsiya va ruxsat
# ---------------------------------------------------------------------------


# 422 javobi ham JSON bo'lishi shart. Pydantic xato tafsilotiga foydalanuvchi
# yuborgan QIYMATNI qo'shadi — u inf/NaN bo'lsa, javobning o'zi serializatsiya
# bo'lmay 500 ga aylanardi ("Out of range float values are not JSON compliant").
@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    import math

    def clean(v):
        if isinstance(v, float) and not math.isfinite(v):
            return str(v)
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [clean(x) for x in v]
        if isinstance(v, (str, int, bool)) or v is None:
            return v
        return str(v)                       # ctx ichidagi istalgan obyekt

    return JSONResponse(status_code=422, content={"detail": clean(exc.errors())})


def get_user(request: Request) -> Optional[dict]:
    """Cookie dan joriy foydalanuvchi (yoki None)."""
    return auth.current_user(engine.conn, request.cookies.get(auth.SESSION_COOKIE))


def require(permission: str):
    """FastAPI bog'liqligi: berilgan ruxsatsiz endpointga kirib bo'lmaydi.

    401 — umuman kirmagan, 403 — kirgan lekin roli yetmaydi. Frontend shu
    ikkalasini farqlaydi: 401 da login ekraniga qaytaradi, 403 da esa
    "bu bo'lim sizning rolingizga ochiq emas" deb yozadi.
    """
    def dep(request: Request) -> dict:
        user = get_user(request)
        if user is None:
            raise HTTPException(401, "kirish talab qilinadi")
        if not auth.has(user, permission):
            raise HTTPException(
                403, f"«{auth.ROLES.get(user['rol'], {}).get('nom', user['rol'])}» "
                     f"roli bu amalni bajara olmaydi")
        return user
    return dep


@app.post("/api/auth/login")
def auth_login(req: LoginReq, response: Response) -> dict:
    token = auth.login(engine.conn, req.login, req.password)
    if token is None:
        raise HTTPException(401, "Login yoki parol noto'g'ri")
    response.set_cookie(auth.SESSION_COOKIE, token, httponly=True,
                        samesite="lax", max_age=auth.SESSION_IDLE_MINUTES * 60)
    return auth.current_user(engine.conn, token)


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    auth.logout(engine.conn, request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    user = get_user(request)
    if user is None:
        raise HTTPException(401, "kirish talab qilinadi")
    return user


@app.get("/api/auth/demo")
def auth_demo() -> List[dict]:
    """Login ekranidagi demo hisoblar (hakaton uchun ataylab ochiq)."""
    return auth.demo_accounts()


@app.get("/api/foydalanuvchilar")
def foydalanuvchilar(user: dict = Depends(require("foydalanuvchi:boshqarish"))
                     ) -> dict:
    return {"foydalanuvchilar": auth.list_users(engine.conn),
            "rollar": [{"kalit": k, **{kk: vv for kk, vv in v.items()
                                       if kk != "ruxsat"},
                        "ruxsat": sorted(v["ruxsat"])}
                       for k, v in auth.ROLES.items()]}


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


@app.get("/api/meta")
def meta() -> dict:
    d = engine.data
    def uniq(field: str) -> List[str]:
        return sorted({a[field] for a in d.applicants.values() if a.get(field)})
    return {
        "bandlik": uniq("bandlik"),
        "talim": uniq("talim"),
        "viloyat": uniq("viloyat"),
        "maqsad": sorted({a["maqsad"] for a in d.applications}),
        "muddat": [6, 12, 24, 36, 60],
        "siyosat": {
            "APPROVE_SCORE": APPROVE_SCORE, "REVIEW_SCORE": REVIEW_SCORE,
            "MAX_DTI": MAX_DTI, "MAX_PTI": MAX_PTI,
            "MAX_PD_APPROVE": MAX_PD_APPROVE,
            "KO_MAX_DELINQ_DAYS": KO_MAX_DELINQ_DAYS,
            "BASE_SCORE": BASE_SCORE, "BASE_ODDS": BASE_ODDS, "PDO": PDO,
        },
        "dataset": {"arizachi": len(d.applicants), "ariza": len(d.applications),
                    "train": len(d.train()), "test": len(d.test())},
    }


@app.get("/api/mijozlar")
def mijozlar(q: str = "", limit: int = 30,
             user: dict = Depends(require("mijoz:korish"))) -> List[dict]:
    """Avtoto'ldirish uchun mijozlar ro'yxati."""
    ql = q.strip().lower()
    out = []
    for a in engine.data.applicants.values():
        if ql and ql not in a["applicant_id"].lower() and ql not in a["ism"].lower():
            continue
        out.append({"applicant_id": a["applicant_id"], "ism": a["ism"],
                    "yosh": a["yosh"], "bandlik": a["bandlik"],
                    "viloyat": a["viloyat"],
                    "deklaratsiya_daromad": a["deklaratsiya_daromad"]})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Skorkarta
# ---------------------------------------------------------------------------


@app.get("/api/scorecard")
def scorecard(user: dict = Depends(require("skorkarta:korish"))) -> dict:
    sc = engine.scorecard
    if sc is None:
        raise HTTPException(503, "skorkarta o'rgatilmagan")
    row = db.current_version(engine.conn)
    return {"version": sc.version, "version_id": engine.version_id,
            "valid_from": row["valid_from"] if row else None,
            "metrics": sc.metrics, "iv": sc.iv_table(),
            "intercept": round(sc.model.intercept, 4),
            "iteratsiya": sc.model.n_iter, "yaqinlashdi": sc.model.converged,
            "belgilar_soni": len(sc.spec)}


@app.get("/api/scorecard/versions")
def versions(user: dict = Depends(require("skorkarta:korish"))) -> List[dict]:
    return db.list_versions(engine.conn)


@app.post("/api/scorecard/retrain")
def retrain(req: RetrainReq,
            user: dict = Depends(require("skorkarta:orgatish"))) -> dict:
    spec = None
    if req.belgilar:
        from .scorecard import FEATURE_SPEC
        allowed = set(req.belgilar)
        spec = [s for s in FEATURE_SPEC if s[0] in allowed]
        if not spec:
            raise HTTPException(400, "belgilar ro'yxati bo'sh yoki noto'g'ri")
    sc = engine.train(version=req.version, izoh=req.izoh, spec=spec, l2=req.l2)
    return {"version": sc.version, "version_id": engine.version_id,
            "metrics": sc.metrics, "belgilar": [k for k, _, _, _ in sc.spec]}


# ---------------------------------------------------------------------------
# Ariza -> qaror
# ---------------------------------------------------------------------------


def _decide(form: ArizaForm) -> tuple:
    application, feats = engine.features_from_form(form.model_dump())
    if feats.get("income_used", 0) <= 0 and not form.applicant_id:
        raise HTTPException(400, "daromad kiritilmagan: oylik_daromad yoki "
                                 "deklaratsiya_daromad to'ldirilishi kerak")
    d = engine.decide(application, feats)
    return application, feats, d


@app.post("/api/ariza")
def ariza(form: ArizaForm,
          user: dict = Depends(require("ariza:yuborish"))) -> dict:
    application, feats, d = _decide(form)
    decision_id = engine.record(application, d, manba="web", kim=user["login"])
    out = d.to_dict()
    out["decision_id"] = decision_id
    out["application"] = application
    out["scorecard_version"] = engine.scorecard.version
    return out


@app.post("/api/simulyatsiya")
def simulyatsiya(form: ArizaForm,
                 user: dict = Depends(require("simulyatsiya"))) -> dict:
    """What-if: jurnalga yozmasdan qarorni hisoblash."""
    _, feats, d = _decide(form)
    out = d.to_dict()
    out["saqlanmadi"] = True
    return out


@app.get("/api/arizalar")
def arizalar(limit: int = Query(100, ge=1, le=1000), qaror: Optional[str] = None,
             user: dict = Depends(require("qarorlar:korish"))) -> List[dict]:
    return db.recent_decisions(engine.conn, limit=limit, qaror=qaror)


@app.get("/api/ariza/{application_id}")
def ariza_detali(application_id: str,
                 user: dict = Depends(require("mijoz:korish"))) -> dict:
    history = db.decision_history(engine.conn, application_id)
    if not history:
        raise HTTPException(404, f"{application_id} bo'yicha qaror topilmadi")
    application = db.get_application(engine.conn, application_id) or {}
    applicant_id = application.get("applicant_id", "")
    profile = engine.data.profile(applicant_id) if applicant_id else {}
    return {"application_id": application_id, "application": application,
            "profil": profile, "tarix": history, "oxirgi": history[-1]}


@app.get("/api/ariza/{application_id}/taqqoslash")
def taqqoslash(application_id: str, a: int, b: int,
               user: dict = Depends(require("skorkarta:korish"))) -> dict:
    """Bitta arizani ikki xil skorkarta versiyasi bilan qayta hisoblash."""
    ra = engine.rescore_with_version(application_id, a)
    rb = engine.rescore_with_version(application_id, b)
    if ra is None or rb is None:
        raise HTTPException(404, "ariza yoki versiya topilmadi")
    fa = {c["key"]: c for c in ra["skoring"]["omillar"]}
    fb = {c["key"]: c for c in rb["skoring"]["omillar"]}
    farq = []
    for key in sorted(set(fa) | set(fb)):
        pa = fa.get(key, {}).get("points", 0.0)
        pb = fb.get(key, {}).get("points", 0.0)
        if abs(pa - pb) > 1e-9:
            farq.append({"key": key,
                         "label": (fa.get(key) or fb[key])["label"],
                         "a": pa, "b": pb, "delta": round(pb - pa, 1)})
    farq.sort(key=lambda r: -abs(r["delta"]))
    return {"application_id": application_id, "a": ra, "b": rb, "farq": farq,
            "delta_ball": round(rb["ball"] - ra["ball"], 1),
            "delta_pd": round(rb["pd"] - ra["pd"], 6)}


# ---------------------------------------------------------------------------
# Jurnal
# ---------------------------------------------------------------------------


@app.get("/api/mijoz/{applicant_id}")
def mijoz_kartasi(applicant_id: str,
                  user: dict = Depends(require("mijoz:korish"))) -> dict:
    """Mijozning to'liq kartasi: profil, 12 oylik oqim, kreditlar, arizalar."""
    card = engine.client_card(applicant_id)
    if card is None:
        raise HTTPException(404, f"{applicant_id} topilmadi")
    return card


@app.get("/api/mijoz/{applicant_id}/graf")
def mijoz_grafi(applicant_id: str, n: int = Query(8, ge=3, le=24),
                user: dict = Depends(require("mijoz:korish"))) -> dict:
    """Mijoz aloqalari grafi: kreditlar, o'xshash mijozlar va ular orasidagi
    setka. Bo'sh qatlam bilan qaytgan `partial`/`missing` maydonlariga qarang —
    "aloqa yo'q" va "qatlam ishlamadi" bir narsa emas."""
    g = engine.graph.build(applicant_id, n=n)
    if g is None:
        raise HTTPException(404, f"{applicant_id} topilmadi")
    return g


@app.get("/api/portfel")
def portfel(user: dict = Depends(require("portfel:korish"))) -> dict:
    """Portfel darajasidagi kesim: ball taqsimoti va bandlar bo'yicha defolt ulushi."""
    p = engine.portfolio()
    if not p:
        raise HTTPException(503, "skorkarta o'rgatilmagan")
    return p


@app.get("/api/statistika")
def statistika(user: dict = Depends(require("qarorlar:korish"))) -> dict:
    """Jurnal STATISTIKASI va hash zanjiri holati — xom yozuvlarsiz.

    Zanjir butunligi butun jamoaga kerak bo'lgan ishonch signali; mijozning
    to'liq payload'i esa faqat auditorga (`/api/jurnal`).
    """
    stats = db.stats(engine.conn)
    # Rad sabablari reytingi — jamoadosh loyihasidagi "TOP-5 sabab" g'oyasi:
    # underwriter uchun "portfel nimadan qaytmoqda" degan savolga bir qarashda
    # javob. Qoidalar allaqachon decision_journal payload ichida yotibdi.
    reasons: dict = {}
    for row in engine.conn.execute(
            "SELECT payload FROM decision_journal WHERE qaror = 'RAD_ETILDI' "
            "ORDER BY id DESC LIMIT 800"):
        try:
            import json as _json
            for q in _json.loads(row["payload"]).get("qoidalar", []):
                if q.get("qaror") == "RAD_ETILDI":
                    r = reasons.setdefault(q["kod"], {"kod": q["kod"], "n": 0,
                                                      "matn": q["matn"]})
                    r["n"] += 1
        except Exception:
            continue
    top = sorted(reasons.values(), key=lambda r: -r["n"])[:5]
    return {"zanjir": db.verify_chain(engine.conn),
            "statistika": stats,
            "rad_sabablari": top}


@app.get("/api/jurnal")
def jurnal(limit: int = Query(50, ge=1, le=1000),
           user: dict = Depends(require("jurnal:korish"))) -> dict:
    return {"zanjir": db.verify_chain(engine.conn),
            "statistika": db.stats(engine.conn),
            "oxirgi": db.recent_decisions(engine.conn, limit=limit)}


# ---------------------------------------------------------------------------
# Statik frontend
# ---------------------------------------------------------------------------

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

    @app.middleware("http")
    async def no_stale_cache(request: Request, call_next):
        """Frontend fayllari keshda qotib qolmasin.

        `no-cache` "saqlama" degani emas — "har safar serverdan tekshir"
        degani (ETag bilan 304 qaytadi). Busiz brauzer eski app.js ni disk
        keshidan olib, yangi login ekrani ISHLAMAY qoladi: forma handler'siz
        qoladi va "Kirish" bosilganda hech nima bo'lmaydi.
        """
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(WEB_DIR / "index.html"))

    @app.get("/taqdimot")
    def taqdimot() -> FileResponse:
        """Taqdimot slaydlari SHU serverdan beriladi.

        Nega muhim: graf slaydidagi «jonli» tugma ilovani iframe ichida ochadi.
        Sessiya cookie'si SameSite=lax — BOSHQA origin (masalan alohida :8091
        server) ichidagi iframe'ga u yuborilmaydi va graf bo'sh chiqadi.
        Bir xil origin bo'lsa cookie ishlaydi va graf jonli ko'rinadi.
        """
        f = WEB_DIR.parent / "taqdimot.html"
        if not f.exists():
            raise HTTPException(404, "taqdimot.html topilmadi")
        return FileResponse(str(f))
