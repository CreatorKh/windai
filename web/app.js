/* WINDAI — kredit qarorlari platformasi (vanilla JS, build qadamisiz).
   Uslub FindDroppers dizayn tizimidan: burchaksiz brutalizm, #d1fe17 aksent. */
'use strict';

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const state = { meta: null, user: null, scorecard: null, base: null,
                versions: [], whatIfReady: false, mijoz: null };

/* ------------------------------------------------------------- yordamchilar */
const nf = new Intl.NumberFormat('ru-RU');
const money = v => nf.format(Math.round(v || 0)) + ' so‘m';
const pct   = (v, d = 1) => (100 * (v || 0)).toFixed(d) + '%';
const esc   = s => String(s ?? '').replace(/[&<>"]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const initials = s => String(s || '?').trim().split(/\s+/).slice(0, 2)
  .map(w => w[0]).join('').toUpperCase();

/** FastAPI 422 `detail` ni massiv sifatida qaytaradi — uni o'qiladigan
 *  matnga aylantiramiz, aks holda foydalanuvchi «[object Object]» ko'radi. */
function apiErr(body, fallback) {
  const d = body && body.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d.map(x => {
      const field = Array.isArray(x.loc) ? x.loc[x.loc.length - 1] : '';
      return (field ? `«${field}»: ` : '') + (x.msg || '');
    }).join('; ');
  }
  return fallback;
}

/** Eski brauzerlarda AbortSignal.timeout yo'q — bo'lmasa signal'siz ishlaymiz. */
function timeoutSignal(ms) {
  try { return AbortSignal.timeout(ms); } catch (e) { return undefined; }
}

async function api(path, opts) {
  const r = await fetch(path, { signal: timeoutSignal(20000), ...opts });
  if (r.status === 401) {                 // sessiya tugadi yoki umuman yo'q
    showGate(state.user ? 'Sessiya tugadi. Qaytadan kiring.' : '');
    throw new Error('kirish talab qilinadi');
  }
  if (!r.ok) {
    let body = null;
    try { body = await r.json(); } catch (e) {}
    throw new Error(apiErr(body, r.statusText));
  }
  return r.json();
}
const post = (p, body) => api(p, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body) });

let toastTimer = null;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3600);
}

const VERDICT = {
  MAQULLANDI:          { cls: 'v-ok',  text: "Ma’qullandi" },
  QOLDA_KORIB_CHIQISH: { cls: 'v-mid', text: "Qo‘lda ko‘rib chiqish" },
  RAD_ETILDI:          { cls: 'v-no',  text: 'Rad etildi' },
};
const verdict = q => `<span class="verdict ${(VERDICT[q]||{}).cls||''}">${
  esc((VERDICT[q]||{}).text||q)}</span>`;

/* ------------------------------------------------------------------- tema */
function initTheme() {
  $('#theme').onclick = () => {
    const d = document.documentElement.classList.toggle('dark');
    localStorage.setItem('theme', d ? 'dark' : 'light');
  };
}

/* ============================================================ KIRISH EKRANI */
function showGate(msg) {
  state.user = null;
  $('#login-gate').hidden = false;
  $('#who').hidden = true;
  $('#logout').hidden = true;
  if (msg) showLoginError(msg);
}

function showLoginError(msg) {
  const box = $('#lg-error');
  box.className = 'err';
  box.textContent = msg;
  box.hidden = false;
}

async function initGate() {
  $('#login-form').onsubmit = async ev => {
    ev.preventDefault();
    await doLogin($('#lg-login').value.trim(), $('#lg-parol').value);
  };
  $('#logout').onclick = async () => {
    try { await post('/api/auth/logout', {}); } catch (e) {}
    location.hash = '';
    location.reload();
  };
  try {
    const accounts = await (await fetch('/api/auth/demo')).json();
    $('#lg-accounts').innerHTML = accounts.map(a => `
      <button type="button" class="demo-card" data-l="${esc(a.login)}"
        data-p="${esc(a.parol)}">
        <b>${esc(a.rol_nomi)}</b>
        <em>${esc(a.tavsif)}</em>
        <code>${esc(a.login)} / ${esc(a.parol)}</code>
      </button>`).join('');
    $$('#lg-accounts .demo-card').forEach(b => b.onclick = () => {
      $('#lg-login').value = b.dataset.l;
      $('#lg-parol').value = b.dataset.p;
      doLogin(b.dataset.l, b.dataset.p);
    });
  } catch (e) { /* demo ro'yxati bo'lmasa ham qo'lda kirish ishlaydi */ }
}

async function doLogin(login, parol) {
  $('#lg-error').hidden = true;
  try {
    const r = await fetch('/api/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login, password: parol }) });
    if (!r.ok) {
      let b = null; try { b = await r.json(); } catch (e) {}
      showLoginError(apiErr(b, "Login yoki parol noto‘g‘ri"));
      return;
    }
    state.user = await r.json();
    $('#login-gate').hidden = true;
    await afterLogin();
  } catch (e) {
    showLoginError('Server bilan aloqa yo‘q: ' + e.message);
  }
}

/* ============================================================ FOYDALANUVCHI */
const can = perm => !!state.user && state.user.ruxsat.includes(perm);

function renderUser() {
  const u = state.user;
  if (!u) return;
  $('#who').hidden = false;
  $('#logout').hidden = false;
  $('#who-avatar').textContent = initials(u.ism);
  $('#who-ism').textContent = u.ism;
  $('#who-rol').textContent = u.rol_nomi;
  $('#who-ism').title = `${u.ism} · ${u.lavozim}`;
}

/* Shapkadagi chiplar rolga bog'liq: mijoz menejeriga model versiyasi kerak emas. */
async function renderChips() {
  const box = $('#top-chips');
  box.innerHTML = '';
  if (!can('skorkarta:korish')) return;
  try {
    const sc = await api('/api/scorecard');
    state.scorecard = sc;
    const chips = [`<span class="chip">Skorkarta ${esc(sc.version)} · amalda</span>`];
    if (can('skorkarta:orgatish')) {
      chips.push(`<span class="chip">AUC CV ${sc.metrics.auc_cv ?? '—'}</span>`);
    }
    box.innerHTML = chips.join('');
  } catch (e) { /* chiplar hayotiy emas */ }
}

/* ================================================================== SAHIFA */
const PAGES = {
  ariza: { nom: 'Yangi ariza', perm: 'ariza:yuborish',
    tavsif: 'Mijoz ma’lumotlarini kiriting — tizim ball, defolt ehtimoli va limitni hisoblab beradi.' },
  underwriter: { nom: 'Qarorlar oqimi', perm: 'qarorlar:korish',
    tavsif: 'Barcha arizalar, ballar va qarorlar bitta ro‘yxatda — ID bo‘yicha qidiring.' },
  mijoz: { nom: 'Mijoz kartasi', perm: 'mijoz:korish',
    tavsif: 'Bitta mijozning profili, 12 oylik pul oqimi, kreditlari va ariza tarixi.' },
  skorkarta: { nom: 'Skoring modeli', perm: 'skorkarta:korish',
    tavsif: 'Qaysi belgi ballga qancha ta’sir qiladi: IV, koeffitsient va WOE bucket‘lari.' },
  whatif: { nom: 'Sinov maydoni', perm: 'simulyatsiya',
    tavsif: 'Daromad yoki summani o‘zgartiring — qaror qanday o‘zgarishini darhol ko‘ring.' },
  versiya: { nom: 'Versiyalar va audit', perm: 'skorkarta:korish',
    tavsif: 'Skorkarta versiyalari, ularni taqqoslash va o‘zgarmas qaror jurnali.' },
};
const TABS = Object.keys(PAGES);
const TAB_HOOK = {};        // tab -> [yuklovchi, xato konteyneri]

function parseHash() {
  const raw = decodeURIComponent(location.hash.replace(/^#/, ''));
  const [name, arg] = raw.split('/');
  return { name: TABS.includes(name) ? name : null, arg: arg || null };
}

/** Faol tabni almashtiradi va uni URL da saqlaydi (F5 dan keyin joyida qoladi). */
function setTab(name, { silent = false, arg = null } = {}) {
  const page = PAGES[name];
  if (!page || !can(page.perm)) {
    const first = TABS.find(t => can(PAGES[t].perm));
    if (!first) return;
    if (page) toast(`«${page.nom}» bo‘limi ${state.user.rol_nomi} rolida ochilmaydi`);
    name = first;
    arg = null;
  }
  $$('nav.tabs button').forEach(b =>
    b.setAttribute('aria-selected', String(b.dataset.tab === name)));
  $$('section[id^="tab-"]').forEach(s => s.hidden = s.id !== 'tab-' + name);
  $('#page-title').textContent = PAGES[name].nom;
  $('#page-sub').textContent = PAGES[name].tavsif;

  const want = name + (arg ? '/' + arg : '');
  if (!silent && location.hash.slice(1) !== want) {
    history.replaceState(null, '', '#' + want);
  }
  const active = $(`nav.tabs button[data-tab="${name}"]`);
  if (active) active.scrollIntoView({ inline: 'center', block: 'nearest' });

  const entry = TAB_HOOK[name];
  if (!entry) return;
  const [hook, errBox] = entry;
  Promise.resolve().then(() => hook(arg)).catch(e => {
    const box = $(errBox);
    if (box) box.innerHTML = `<div class="err">Yuklashda xato: ${esc(e.message)}</div>`;
  });
}

function initTabs() {
  Object.assign(TAB_HOOK, {
    ariza:       [() => {}, '#ariza-natija'],
    underwriter: [loadUnderwriter, '#uw-kpi'],
    mijoz:       [loadMijozTab, '#mk-card'],
    skorkarta:   [loadScorecard, '#sc-kpi'],
    whatif:      [initWhatIf, '#wi-natija'],
    versiya:     [loadVersions, '#jr-out'],
  });
  $$('nav.tabs button').forEach(b => b.onclick = () => {
    if (b.disabled) return;
    setTab(b.dataset.tab);
  });
  addEventListener('hashchange', () => {
    const { name, arg } = parseHash();
    setTab(name || TABS[0], { silent: true, arg });
  });
}

/** Ruxsati yo'q bo'limlar YASHIRILMAYDI, bloklanadi: rol modeli ko'rinib tursin. */
function applyRoleLocks() {
  $$('nav.tabs button').forEach(b => {
    const ok = can(b.dataset.perm);
    b.disabled = !ok;
    if (ok) b.removeAttribute('data-locked');
    else {
      b.dataset.locked = '1';
      b.title = `Bu bo‘lim ${state.user.rol_nomi} rolida ochilmaydi`;
    }
  });
  $$('[data-perm]').forEach(el => {
    if (el.tagName === 'BUTTON' && el.getAttribute('role') === 'tab') return;
    el.hidden = !can(el.dataset.perm);
  });
}

/* ============================================================ PUL MAYDONLARI */
/* type="number" ming ajratgichni qo'llamaydi, shuning uchun matn maydoni.
   Minus BELGISI olib tashlanadi: `min="0"` matn maydonida ishlamaydi va
   manfiy summa serverga yetib borardi. */
const rawNum = el => Number(String(el.value).replace(/[^\d.]/g, '')) || 0;

function formatMoneyInput(el) {
  const pos = el.selectionStart, len = el.value.length;
  const n = rawNum(el);
  el.value = n ? nf.format(n) : '';
  const at = Math.max(0, (pos || 0) + (el.value.length - len));
  try { el.setSelectionRange(at, at); } catch (e) {}
}

function initMoneyInputs() {
  $$('input.money').forEach(el => {
    formatMoneyInput(el);
    el.addEventListener('input', () => { formatMoneyInput(el); liveCalc(); });
  });
  $$('.quick').forEach(box => {
    const target = $(box.dataset.target);
    box.querySelectorAll('button').forEach(b => b.onclick = () => {
      target.value = nf.format(Number(b.dataset.v));
      liveCalc();
    });
  });
}

/* ============================================================= JONLI HISOB */
/* Serverdagi mantiqning aynan nusxasi (app/features.py): annuitet va daromad
   clamp'i bir xil bo'lmasa, ekrandagi DTI serverникидan farq qilib qoladi. */
const ANNUAL_RATE = 0.28;

function annuity(principal, months) {
  if (!months || months <= 0) return principal;
  const i = ANNUAL_RATE / 12;
  const f = 1 - Math.pow(1 + i, -months);
  return f <= 0 ? principal / months : principal * i / f;
}

function resolveIncome(observed, declared) {
  if (observed > 0 && declared > 0) {
    return Math.max(Math.min(observed, declared * 1.5), declared * 0.5);
  }
  return observed || declared;
}

function liveCalc() {
  const box = $('#live-panel');
  if (!state.meta) return;
  const pol = state.meta.siyosat;
  const f = readForm();
  let income, existing;
  if (f.applicant_id) {
    // Mavjud mijoz: jonli hisob ham BANK ma'lumotidan yursin — aks holda
    // chapda yashil 35%, qarorda esa boshqa raqam chiqadi.
    const k = state.mavjudKarta && state.mavjudKarta.korsatkichlar;
    if (!k) { box.innerHTML = ''; return; }     // karta hali yuklanmoqda
    income = k.daromad_median;
    existing = k.mavjud_oylik_tolov;
  } else {
    income = resolveIncome(f.oylik_daromad, f.deklaratsiya_daromad);
    existing = f.mavjud_oylik_yuk;
  }
  const pay = annuity(f.sorlgan_summa, f.muddat_oy);
  const dti = income > 0 ? (existing + pay) / income : 99;
  const pti = income > 0 ? pay / income : 99;
  const free = income - existing - pay;

  const cls = (v, lim) => (v <= lim ? 'ok' : 'no');
  box.innerHTML = `
    <div class="hd"><span class="label">Jonli hisob</span>
      <span class="code faint">yuborishdan oldin</span></div>
    <div class="live-row">
      <div><div class="k">Oylik to‘lov</div>
        <div class="v">${nf.format(Math.round(pay))}</div>
        <div class="s">${f.muddat_oy} oy · 28% yillik</div></div>
      <div><div class="k">Qarz yuki (DTI)</div>
        <div class="v ${cls(dti, pol.MAX_DTI)}">${pct(dti)}</div>
        <div class="s">chegara ${pct(pol.MAX_DTI, 0)}</div></div>
      <div><div class="k">Erkin pul</div>
        <div class="v ${free >= 0 ? 'ok' : 'no'}">${nf.format(Math.round(free))}</div>
        <div class="s">PTI ${pct(pti)} · chegara ${pct(pol.MAX_PTI, 0)}</div></div>
    </div>`;

  const gap = (!f.applicant_id && f.deklaratsiya_daromad > 0)
    ? f.oylik_daromad / f.deklaratsiya_daromad : 1;
  $('#hint-gap').textContent = Math.abs(gap - 1) >= 0.3
    ? 'Bank tushumi deklaratsiyadan sezilarli farq qiladi — bu ballni pasaytiradi.'
    : 'Bank oqimi bilan solishtiriladi.';
}

/* Daromad barqarorligi -> 12 oylik seriya. Determinatik koeffitsientlar:
   tasodifiy son ishlatilsa, bir xil forma har safar boshqa ball berardi. */
const CV_PROFILES = {
  barqaror:    [1.00, .98, 1.02, .99, 1.01, .98, 1.02, 1.00, .99, 1.01, 1.02, .98],
  ozgaruvchan: [1.00, .78, 1.22, .85, 1.15, .74, 1.26, .92, 1.08, .82, 1.18, 1.00],
  kuchli:      [1.00, .50, 1.50, .62, 1.38, .45, 1.55, .72, 1.28, .55, 1.45, 1.00],
};

/* ================================================================== ARIZA */
function fillSelect(el, items, val) {
  el.innerHTML = items.map(v =>
    `<option value="${esc(v)}"${String(v) === String(val) ? ' selected' : ''}>${esc(v)}</option>`
  ).join('');
}

let clients = [];

async function initForm() {
  const m = state.meta;
  fillSelect($('#f-bandlik'), m.bandlik, 'xususiy');
  fillSelect($('#f-talim'), m.talim, 'oliy');
  fillSelect($('#f-muddat'), m.muddat, 24);
  fillSelect($('#f-maqsad'), m.maqsad, m.maqsad[0]);
  fillSelect($('#wi-muddat'), m.muddat, 24);

  initMoneyInputs();
  ['#f-muddat', '#f-cv', '#f-yosh', '#f-nloan', '#f-kechikish', '#f-staj']
    .forEach(id => $(id).addEventListener('input', liveCalc));

  // Rejim almashtirgich
  $$('.mode').forEach(b => b.onclick = () => setMode(b.dataset.mode));

  // Pressetlar FAQAT to'ldiradi — avval har bosish jurnalga yozuv qo'shardi.
  $$('.preset').forEach(b => b.onclick = () => applyPreset(b.dataset.preset));

  if (can('mijoz:korish')) {
    clients = await api('/api/mijozlar?limit=80');
    $('#f-applicant').innerHTML = '<option value="">— mijozni tanlang —</option>' +
      clients.map(c => `<option value="${esc(c.applicant_id)}">${esc(c.applicant_id)}
        · ${esc(c.ism)} · ${esc(c.bandlik)}</option>`).join('');
    $('#f-applicant').onchange = () => loadMavjudKarta($('#f-applicant').value);
  }

  $('#form-ariza').onsubmit = async ev => {
    ev.preventDefault();
    const btn = $('#form-ariza button[type=submit]');
    btn.disabled = true;
    $('#ariza-natija').innerHTML = '<div class="loading">hisoblanmoqda…</div>';
    try {
      const body = readForm();
      const res = await post('/api/ariza', body);
      state.base = body;
      $('#ariza-natija').innerHTML = renderDecision(res, true);
      $('#live-status').textContent =
        `Qaror: ${(VERDICT[res.qaror] || {}).text || res.qaror}, ball ${res.ball.toFixed(0)}`;
      if (innerWidth < 1120) $('#ariza-natija').scrollIntoView({ behavior: 'smooth' });
    } catch (e) {
      $('#ariza-natija').innerHTML = `<div class="err">Xato: ${esc(e.message)}</div>`;
    } finally { btn.disabled = false; }
  };
  liveCalc();
}

function setMode(mode) {
  $$('.mode').forEach(b =>
    b.setAttribute('aria-checked', String(b.dataset.mode === mode)));
  $('#mode-yangi').hidden = mode !== 'yangi';
  $('#mode-mavjud').hidden = mode !== 'mavjud';
  if (mode === 'yangi') {
    $('#f-applicant').value = '';
    $('#mavjud-karta').innerHTML = '';
  }
  liveCalc();
}

/** Mavjud mijoz tanlanganda: bank ma'lumotlari SERVERDAN olinadi, forma
 *  ularni tahrirlash imkonini bermaydi — aks holda ekran yolg'on gapiradi
 *  (backend baribir datasetdagi qiymatlarni ishlatadi). */
async function loadMavjudKarta(id) {
  const box = $('#mavjud-karta');
  if (!id) { box.innerHTML = ''; return; }
  box.innerHTML = '<div class="loading">yuklanmoqda…</div>';
  try {
    const d = await api('/api/mijoz/' + encodeURIComponent(id));
    state.mavjudKarta = d;
    const a = d.applicant, k = d.korsatkichlar;
    box.innerHTML = `
      <div class="card flat" style="margin-bottom:14px">
        <div class="card-head"><h3>${esc(a.ism)}</h3>
          <span class="label">bank ma’lumotlaridan</span></div>
        <div class="grid g2">
          <div class="between"><span class="dim">Bandlik</span><b>${esc(a.bandlik)}</b></div>
          <div class="between"><span class="dim">Yosh / staj</span>
            <b>${a.yosh} / ${a.ish_staji_oy} oy</b></div>
          <div class="between"><span class="dim">Daromad medianasi</span>
            <b class="num">${money(k.daromad_median)}</b></div>
          <div class="between"><span class="dim">Mavjud to‘lov</span>
            <b class="num">${money(k.mavjud_oylik_tolov)}</b></div>
          <div class="between"><span class="dim">Faol kreditlar</span>
            <b>${k.faol_kreditlar}</b></div>
          <div class="between"><span class="dim">Maks. kechikish</span>
            <b>${k.max_kechikish} kun</b></div>
        </div>
        <p class="code faint" style="margin-top:10px">Bu maydonlar tahrirlanmaydi —
          qaror bank ma’lumotlari asosida chiqadi.
          <a href="#mijoz/${esc(id)}">To‘liq karta →</a></p>
      </div>`;
    liveCalc();                       // karta kelgach jonli hisob bankdan yuradi
  } catch (e) {
    box.innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

function readForm() {
  const n = id => rawNum($(id));
  const i = id => Number($(id).value || 0);
  const applicant = $('#mode-mavjud').hidden ? '' : $('#f-applicant').value;

  // MAVJUD MIJOZ REJIMI: yashirin "yangi mijoz" maydonlarini YUBORMAYMIZ.
  // Ular oldingi presetdan qolgan qiymatlarni saqlaydi va serverda
  // max(forma, bank) orqali soxta DTI yasar edi: kartada "mavjud to'lov 0",
  // qarorda esa "to'lovlar daromadning 103% i" — bevosita qarama-qarshilik.
  // Bank ma'lumotidagi mijoz uchun forma faqat KREDIT SO'ROVINI beradi.
  if (applicant) {
    return {
      applicant_id: applicant,
      sorlgan_summa: n('#f-summa'), muddat_oy: i('#f-muddat'),
      maqsad: $('#f-maqsad').value,
      mavjud_oylik_yuk: 0,          // server kredit registridan o'zi oladi
    };
  }

  const kirim = n('#f-kirim');
  const profile = CV_PROFILES[$('#f-cv').value] || CV_PROFILES.barqaror;
  return {
    applicant_id: null,
    yosh: i('#f-yosh'), oila_azolari: i('#f-oila'),
    bandlik: $('#f-bandlik').value, talim: $('#f-talim').value,
    ish_staji_oy: i('#f-staj'), mijoz_boldi_oy: i('#f-tarix'),
    deklaratsiya_daromad: n('#f-dekl'), oylik_daromad: kirim,
    kirim_seriya: profile.map(x => Math.round(kirim * x)),
    oylik_chiqim: n('#f-chiqim'), naqd_yechish: n('#f-naqd'),
    mavjud_oylik_yuk: n('#f-yuk'), mavjud_kredit_soni: i('#f-nloan'),
    kredit_qoldigi: n('#f-qoldiq'), max_kechikish_kun: i('#f-kechikish'),
    sorlgan_summa: n('#f-summa'), muddat_oy: i('#f-muddat'),
    maqsad: $('#f-maqsad').value,
  };
}

const PRESETS = {
  ideal: { yosh: 41, oila_azolari: 2, bandlik: 'byudjet', talim: 'oliy',
    ish_staji_oy: 96, mijoz_boldi_oy: 72, deklaratsiya_daromad: 12000000,
    oylik_daromad: 12400000, oylik_chiqim: 5200000, naqd_yechish: 600000,
    mavjud_oylik_yuk: 0, mavjud_kredit_soni: 0, kredit_qoldigi: 0,
    max_kechikish_kun: 0, sorlgan_summa: 30000000, muddat_oy: 36,
    maqsad: 'avto', cv: 'barqaror' },
  chegaraviy: { yosh: 29, oila_azolari: 4, bandlik: 'savdo', talim: 'orta_maxsus',
    ish_staji_oy: 18, mijoz_boldi_oy: 9, deklaratsiya_daromad: 5000000,
    oylik_daromad: 4700000, oylik_chiqim: 3300000, naqd_yechish: 1500000,
    mavjud_oylik_yuk: 900000, mavjud_kredit_soni: 1, kredit_qoldigi: 11000000,
    max_kechikish_kun: 15, sorlgan_summa: 60000000, muddat_oy: 24,
    maqsad: 'mikrobiznes', cv: 'ozgaruvchan' },
  yuqori_xavf: { yosh: 26, oila_azolari: 5, bandlik: 'qurilish', talim: 'orta',
    ish_staji_oy: 7, mijoz_boldi_oy: 4, deklaratsiya_daromad: 3200000,
    oylik_daromad: 2900000, oylik_chiqim: 2600000, naqd_yechish: 1600000,
    mavjud_oylik_yuk: 1400000, mavjud_kredit_soni: 2, kredit_qoldigi: 18000000,
    max_kechikish_kun: 95, sorlgan_summa: 40000000, muddat_oy: 12,
    maqsad: "iste'mol", cv: 'kuchli' },
};

const FIELD_OF = {
  yosh: '#f-yosh', oila_azolari: '#f-oila', bandlik: '#f-bandlik',
  talim: '#f-talim', ish_staji_oy: '#f-staj', mijoz_boldi_oy: '#f-tarix',
  deklaratsiya_daromad: '#f-dekl', oylik_daromad: '#f-kirim',
  oylik_chiqim: '#f-chiqim', naqd_yechish: '#f-naqd', mavjud_oylik_yuk: '#f-yuk',
  mavjud_kredit_soni: '#f-nloan', kredit_qoldigi: '#f-qoldiq',
  max_kechikish_kun: '#f-kechikish', sorlgan_summa: '#f-summa',
  muddat_oy: '#f-muddat', maqsad: '#f-maqsad', cv: '#f-cv',
};

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  setMode('yangi');
  for (const [k, v] of Object.entries(p)) {
    const el = $(FIELD_OF[k]);
    if (!el) continue;
    el.value = el.classList.contains('money') ? nf.format(Number(v)) : v;
  }
  $$('.preset').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.preset === name)));
  liveCalc();
  toast('Ssenariy to‘ldirildi — «Qaror olish» tugmasini bosing');
}

/* ------------------------------------------------------- qaror ko'rinishi */
function gauge(score) {
  const p = s => Math.max(0, Math.min(100, (s - 400) / 3));
  const pol = state.meta.siyosat;
  return `<div class="gauge"><i style="width:${p(score)}%"></i>
      <span class="tick" style="left:${p(pol.REVIEW_SCORE)}%"></span>
      <span class="tick" style="left:${p(pol.APPROVE_SCORE)}%"></span></div>
    <div class="legend code faint"><span>400</span>
      <span>rad · ${pol.REVIEW_SCORE} · qo‘lda · ${pol.APPROVE_SCORE} · ma’qul</span>
      <span>700</span></div>`;
}

function contribRows(omillar) {
  const max = Math.max(1, ...omillar.map(o => Math.abs(o.points)));
  return omillar.map(o => {
    const w = Math.abs(o.points) / max * 50;
    const pos = o.points > 0;
    return `<div class="contrib">
      <div><span class="nm">${esc(o.label)}</span>
        <span class="bin">${esc(o.bin)} · WOE ${o.woe.toFixed(2)}</span></div>
      <div class="bar"><span class="mid"></span>
        <i class="${pos ? 'pos' : 'neg'}" style="${
          pos ? `left:50%;width:${w}%` : `right:50%;width:${w}%`}"></i></div>
      <div class="pts ${pos ? 'pos' : 'neg'}">${o.points > 0 ? '+' : ''}${
        o.points.toFixed(0)}</div></div>`;
  }).join('');
}

function factRow(items) {
  return `<div class="verdict-facts">${items.map(([l, v]) =>
    `<div class="fact"><div class="label">${l}</div><b>${v}</b></div>`).join('')}</div>`;
}

/** Mijozga qaratilgan qaror ko'rinishi: avval INSON TILIDA javob va
 *  "nima qilsam bo'ladi", keyingina texnik tafsilot (yig'ilgan holda). */
function renderDecision(d, saved) {
  const m = d.mijoz_izohi, k = d.korsatkichlar, L = d.limit;
  const om = d.skoring.omillar;
  const neg = om.filter(o => o.points < 0).length;

  const good = (m.yordam_berdi || []).map(x =>
    `<li>${esc(x.matn)}<em>${x.ball > 0 ? '+' : ''}${x.ball.toFixed(0)} ball</em></li>`).join('');
  const bad = (m.tosqinlik_qildi || []).map(x =>
    `<li>${esc(x.matn)}<em>${x.ball.toFixed(0)} ball</em></li>`).join('');

  return `
  <div class="stack">
    <div class="verdict-box ${esc(m.ohang)}">
      <div class="verdict-grid">
        <div>
          <h2>${esc(m.sarlavha)}</h2>
          <p class="verdict-lead">${esc(m.bosh_gap)}</p>
          ${factRow(m.raqamlar.tavsiya > 0
            ? [['Tavsiya etilgan', money(m.raqamlar.tavsiya)],
               ['Muddat', m.raqamlar.muddat_oy + ' oy'],
               ['Oylik to‘lov', money(m.raqamlar.oylik_tolov)],
               ['To‘lay olmaslik ehtimoli', pct(d.pd, 2)]]
            : [['So‘ralgan', money(m.raqamlar.soralgan)],
               ['Berilishi mumkin', money(0)],
               ['To‘lay olmaslik ehtimoli', pct(d.pd, 2)]])}
        </div>
        <div class="verdict-ring">${scoreRing(d.ball)}</div>
      </div>
    </div>

    <div class="actions">
      <div class="hd"><h3>Nima qilsam bo‘ladi?</h3>
        <span class="label">amaliy qadamlar</span></div>
      <ol>${(m.keyingi_qadam || []).map(x => `<li>${esc(x)}</li>`).join('')}</ol>
    </div>

    ${(good || bad) ? `<div class="why">
      <div><div class="label" style="margin-bottom:10px">Foydangizga ishladi</div>
        ${good ? `<ul class="good">${good}</ul>`
               : '<p class="data faint">Sezilarli ijobiy omil topilmadi.</p>'}</div>
      <div><div class="label" style="margin-bottom:10px">To‘sqinlik qildi</div>
        ${bad ? `<ul class="bad">${bad}</ul>`
              : '<p class="data faint">Salbiy omil yo‘q.</p>'}</div>
    </div>` : ''}

    <details class="tech">
      <summary>Texnik tafsilot — underwriter va regulyator uchun</summary>
      <div class="tech-body">
        <div>
          <div class="between" style="margin-bottom:4px">
            <span class="label">Skorkarta bali</span>
            <span class="data num">${d.ball.toFixed(1)} / PD ${pct(d.pd, 3)}</span></div>
          ${gauge(d.ball)}
        </div>
        <div class="tech-note"><b>Rasmiy sabab (audit izi).</b> ${esc(d.sabab)}</div>
        <div>
          <div class="between" style="margin-bottom:8px">
            <span class="label">Omillar hissasi</span>
            <span class="label">${neg} salbiy / ${om.length - neg} ijobiy</span></div>
          <p class="code faint" style="margin-bottom:10px">Neytral tayanch
            ${d.skoring.neytral_ball.toFixed(0)} ball + hissalar yig‘indisi =
            ${d.ball.toFixed(0)} ball</p>
          ${contribRows(om)}
        </div>
        <div class="grid g2">
          <div class="card flat">
            <div class="card-head"><h3>Limit</h3>
              <span class="label">binary search</span></div>
            <div class="between"><span class="dim">So‘ralgan</span>
              <b class="num">${money(d.sorlgan_summa)}</b></div>
            <div class="between"><span class="dim">Tavsiya etilgan</span>
              <b class="num">${money(d.tavsiya_summa)}</b></div>
            <div class="between"><span class="dim">To‘lov qobiliyati limiti</span>
              <span class="num">${money(L.tolov_qobiliyati_limiti)}</span></div>
            <div class="between"><span class="dim">Cheklovchi omil</span>
              <span>${esc(L.cheklovchi_omil)}</span></div>
            <div class="between"><span class="dim">Iteratsiya / qo‘riqchi</span>
              <span class="num">${L.iteratsiya} / ${L.qoriqchi_qadam}</span></div>
          </div>
          <div class="card flat">
            <div class="card-head"><h3>Ko‘rsatkichlar</h3>
              <span class="label">DTI · PTI · cash-flow</span></div>
            <div class="between"><span class="dim">DTI (jami yuk)</span>
              <b class="num">${pct(k.dti)}</b></div>
            <div class="between"><span class="dim">PTI (yangi to‘lov)</span>
              <span class="num">${pct(k.pti)}</span></div>
            <div class="between"><span class="dim">Mavjud DTI</span>
              <span class="num">${pct(k.dti_current)}</span></div>
            <div class="between"><span class="dim">Daromad medianasi</span>
              <span class="num">${money(k.income_median)}</span></div>
            <div class="between"><span class="dim">Daromad CV</span>
              <b class="num">${k.income_cv.toFixed(3)}</b></div>
            <div class="between"><span class="dim">Maks. kechikish</span>
              <span class="num">${k.max_delinq} kun</span></div>
          </div>
        </div>
        <div class="card flat">
          <div class="card-head"><h3>Ishga tushgan qoidalar</h3>
            <span class="label">${d.qoidalar.length} ta</span></div>
          ${d.qoidalar.length ? d.qoidalar.map(r => `<div class="rule-item">
              <span class="chip">${esc(r.kod)}</span>
              <span style="flex:1">${esc(r.matn)}</span>
              <span class="chip">${esc(r.ogirlik)}</span></div>`).join('')
            : '<div class="empty">Hech qanday cheklov ishga tushmadi.</div>'}
        </div>
        ${saved ? `<p class="code faint">jurnal yozuvi #${d.decision_id} ·
          skorkarta ${esc(d.scorecard_version)} · xodim ${esc(state.user.login)} ·
          yozuv o‘zgarmas</p>` : ''}
      </div>
    </details>
  </div>`;
}

/* -------------------------------------------------------------- skor halqa */
/* Jamoadosh loyihasidagi score-circle g'oyasi, lekin oddiy rangli halqa emas:
   arka ball qiymatiga proportsional to'ladi (300..900 shkala), rang qaror
   bandiga mos. Katta raqam markazda — hakam bir qarashda o'qiydi. */
function scoreRing(ball, size = 116) {
  const pol = state.meta.siyosat;
  const p = Math.max(0, Math.min(1, (ball - 300) / 600));
  const color = ball >= pol.APPROVE_SCORE ? 'var(--risk-low)'
              : ball >= pol.REVIEW_SCORE ? 'var(--risk-mid)' : 'var(--risk-hi)';
  const C = 100;                                  // aylana uzunligi = 100
  return `<svg class="score-ring" viewBox="0 0 42 42" style="width:${size}px;height:${size}px"
      role="img" aria-label="Ball ${ball.toFixed(0)}">
    <circle class="ring-track" r="15.9155" cx="21" cy="21"></circle>
    <circle class="ring-fill" r="15.9155" cx="21" cy="21" stroke="${color}"
      stroke-dasharray="${(p * C).toFixed(1)} ${(C - p * C).toFixed(1)}"
      stroke-dashoffset="25"></circle>
    <text x="21" y="21.5" class="ring-num" fill="${color}">${ball.toFixed(0)}</text>
    <text x="21" y="27.5" class="ring-sub">ball</text>
  </svg>`;
}

/* ------------------------------------------------------------------ donut */
function donut(parts) {
  const total = parts.reduce((a, [v]) => a + v, 0) || 1;
  const R = 15.9155;      // aylana uzunligi 100 bo'lsin — foizlar to'g'ri keladi
  let off = 25;           // 12 dan boshlansin
  const segs = parts.map(([v, c]) => {
    const p = v / total * 100;
    const el = `<circle r="${R}" cx="21" cy="21" fill="none" stroke="${c}"
      stroke-width="7" stroke-dasharray="${p} ${100 - p}"
      stroke-dashoffset="${off}"></circle>`;
    off -= p;
    return el;
  }).join('');
  return `<svg class="donut" viewBox="0 0 42 42" role="img"
    aria-label="Qarorlar taqsimoti">${segs}</svg>`;
}

/* =========================================================== UNDERWRITER */
async function loadUnderwriter() {
  const q = $('#uw-filter').value;
  const [rows, st] = await Promise.all([
    api('/api/arizalar?limit=300' + (q ? '&qaror=' + q : '')),
    api('/api/statistika'),
  ]);
  const s = st.statistika;
  const ok = s.qarorlar.MAQULLANDI || 0, mid = s.qarorlar.QOLDA_KORIB_CHIQISH || 0,
        no = s.qarorlar.RAD_ETILDI || 0;
  $('#uw-kpi').innerHTML = [
    ['Jami qaror', s.jami_qaror],
    ["Ma’qullangan", ok],
    ["Qo‘lda", mid],
    ['Rad etilgan', no],
  ].map(([l, v]) => `<div class="kpi-box"><div class="label">${l}</div>
      <div class="kpi">${nf.format(v)}</div></div>`).join('');

  // Donat + rad sabablari — jamoadosh loyihasidagi "Обзор" ekranidan olingan.
  $('#uw-overview').innerHTML = `
    <div class="card">
      <div class="card-head"><h3>Portfel holati</h3>
        <span class="label">${nf.format(s.jami_qaror)} qaror</span></div>
      <div class="donut-row">
        ${donut([[ok, 'var(--risk-low)'], [mid, 'var(--risk-mid)'],
                 [no, 'var(--risk-hi)']])}
        <div class="donut-leg">
          ${[['Ma’qullangan', ok, 'var(--risk-low)'],
             ["Qo‘lda ko‘rib chiqish", mid, 'var(--risk-mid)'],
             ['Rad etilgan', no, 'var(--risk-hi)']].map(([l, v, c]) => `
            <div><i style="background:${c}"></i><span style="flex:1">${l}</span>
              <b class="num">${nf.format(v)}</b>
              <em>${s.jami_qaror ? Math.round(v / s.jami_qaror * 100) : 0}%</em></div>`).join('')}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>Eng ko‘p rad sabablari</h3>
        <span class="label">oxirgi qarorlar</span></div>
      ${(st.rad_sabablari || []).length ? st.rad_sabablari.map((r, i) => {
        const max = st.rad_sabablari[0].n;
        return `<div class="reason-row">
          <span class="code">${i + 1}</span>
          <div style="flex:1;min-width:0">
            <div class="reason-txt">${esc(r.matn.split(';')[0].slice(0, 90))}</div>
            <div class="reason-bar"><i style="width:${Math.max(4, r.n / max * 100)}%"></i></div>
          </div>
          <b class="num">${r.n}</b></div>`;
      }).join('') : '<div class="empty">Rad etilgan qaror hali yo‘q</div>'}
    </div>`;

  const tb = $('#uw-table tbody');
  tb.innerHTML = rows.length ? rows.map(r => `
    <tr class="tr-click" data-id="${esc(r.application_id)}">
      <td class="code">${esc(r.application_id)}</td>
      <td>${verdict(r.qaror)}</td>
      <td class="r num">${r.ball.toFixed(0)}</td>
      <td class="r num">${pct(r.pd, 1)}</td>
      <td class="r num">${nf.format(Math.round(r.tavsiya_summa))}</td>
      <td class="code">${esc(r.kim || '—')}</td>
      <td class="dim" style="max-width:300px">${esc(String(r.sabab).slice(0, 110))}${
        String(r.sabab).length > 110 ? '…' : ''}</td>
    </tr>`).join('') : '<tr><td colspan="7" class="empty">qaror yo‘q</td></tr>';

  $$('#uw-table tbody tr.tr-click').forEach(tr => tr.onclick = () => {
    $$('#uw-table tbody tr').forEach(x => x.classList.remove('sel'));
    tr.classList.add('sel');
    showApplication(tr.dataset.id);
  });
  $('#uw-refresh').onclick = loadUnderwriter;
  $('#uw-filter').onchange = loadUnderwriter;

  const search = $('#uw-search');
  search.oninput = () => {
    const qq = search.value.trim().toUpperCase();
    let korindi = 0;
    $$('#uw-table tbody tr.tr-click').forEach(tr => {
      const mos = !qq || tr.dataset.id.toUpperCase().includes(qq);
      tr.hidden = !mos;
      if (mos) korindi++;
    });
    const bosh = $('#uw-empty');
    if (bosh) bosh.remove();
    if (!korindi) {
      $('#uw-table tbody').insertAdjacentHTML('beforeend',
        `<tr id="uw-empty"><td colspan="7" class="empty">«${esc(qq)}» bo‘yicha
          ariza topilmadi</td></tr>`);
    }
  };

  if (can('portfel:korish')) loadPortfolio();
  else $('#uw-portfel').hidden = true;
}

/** Holdout natijalari — ekrandagi CV AUC bilan yonma-yon. */
function holdoutBlock(h, m) {
  const q = h.qaror_sifati || {};
  const row = (k, nom) => q[k]
    ? `<tr><td>${nom}</td><td class="r num">${nf.format(q[k].n)}</td>
        <td class="r num">${pct(q[k].defolt, 1)}</td></tr>` : '';
  return `
    <div class="grid g2" style="margin-top:16px">
      <div class="card flat">
        <div class="card-head"><h3>Model sifati</h3>
          <span class="label">${nf.format(h.coverage)} ko‘rilmagan ariza</span></div>
        <div class="between"><span class="dim">AUC — holdout (test)</span>
          <b class="num">${h.auc}</b></div>
        <div class="between"><span class="dim">AUC — 5-fold CV (train)</span>
          <span class="num">${m.auc_cv ?? '—'}</span></div>
        <div class="between"><span class="dim">Gini / KS</span>
          <span class="num">${h.gini} / ${h.ks}</span></div>
        <div class="between"><span class="dim">Yuqori chegara (haqiqiy PD ning AUC si)</span>
          <span class="num">${h.ceiling_auc}</span></div>
        <p class="code faint" style="margin-top:8px">Natijalar PD dan tasodifiy
          chiqarilgan — hech qanday model ${h.ceiling_auc} dan oshib keta olmaydi;
          ${h.auc} bu yuqori chegaraning ${Math.round(h.auc / h.ceiling_auc * 100)}% i.</p>
      </div>
      <div class="card flat">
        <div class="card-head"><h3>Qaror sifati</h3>
          <span class="label">javob kaliti bo‘yicha</span></div>
        <div class="tw"><table><thead><tr><th>Qaror</th><th class="r">Ariza</th>
          <th class="r">Haqiqiy defolt</th></tr></thead><tbody>
          ${row('MAQULLANDI', "Ma’qullandi")}
          ${row('QOLDA_KORIB_CHIQISH', "Qo‘lda ko‘rib chiqish")}
          ${row('RAD_ETILDI', 'Rad etildi')}
        </tbody></table></div>
        <p class="code faint" style="margin-top:8px">Ma’qullangan portfelning
          defolt ulushi rad etilganidan sezilarli past bo\u2018lishi kutiladi —
          aniq raqamlar yuqoridagi jadvalda.</p>
      </div>
    </div>`;
}

/** Portfel kesimi: ball oshgani sari defolt ulushi kamayishini bitta rasmda. */
async function loadPortfolio() {
  const box = $('#uw-portfel');
  box.innerHTML = '<div class="loading">portfel tahlili…</div>';
  try {
    const p = await api('/api/portfel');
    const bins = p.taqsimot.filter(b => b.n > 0);
    const maxRate = Math.max(0.01, ...bins.map(b => b.defolt || 0));
    const cls = r => (r > 0.20 ? 'hi' : r > 0.08 ? 'mid' : 'low');
    const lo = bins[0].lo, hi = bins[bins.length - 1].hi;
    const posOf = v => ((v - lo) / Math.max(1, hi - lo)) * 100;
    box.innerHTML = `
      <div class="card-head"><h3>Portfel kesimi — ball qanchalik ajratadi</h3>
        <span class="label">${nf.format(p.n_train)} ta o‘quv arizasi</span></div>
      <p class="data dim" style="margin-bottom:6px">Ustun balandligi — shu ball
        oralig‘idagi <b>haqiqiy defolt ulushi</b>. Ball oshgani sari u monoton
        kamayishi kerak — skorkarta shuni isbotlaydi.</p>
      <div class="pf">
        ${bins.map(b => `<div class="col" title="${b.lo}–${b.hi} ball · ${b.n} ariza · defolt ${pct(b.defolt || 0)}">
            <span class="val">${pct(b.defolt || 0, 0)}</span>
            <div class="bar ${cls(b.defolt || 0)}"
                 style="height:${Math.max(2, (b.defolt || 0) / maxRate * 100)}%"></div>
          </div>`).join('')}
        <span class="pf-cut" style="left:${posOf(p.chegaralar.review)}%">
          <b>${p.chegaralar.review}</b></span>
        <span class="pf-cut" style="left:${posOf(p.chegaralar.approve)}%">
          <b>${p.chegaralar.approve}</b></span>
      </div>
      <div class="pf-axis">${bins.map(b => `<span>${b.lo}</span>`).join('')}</div>
      <div class="bands">
        ${p.band_sifati.map((b, i) => `<div class="${['hi','mid','low'][i]}">
            <div class="label">Ball ${esc(b.nom)}</div>
            <div class="rate">${pct(b.defolt || 0, 1)}</div>
            <div class="code faint" style="margin-top:4px">${nf.format(b.n)} ariza ·
              haqiqiy defolt</div></div>`).join('')}
      </div>
      ${p.holdout ? holdoutBlock(p.holdout, p.metrics) : ''}`;
  } catch (e) {
    box.innerHTML = `<div class="err">Portfel tahlili yuklanmadi: ${esc(e.message)}</div>`;
  }
}

async function showApplication(id) {
  $('#uw-detail').innerHTML = '<div class="loading">yuklanmoqda…</div>';
  try {
    const d = await api('/api/ariza/' + encodeURIComponent(id));
    const last = d.tarix[d.tarix.length - 1], p = last.payload;
    const a = (d.profil && d.profil.applicant) || {};
    const mi = p.mijoz_izohi;
    const aid = d.application && d.application.applicant_id;
    $('#uw-detail').innerHTML = `<div class="stack">
      <div class="card">
        <div class="card-head"><h3>${esc(id)}</h3>
          <span class="label">${esc(a.ism || 'yangi mijoz')}</span></div>
        <div class="between" style="align-items:center">
          <div>${verdict(last.qaror)}
            ${aid && a.ism ? `<p style="margin-top:10px"><a href="#mijoz/${esc(aid)}"
              class="code">Mijoz kartasi →</a></p>` : ''}</div>
          ${scoreRing(last.ball, 92)}
        </div>
        ${mi ? `<div class="verdict-box ${esc(mi.ohang)}" style="margin-top:12px">
            <p class="verdict-lead">${esc(mi.bosh_gap)}</p>
            ${(mi.tosqinlik_qildi || []).length ? `<div class="why" style="margin-top:14px">
              <div><div class="label" style="margin-bottom:8px">To‘sqinlik qildi</div>
                <ul class="bad">${mi.tosqinlik_qildi.map(x =>
                  `<li>${esc(x.matn)}<em>${x.ball.toFixed(0)}</em></li>`).join('')}</ul></div>
              <div><div class="label" style="margin-bottom:8px">Foydangizga ishladi</div>
                <ul class="good">${(mi.yordam_berdi || []).map(x =>
                  `<li>${esc(x.matn)}<em>+${x.ball.toFixed(0)}</em></li>`).join('')
                  || '<li style="padding-left:0">—</li>'}</ul></div>
            </div>` : ''}
          </div>` : ''}
        <div class="tech-note" style="margin-top:12px"><b>Rasmiy sabab.</b>
          ${esc(last.sabab)}</div>
      </div>
      <div class="card">
        <div class="card-head"><h3>Omillar hissasi</h3>
          <span class="label">ball ${last.ball.toFixed(0)}</span></div>
        ${contribRows(p.skoring.omillar)}
      </div>
      <div class="card">
        <div class="card-head"><h3>Qarorlar tarixi</h3>
          <span class="label">o‘zgarmas jurnal</span></div>
        ${d.tarix.map(h => `<div class="rule-item">
          <span class="chip">#${h.id}</span>
          <span style="flex:1">${esc(h.created_at)} · ${esc(h.scorecard)} ·
            xodim ${esc(h.kim || '—')} · ball ${h.ball.toFixed(0)}</span>
          ${verdict(h.qaror)}</div>
          <div class="hashline">hash ${esc(h.hash.slice(0, 32))}…</div>`).join('')}
      </div></div>`;
  } catch (e) {
    $('#uw-detail').innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

/* ========================================================= MIJOZ KARTASI */
let mkTimer = null;

async function loadMijozTab(arg) {
  const inp = $('#mk-search');
  if (!inp.dataset.wired) {
    inp.dataset.wired = '1';
    inp.oninput = () => {
      clearTimeout(mkTimer);
      mkTimer = setTimeout(() => searchClients(inp.value.trim()), 250);
    };
    $('#mk-clear').onclick = () => {
      inp.value = ''; $('#mk-results').innerHTML = '';
    };
  }
  if (arg) { inp.value = arg; await renderClientCard(arg); }
  else if (!state.mijoz) $('#mk-results').innerHTML = '';
}

async function searchClients(q) {
  const box = $('#mk-results');
  if (!q) { box.innerHTML = ''; return; }
  try {
    const rows = await api('/api/mijozlar?limit=12&q=' + encodeURIComponent(q));
    box.innerHTML = rows.length
      ? `<div style="margin-top:12px;border:1px solid var(--hair)">${rows.map(c => `
          <div class="mk-search-row" data-id="${esc(c.applicant_id)}">
            <span class="code">${esc(c.applicant_id)}</span>
            <b style="flex:1">${esc(c.ism)}</b>
            <span class="dim">${esc(c.bandlik)} · ${esc(c.viloyat)}</span>
          </div>`).join('')}</div>`
      : '<p class="empty">Mijoz topilmadi</p>';
    $$('#mk-results .mk-search-row').forEach(r => r.onclick = () => {
      location.hash = '#mijoz/' + r.dataset.id;
    });
  } catch (e) {
    box.innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

/** 12 oylik pul oqimi — bitta inline SVG, kutubxonasiz.
 *  Har oy uchun UCH yonma-yon ustun (kirim/chiqim/naqd) + qoldiq chizig'i.
 *  Avvalgi "ichma-ich" variant chalg'itardi: ustunlar ustma-ust tushib,
 *  ranglar aralashib ko'rinar edi. Yonma-yon guruh + gorizontal to'r bilan
 *  o'qish osonlashadi. */
function flowChart(flows) {
  if (!flows.length) return '<div class="empty">Oqim ma\u2019lumoti yo\u2018q</div>';
  const W = 720, H = 168, padT = 14, padB = 22, padL = 6, padR = 6;
  const n = flows.length;
  const slot = (W - padL - padR) / n;           // bir oyning kengligi
  const gw = slot * 0.72;                       // guruh kengligi
  const gap = 1.5, bw = (gw - 2 * gap) / 3;     // uch ustun + oraliqlar
  const max = Math.max(1, ...flows.map(f =>
    Math.max(f.kirim, f.chiqim, f.naqd_yechish, f.oy_oxiri_qoldiq)));
  const y = v => padT + (1 - v / max) * (H - padT - padB);
  const H0 = H - padB;

  // gorizontal to'r: 0 / 50% / 100%
  const grid = [0, .5, 1].map(t => {
    const yy = y(max * t);
    return `<line class="${t ? 'fg' : 'fg0'}" x1="${padL}" y1="${yy}" x2="${W - padR}" y2="${yy}"/>`
      + (t > 0 ? `<text class="fgl" x="${W - padR}" y="${yy - 3}">${
          max * t >= 1e6 ? (max * t / 1e6).toFixed(1) + ' mln' : Math.round(max * t / 1e3) + ' k'}</text>` : '');
  }).join('');

  let bars = '', pts = [], labels = '';
  flows.forEach((f, i) => {
    const x0 = padL + i * slot + (slot - gw) / 2;
    const bar = (v, dx, cls, nom) =>
      `<rect class="${cls}" x="${(x0 + dx).toFixed(1)}" y="${y(v).toFixed(1)}"
         width="${bw.toFixed(1)}" height="${Math.max(0, H0 - y(v)).toFixed(1)}" rx="1.5">
         <title>${esc(f.oy)} · ${nom}: ${money(v)}</title></rect>`;
    bars += bar(f.kirim, 0, 'inc', 'kirim')
          + bar(f.chiqim, bw + gap, 'exp', 'chiqim')
          + bar(f.naqd_yechish, 2 * (bw + gap), 'cash', 'naqd yechish');
    pts.push(`${(x0 + gw / 2).toFixed(1)},${y(f.oy_oxiri_qoldiq).toFixed(1)}`);
    const full = i === 0 || /-01$/.test(String(f.oy));
    labels += `<text class="fml" x="${(x0 + gw / 2).toFixed(1)}" y="${H - 6}">${
      esc(full ? String(f.oy).slice(2) : String(f.oy).slice(-2))}</text>`;
  });

  return `<svg class="flowchart" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="12 oylik pul oqimi">${grid}${bars}
      <polyline class="bal-c" points="${pts.join(' ')}"/>
      <polyline class="bal" points="${pts.join(' ')}"/>
      ${pts.map(pt => { const [px, py] = pt.split(',');
        return `<circle class="bald" cx="${px}" cy="${py}" r="2.4"/>`; }).join('')}
      ${labels}</svg>
    <div class="legend-dots">
      <span><i style="background:var(--flow-inc)"></i>kirim</span>
      <span><i style="background:var(--flow-exp)"></i>chiqim</span>
      <span><i style="background:var(--flow-cash)"></i>naqd yechish</span>
      <span><i style="background:var(--ink);height:2px;width:14px"></i>oy oxiri qoldiq</span></div>`;
}

async function renderClientCard(id) {
  const box = $('#mk-card');
  box.innerHTML = '<div class="loading">mijoz kartasi yuklanmoqda…</div>';
  try {
    const d = await api('/api/mijoz/' + encodeURIComponent(id));
    state.mijoz = d;
    const a = d.applicant, k = d.korsatkichlar;
    const risk = v => v === null || v === undefined ? '' :
      (v > 0.5 ? 'style="color:var(--risk-hi)"'
               : v > 0.35 ? 'style="color:var(--risk-mid)"'
                          : 'style="color:var(--risk-low)"');

    box.innerHTML = `<div class="stack">
      <div class="mk-hero">
        <span class="mk-ava">${esc(initials(a.ism))}</span>
        <div>
          <div class="mk-name">${esc(a.ism)}</div>
          <div class="mk-meta">
            <span class="code">${esc(a.applicant_id)}</span>
            <span>${a.yosh} yosh</span>
            <span>${esc(a.bandlik)}</span>
            <span>${esc(a.viloyat)}</span>
            <span>${esc(a.talim)}</span>
            <span>oila ${a.oila_azolari} kishi</span>
          </div>
        </div>
        <div style="text-align:right">
          <div class="label">Bank bilan</div>
          <div class="kpi">${a.mijoz_boldi_oy}<span class="data dim"> oy</span></div>
        </div>
      </div>

      <div class="grid g4">
        ${[['Daromad medianasi', money(k.daromad_median), `${a.deklaratsiya_daromad ?
             'deklaratsiya ' + money(a.deklaratsiya_daromad) : ''}`],
           ['Mavjud qarz yuki', k.mavjud_dti === null ? '—' : pct(k.mavjud_dti),
            `oyiga ${money(k.mavjud_oylik_tolov)}`],
           ['Daromad barqarorligi', k.daromad_cv.toFixed(2),
            k.daromad_cv < 0.15 ? 'barqaror' : k.daromad_cv < 0.3 ? 'o‘rtacha' : 'kuchli tebranadi'],
           ['To‘lov intizomi', k.max_kechikish + ' kun',
            k.max_kechikish >= 90 ? 'qattiq to‘siq' : k.max_kechikish > 0 ? 'kechikish bo‘lgan' : 'toza tarix'],
        ].map(([l, v, s]) => `<div class="kpi-box"><div class="label">${l}</div>
            <div class="kpi">${v}</div>
            <div class="code faint" style="margin-top:6px">${esc(s)}</div></div>`).join('')}
      </div>

      <div class="card">
        <div class="card-head"><h3>12 oylik pul oqimi</h3>
          <span class="label">kirim · chiqim · naqd · qoldiq</span></div>
        ${flowChart(d.oqim)}
        <div class="grid g4" style="margin-top:14px">
          <div class="between"><span class="dim">Sarf ulushi</span>
            <b class="num" ${risk(k.sarf_ulushi)}>${pct(k.sarf_ulushi)}</b></div>
          <div class="between"><span class="dim">Naqd ulushi</span>
            <b class="num" ${risk(k.naqd_ulushi)}>${pct(k.naqd_ulushi)}</b></div>
          <div class="between"><span class="dim">Zaxira</span>
            <b class="num">${k.zaxira_oy} oy</b></div>
          <div class="between"><span class="dim">Daromadsiz oylar</span>
            <b class="num">${k.nol_oylar}</b></div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h3>Mavjud kreditlar</h3>
          <span class="label">${d.kreditlar.length} ta · ${k.banklar_soni} bank</span></div>
        ${d.kreditlar.length ? `<div class="tw"><table>
          <thead><tr><th>Bank</th><th class="r">Summa</th><th class="r">Oylik to‘lov</th>
            <th class="r">Qoldiq</th><th class="r">Kechikish</th><th>Holat</th></tr></thead>
          <tbody>${d.kreditlar.map(l => `<tr>
            <td class="code">${esc(l.bank)}</td>
            <td class="r num">${nf.format(Math.round(l.summa))}</td>
            <td class="r num">${nf.format(Math.round(l.oylik_tolov))}</td>
            <td class="r num">${nf.format(Math.round(l.qoldiq))}</td>
            <td class="r num" ${l.max_kechikish_kun >= 90 ? 'style="color:var(--risk-hi)"' : ''}>${
              l.max_kechikish_kun}</td>
            <td>${esc(l.status)}</td></tr>`).join('')}</tbody></table></div>`
          : '<div class="empty">Boshqa banklarda kredit yo‘q</div>'}
      </div>

      <div class="card">
        <div class="card-head"><h3>Ariza tarixi</h3>
          <span class="label">${d.arizalar.length} ta</span></div>
        ${d.arizalar.length ? `<div class="tw"><table>
          <thead><tr><th>Ariza</th><th>Sana</th><th>Maqsad</th><th class="r">So‘ralgan</th>
            <th class="r">Ball</th><th>Qaror</th></tr></thead>
          <tbody>${d.arizalar.map(r => `<tr>
            <td class="code">${esc(r.application_id)}</td>
            <td class="code">${esc(r.ariza_sana)}</td>
            <td>${esc(r.maqsad)}</td>
            <td class="r num">${nf.format(Math.round(r.sorlgan_summa))}</td>
            <td class="r num">${r.ball !== null ? r.ball.toFixed(0) : '—'}</td>
            <td>${r.qaror ? verdict(r.qaror) : '<span class="chip">qaror yo‘q</span>'}</td>
            </tr>`).join('')}</tbody></table></div>`
          : '<div class="empty">Bu mijoz hali ariza bermagan</div>'}
      </div>

      <div class="card">
        <div class="card-head"><h3>O‘xshash mijozlar grafi</h3>
          <span class="label" id="graf-status">yuklanmoqda…</span></div>
        <p class="data dim" style="margin-bottom:10px">Savol: <b>xuddi shunday
          profilli mijozlar qanday to‘lagan?</b> Markazda — mijoz. Atrofida —
          risk-profili unga eng yaqin 8 mijoz (skorkartaning o‘sha 15 belgisi
          bo‘yicha): <b style="color:var(--risk-low)">yashil — to‘lagan</b>,
          <b style="color:var(--risk-hi)">qizil — defolt qilgan</b>. Chiziq
          ustida — qaysi belgilar bo‘yicha o‘xshash. Punktir — qo‘shnilar
          bir-biriga ham o‘xshash (zich klaster). Bu ballning vizual isboti:
          atrof qizarsa — bunday profillar haqiqatan defolt qiladi.</p>
        <div id="graf-chips" class="row" style="margin-bottom:10px;flex-wrap:wrap"></div>
        <div id="graf-wrap"><div class="loading">graf qurilmoqda…</div></div>
        <div class="legend-dots" style="margin-top:10px">
          <span><i style="background:var(--accent)"></i>mijoz (markaz)</span>
          <span><i style="background:var(--risk-hi)"></i>defolt qilgan o‘xshash</span>
          <span><i style="background:var(--risk-low)"></i>to‘lagan o‘xshash</span>
          <span><i style="background:var(--rule)"></i>bank / ariza</span>
        </div>
        <p class="code faint" id="graf-basis" style="margin-top:8px"></p>
      </div>

      <div class="row">
        <button class="btn" id="mk-new">Shu mijoz uchun yangi ariza</button>
      </div>
    </div>`;
    renderGraph(id);

    $('#mk-new').onclick = () => {
      location.hash = '#ariza';
      setTimeout(() => {
        setMode('mavjud');
        $('#f-applicant').value = id;
        loadMavjudKarta(id);
      }, 50);
    };
  } catch (e) {
    box.innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }
}

/* ============================================================= SKORKARTA */
async function loadScorecard() {
  const sc = await api('/api/scorecard');
  state.scorecard = sc;
  const m = sc.metrics;
  $('#sc-kpi').innerHTML = [
    ['AUC (5-fold CV)', (m.auc_cv ?? 0).toFixed(4)],
    ['AUC (in-sample)', (m.auc_in_sample ?? 0).toFixed(4)],
    ['KS', (m.ks ?? 0).toFixed(4)],
    ['Gini', (m.gini_in_sample ?? 0).toFixed(4)],
  ].map(([l, v]) => `<div class="kpi-box"><div class="label">${l}</div>
      <div class="kpi">${v}</div></div>`).join('');

  $('#sc-table tbody').innerHTML = sc.iv.map((r, i) => `
    <tr class="tr-click" data-i="${i}">
      <td>${esc(r.label)}<span class="bin code faint" style="display:block">${
        esc(r.key)}</span></td>
      <td class="r num">${r.iv.toFixed(4)}</td>
      <td><span class="chip">${esc(r.kuch)}</span></td>
      <td class="r num">${r.beta ? r.beta.toFixed(3) : '—'}</td>
      <td class="r num">${r.bins.length}</td></tr>`).join('');

  $$('#sc-table tbody tr').forEach(tr => tr.onclick = () => {
    $$('#sc-table tbody tr').forEach(x => x.classList.remove('sel'));
    tr.classList.add('sel');
    showBins(sc.iv[+tr.dataset.i]);
  });
  showBins(sc.iv[0]);
}

function showBins(r) {
  if (!r) return;
  const maxW = Math.max(1, ...r.bins.map(b => Math.abs(b.woe)));
  $('#sc-bins').innerHTML = `<div class="card">
    <div class="card-head"><h3>${esc(r.label)}</h3>
      <span class="label">IV ${r.iv.toFixed(4)} · ${esc(r.kuch)}</span></div>
    <p class="code faint" style="margin-bottom:10px">β = ${
      r.beta ? r.beta.toFixed(4) : 'modelda ishlatilmagan'} ·
      WOE = ln(P(bad)/P(good))</p>
    <div class="tw"><table><thead><tr><th>Bucket</th><th class="r">n</th>
      <th class="r">bad %</th><th class="r">WOE</th><th></th></tr></thead>
      <tbody>${r.bins.map(b => {
        const w = Math.abs(b.woe) / maxW * 46;
        return `<tr><td class="code">${esc(b.label)}</td>
          <td class="r num">${b.n}</td>
          <td class="r num">${pct(b.bad_rate)}</td>
          <td class="r num">${b.woe.toFixed(3)}</td>
          <td style="width:110px"><div class="bar"><span class="mid"></span>
            <i class="${b.woe > 0 ? 'neg' : 'pos'}" style="${b.woe > 0
              ? `left:50%;width:${w}%` : `right:50%;width:${w}%`}"></i></div></td>
          </tr>`; }).join('')}</tbody></table></div>
    <p class="code faint" style="margin-top:10px">Musbat WOE = xavf yuqori
      (ball kamayadi). Manfiy WOE = xavf past (ball oshadi).</p></div>`;
}

/* ================================================================ WHAT-IF */
function resetWhatIfControls() {
  ['#wi-inc', '#wi-sum', '#wi-yuk'].forEach(id => $(id).value = 100);
  $('#wi-muddat').value = state.base.muddat_oy;
}

function initWhatIf() {
  state.base = readForm();
  if (!state.whatIfReady) {
    ['#wi-inc', '#wi-sum', '#wi-yuk'].forEach(id => $(id).oninput = runWhatIf);
    $('#wi-muddat').onchange = runWhatIf;
    $('#wi-reset').onclick = () => { resetWhatIfControls(); runWhatIf(); };
    state.whatIfReady = true;
    resetWhatIfControls();
  }
  runWhatIf();
}

let wiTimer = null;
function runWhatIf() {
  const b = state.base;
  const f = { ...b,
    oylik_daromad: Math.round(b.oylik_daromad * $('#wi-inc').value / 100),
    deklaratsiya_daromad: Math.round(b.deklaratsiya_daromad * $('#wi-inc').value / 100),
    sorlgan_summa: Math.round(b.sorlgan_summa * $('#wi-sum').value / 100),
    mavjud_oylik_yuk: Math.round(b.mavjud_oylik_yuk * $('#wi-yuk').value / 100),
    muddat_oy: Number($('#wi-muddat').value),
    applicant_id: null };
  $('#wi-inc-v').textContent = money(f.oylik_daromad);
  $('#wi-sum-v').textContent = money(f.sorlgan_summa);
  $('#wi-yuk-v').textContent = money(f.mavjud_oylik_yuk);

  clearTimeout(wiTimer);
  wiTimer = setTimeout(async () => {
    try {
      const [now, base] = await Promise.all([
        post('/api/simulyatsiya', f),
        post('/api/simulyatsiya', { ...b, applicant_id: null }),
      ]);
      const sgn = (n, fmt) => (n > 0 ? '+' : n < 0 ? '−' : '') + fmt(Math.abs(n));
      const dBall = now.ball - base.ball;
      const dPd = (now.pd - base.pd) * 100;
      const dLim = now.limit.tolov_qobiliyati_limiti -
                   base.limit.tolov_qobiliyati_limiti;
      const cells = [
        ['Ball', now.ball.toFixed(0), dBall, sgn(dBall, v => v.toFixed(1))],
        ['PD', pct(now.pd, 2), -dPd, sgn(dPd, v => v.toFixed(2)) + ' p.p.'],
        ['Maksimal limit', nf.format(Math.round(now.limit.tolov_qobiliyati_limiti)),
         dLim, sgn(dLim, v => nf.format(Math.round(v)))],
      ];
      $('#wi-natija').innerHTML = `<div class="stack">
        <div class="grid g3">
          ${cells.map(([l, v, good, d]) => `<div class="kpi-box">
              <div class="label">${l}</div>
              <div class="kpi">${v}</div>
              <div class="code" style="margin-top:6px;color:${
                good > 0 ? 'var(--risk-low)'
                : good < 0 ? 'var(--risk-hi)' : 'var(--dim)'}">
                ${d} bazaviyga nisbatan</div>
              </div>`).join('')}
        </div>
        ${renderDecision(now, false)}</div>`;
    } catch (e) {
      $('#wi-natija').innerHTML = `<div class="err">${esc(e.message)}</div>`;
    }
  }, 200);
}

/* =============================================================== VERSIYA */
async function loadVersions() {
  const vs = await api('/api/scorecard/versions');
  state.versions = vs;
  $('#ver-table tbody').innerHTML = vs.map(v => `<tr>
    <td class="code">${v.id}</td><td><b>${esc(v.version)}</b>
      <span class="bin code faint" style="display:block">${esc(v.izoh || '')}</span></td>
    <td class="r num">${v.metrics.auc_cv ?? '—'}</td>
    <td class="r num">${v.metrics.ks ?? '—'}</td>
    <td class="code">${esc(v.valid_from)}</td>
    <td class="code">${esc(v.valid_to || '—')}</td>
    <td>${v.is_current ? '<span class="chip on">amalda</span>'
      : '<span class="chip">yopilgan</span>'}</td></tr>`).join('');

  const opts = vs.map(v => `<option value="${v.id}">${esc(v.version)}</option>`).join('');
  $('#cmp-a').innerHTML = opts;
  $('#cmp-b').innerHTML = opts;
  if (vs.length > 1) $('#cmp-b').value = vs[vs.length - 1].id;

  // Xom audit izi — faqat auditorga; qolganlar zanjir holatini ko'radi.
  const jr = $('#jr-out');
  try {
    if (can('jurnal:korish')) {
      const j = await api('/api/jurnal?limit=12');
      const z = j.zanjir;
      jr.innerHTML = `
        <div class="note ${z.butun ? '' : 'bad'}">
          Hash zanjiri: <b>${z.butun ? 'BUTUN' : 'BUZILGAN (#' + z.buzilgan_id + ')'}</b>
          · ${z.tekshirildi} yozuv tekshirildi</div>
        <div class="tw" style="margin-top:12px"><table><thead><tr><th>#</th>
          <th>Ariza</th><th>Qaror</th><th class="r">Ball</th><th>Xodim</th>
          <th>Versiya</th></tr></thead><tbody>${j.oxirgi.map(r => `<tr>
            <td class="code">${r.id}</td><td class="code">${esc(r.application_id)}</td>
            <td>${verdict(r.qaror)}</td><td class="r num">${r.ball.toFixed(0)}</td>
            <td class="code">${esc(r.kim || '—')}</td>
            <td class="code">${esc(r.scorecard)}</td></tr>`).join('')}
          </tbody></table></div>`;
    } else {
      const st = await api('/api/statistika');
      const z = st.zanjir;
      jr.innerHTML = `<div class="note ${z.butun ? '' : 'bad'}">
          Hash zanjiri: <b>${z.butun ? 'BUTUN' : 'BUZILGAN'}</b> ·
          ${z.tekshirildi} yozuv tekshirildi</div>
        <p class="code faint" style="margin-top:10px">Xom jurnal yozuvlari faqat
          «Administrator» rolida ochiladi.</p>`;
    }
  } catch (e) {
    jr.innerHTML = `<div class="err">${esc(e.message)}</div>`;
  }

  if (can('skorkarta:orgatish')) {
    $('#rt-run').onclick = async () => {
      const btn = $('#rt-run');
      if (btn.disabled) return;
      btn.disabled = true;
      $('#rt-out').innerHTML = '<div class="loading">o‘rgatilmoqda…</div>';
      try {
        const r = await post('/api/scorecard/retrain', {
          version: $('#rt-ver').value, l2: Number($('#rt-l2').value),
          izoh: $('#rt-izoh').value });
        $('#rt-out').innerHTML = `<div class="note"><b>${esc(r.version)}</b> tayyor ·
          AUC CV ${r.metrics.auc_cv} · KS ${r.metrics.ks} ·
          ${r.belgilar.length} belgi</div>`;
        await loadVersions(); await renderChips();
      } catch (e) {
        $('#rt-out').innerHTML = `<div class="err">${esc(e.message)}</div>`;
      } finally { btn.disabled = false; }
    };
  }

  $('#cmp-run').onclick = async () => {
    const cbtn = $('#cmp-run');
    if (cbtn.disabled) return;
    const id = $('#cmp-app').value.trim();
    if (!id) { $('#cmp-out').innerHTML = '<div class="err">Ariza ID kiriting</div>'; return; }
    cbtn.disabled = true;
    $('#cmp-out').innerHTML = '<div class="loading">hisoblanmoqda…</div>';
    try {
      const r = await api(`/api/ariza/${encodeURIComponent(id)}/taqqoslash` +
        `?a=${$('#cmp-a').value}&b=${$('#cmp-b').value}`);
      $('#cmp-out').innerHTML = `
        <div class="grid g2" style="margin-bottom:12px">
          <div class="kpi-box"><div class="label">${esc(
            $('#cmp-a').selectedOptions[0].text)}</div>
            <div class="kpi">${r.a.ball.toFixed(0)}</div>
            <div class="code faint" style="margin-top:4px">PD ${pct(r.a.pd, 2)} ·
              ${esc(r.a.qaror)}</div></div>
          <div class="kpi-box"><div class="label">${esc(
            $('#cmp-b').selectedOptions[0].text)}</div>
            <div class="kpi">${r.b.ball.toFixed(0)}</div>
            <div class="code faint" style="margin-top:4px">PD ${pct(r.b.pd, 2)} ·
              ${esc(r.b.qaror)}</div></div></div>
        <div class="note">Ball farqi <b>${r.delta_ball > 0 ? '+' : ''}${
          r.delta_ball}</b> · PD farqi ${(r.delta_pd * 100).toFixed(2)} p.p.</div>
        <div class="tw" style="margin-top:12px"><table><thead><tr><th>Omil</th>
          <th class="r">A</th><th class="r">B</th><th class="r">Δ</th></tr></thead>
          <tbody>${r.farq.map(f => `<tr><td>${esc(f.label)}</td>
            <td class="r num">${f.a.toFixed(1)}</td>
            <td class="r num">${f.b.toFixed(1)}</td>
            <td class="r num" style="color:${f.delta > 0 ? 'var(--risk-low)'
              : 'var(--risk-hi)'}">${f.delta > 0 ? '+' : ''}${f.delta}</td>
            </tr>`).join('')}</tbody></table></div>`;
    } catch (e) {
      $('#cmp-out').innerHTML = `<div class="err">${esc(e.message)}</div>`;
    } finally { cbtn.disabled = false; }
  };
}

/* ========================================================== ALOQALAR GRAFI */
/* Jonli force-directed simulyatsiya — kutubxonasiz, FindDroppers ruhida:
   graf ochilganda tugunlar harakatda joylashadi (requestAnimationFrame),
   sudralganda fizika qayta qiziydi, tugun bosilganda yon panelda tafsilot,
   hover da bog'liq qirralar yoritiladi. Sarlavhada qatlam statistikasi:
   nima kesildi (cuts), nima ishlamadi (partial) — yashirmaymiz. */
async function renderGraph(applicantId) {
  const wrap = $('#graf-wrap');
  let g;
  try {
    g = await api('/api/mijoz/' + encodeURIComponent(applicantId) + '/graf');
  } catch (e) {
    wrap.innerHTML = `<div class="err">Graf yuklanmadi: ${esc(e.message)}</div>`;
    return;
  }

  // ── sarlavha statistikasi: FindDroppers dagi took/cuts/partial ──
  $('#graf-status').textContent =
    `${g.nodes.length} tugun · ${g.edges.length} aloqa · ${g.took.total} ms`;
  const chips = [];
  chips.push(`<span class="chip">o‘xshash: ${g.similar}</span>`);
  chips.push(`<span class="chip">setka: ${g.mesh_edges} qirra</span>`);
  for (const [k, c] of Object.entries(g.cuts || {})) {
    chips.push(`<span class="chip">${esc(k)}: ${c.kept}/${c.total} ko‘rsatildi</span>`);
  }
  for (const f of g.partial || []) {
    chips.push(`<span class="chip" style="color:var(--risk-hi)">${esc(f)} ishlamadi</span>`);
  }
  $('#graf-chips').innerHTML = chips.join('');
  $('#graf-basis').textContent = 'Asos: ' + g.basis +
    '. Bu datasetda yo\u2018q: ' + g.missing.join(', ') + '.';

  const W = 760, H = 430;
  const nodes = g.nodes.map(n => ({ ...n, x: 0, y: 0, vx: 0, vy: 0 }));
  const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  const edges = g.edges.filter(e => byId[e.source] && byId[e.target])
    .sort((a, b) => (b.kind === 'mesh') - (a.kind === 'mesh'));   // mesh pastda
  const adj = {};                                 // hover yoritish uchun
  edges.forEach((e, i) => {
    (adj[e.source] = adj[e.source] || []).push(i);
    (adj[e.target] = adj[e.target] || []).push(i);
  });

  const root = nodes.find(n => n.root) || nodes[0];
  let ang = 0;
  nodes.forEach(n => {
    if (n === root) { n.x = W / 2; n.y = H / 2; return; }
    const r = 40 + Math.random() * 30;            // markazdan boshlab tarqaladi
    ang += 2.399963;
    n.x = W / 2 + r * Math.cos(ang);
    n.y = H / 2 + r * Math.sin(ang);
  });

  const nodeColor = n => {
    if (n.root) return 'var(--accent)';
    if (n.type === 'client') {
      return n.natija === 'defolt' ? 'var(--risk-hi)'
           : n.natija === 'toladi' ? 'var(--risk-low)' : 'var(--rule)';
    }
    if (n.type === 'ariza') {
      return n.qaror === 'RAD_ETILDI' || n.qaror === 'defolt' ? 'var(--risk-hi)'
           : n.qaror ? 'var(--risk-low)' : 'var(--rule)';
    }
    return 'var(--rule)';
  };
  const nodeR = n => n.root ? 17 : n.type === 'client' ? 12 : 9;

  wrap.innerHTML = `
    <div class="graf-split">
      <svg class="graf" viewBox="0 0 ${W} ${H}">
        ${edges.map((e, i) => {
          const cls = e.kind === 'mesh' ? 'ge-mesh' : e.kind === 'similar' ? 'ge-sim' : 'ge-attr';
          // Masofa qanchalik kichik (o'xshashroq) — chiziq shunchalik qalin.
          // Diapazon o'lchangan: eng yaqinlari ~0.3, chegara 1.15.
          const w = e.kind === 'similar'
              ? Math.max(1.2, 3.4 - (e.dist || 1) * 2).toFixed(1)
              : e.kind === 'mesh' ? 1 : 1.5;
          const tip = e.kind === 'similar'
              ? `o\u2018xshashlik ${e.dist} · yaqin belgilar: ${e.label}`
              : e.kind === 'mesh' ? `o\u2018zaro o\u2018xshash · masofa ${e.dist}`
              : e.label || e.kind;
          return `<line class="${cls}" data-i="${i}" stroke-width="${w}">
            <title>${esc(tip)}</title></line>`;
        }).join('')}
        ${nodes.map((n, i) => {
          const r = nodeR(n);
          const sub = n.root ? '' :
            n.natija === 'toladi' ? "to\u2018lagan"
            : n.natija === 'defolt' ? 'defolt'
            : n.type === 'bank' ? 'bank' : n.type === 'ariza' ? 'ariza' : '';
          return `
          <g class="gn" data-i="${i}">
            ${n.root ? `<circle r="${r + 4.5}" class="root-halo"></circle>` : ''}
            <circle r="${r}" fill="${nodeColor(n)}"></circle>
            <text y="${r + 11}">${esc(String(n.label).slice(0, 18))}</text>
            ${sub ? `<text y="${r + 21}" class="gsub2 ${
                n.natija === 'defolt' ? 'bad' : ''}">${sub}</text>` : ''}
          </g>`;
        }).join('')}
      </svg>
      <div class="graf-info" id="graf-info">
        <div class="label" style="margin-bottom:8px">Tugun tafsiloti</div>
        <p class="data dim">Tugunni bosing — tafsilot shu yerda. Sudrash mumkin,
          o‘xshash mijozga ikki bosishda o‘tiladi.</p>
      </div>
    </div>`;

  const svg = wrap.querySelector('svg');
  const lineEls = [...svg.querySelectorAll('line')];
  const gEls = [...svg.querySelectorAll('g.gn')];

  function paint() {
    lineEls.forEach((el, i) => {
      const e = edges[i], a = byId[e.source], b = byId[e.target];
      el.setAttribute('x1', a.x); el.setAttribute('y1', a.y);
      el.setAttribute('x2', b.x); el.setAttribute('y2', b.y);
    });
    gEls.forEach((el, i) =>
      el.setAttribute('transform', `translate(${nodes[i].x},${nodes[i].y})`));
  }

  // ── jonli simulyatsiya: sovuguncha aylanaveradi, sudrash qayta qizdiradi ──
  let heat = 1.0, rafId = null;
  function tick() {
    const k = 0.02;
    for (const e of edges) {
      const a = byId[e.source], b = byId[e.target];
      const want = e.kind === 'loan' || e.kind === 'ariza' ? 90
                 : e.kind === 'mesh' ? 115 : 155;
      const dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(1, Math.hypot(dx, dy));
      const f = k * (d - want) / d;
      a.vx += f * dx; a.vy += f * dy;
      b.vx -= f * dx; b.vy -= f * dy;
    }
    for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      const dx = b.x - a.x, dy = b.y - a.y;
      const d2 = Math.max(120, dx * dx + dy * dy);
      const f = 1700 / d2, d = Math.sqrt(d2);
      a.vx -= f * dx / d; a.vy -= f * dy / d;
      b.vx += f * dx / d; b.vy += f * dy / d;
    }
    for (const n of nodes) {
      if (n.root || n._pin) { n.vx = n.vy = 0; continue; }
      n.x = Math.max(28, Math.min(W - 28, n.x + n.vx * heat));
      n.y = Math.max(22, Math.min(H - 26, n.y + n.vy * heat));
      n.vx *= 0.82; n.vy *= 0.82;
    }
    paint();
    heat *= 0.985;
    if (heat > 0.02) rafId = requestAnimationFrame(tick);
  }
  const reheat = () => {
    heat = Math.max(heat, 0.5);
    cancelAnimationFrame(rafId);
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);

  // ── hover: bog'liq qirralarni yoritish ──
  gEls.forEach((el, i) => {
    el.addEventListener('pointerenter', () => {
      const on = new Set(adj[nodes[i].id] || []);
      lineEls.forEach((l, li) => l.classList.toggle('ge-hot', on.has(li)));
      const nbr = new Set([nodes[i].id]);
      on.forEach(li => { nbr.add(edges[li].source); nbr.add(edges[li].target); });
      gEls.forEach((x, xi) => x.classList.toggle('gn-dim', !nbr.has(nodes[xi].id)));
      svg.classList.add('graf-focus');
    });
    el.addEventListener('pointerleave', () => {
      lineEls.forEach(l => l.classList.remove('ge-hot'));
      gEls.forEach(x => x.classList.remove('gn-dim'));
      svg.classList.remove('graf-focus');
    });
  });

  // ── tugun tafsiloti paneli ──
  function showNode(n) {
    const rows = [];
    if (n.type === 'client') {
      rows.push(['Turi', n.root ? 'markaziy mijoz' : 'o\u2018xshash mijoz']);
      if (n.sub) rows.push(['ID', n.sub]);
      if (n.ball) rows.push(['Ball', n.ball]);
      if (n.natija) rows.push(['Natija', n.natija === 'toladi' ? 'to\u2018lagan'
        : n.natija === 'defolt' ? 'defolt qilgan' : n.natija]);
      if (n.bandlik) rows.push(['Bandlik', n.bandlik]);
      if (n.viloyat) rows.push(['Viloyat', n.viloyat]);
    } else if (n.type === 'bank') {
      rows.push(['Turi', 'bank (mavjud kredit)']);
    } else if (n.type === 'ariza') {
      rows.push(['Turi', 'ariza']);
      if (n.sub) rows.push(['Maqsad', n.sub]);
      if (n.qaror) rows.push(['Qaror', n.qaror]);
      if (n.ball) rows.push(['Ball', n.ball]);
    }
    $('#graf-info').innerHTML = `
      <div class="label" style="margin-bottom:8px">Tugun tafsiloti</div>
      <b style="display:block;margin-bottom:8px">${esc(n.label)}</b>
      ${rows.map(([k, v]) => `<div class="between" style="padding:3px 0">
        <span class="dim">${k}</span><span>${esc(String(v))}</span></div>`).join('')}
      ${n.type === 'client' && !n.root && n.sub
        ? `<button class="btn mini" style="margin-top:10px"
             onclick="location.hash='#mijoz/${esc(n.sub)}'">Kartasiga o\u2018tish</button>`
        : ''}`;
  }

  // ── sudrash + tanlash ──
  let drag = null;
  const pos = ev => {
    const r = svg.getBoundingClientRect();
    const p = ev.touches ? ev.touches[0] : ev;
    return [(p.clientX - r.left) * W / r.width, (p.clientY - r.top) * H / r.height];
  };
  gEls.forEach((el, i) => {
    el.addEventListener('pointerdown', ev => {
      drag = i; nodes[i]._pin = true; ev.preventDefault();
      gEls.forEach(x => x.classList.remove('gn-sel'));
      el.classList.add('gn-sel');
      showNode(nodes[i]);
    });
    el.addEventListener('dblclick', () => {
      const n = nodes[i];
      if (n.type === 'client' && !n.root && n.sub) location.hash = '#mijoz/' + n.sub;
    });
  });
  svg.addEventListener('pointermove', ev => {
    if (drag === null) return;
    const [x, y] = pos(ev);
    nodes[drag].x = x; nodes[drag].y = y;
    reheat();
  });
  addEventListener('pointerup', () => {
    if (drag !== null) nodes[drag]._pin = nodes[drag].root ? true : false;
    drag = null;
  });
}

/* ================================================================== boot *//* ================================================================== boot */
async function afterLogin() {
  renderUser();
  applyRoleLocks();
  await renderChips();
  if (!state.meta) state.meta = await api('/api/meta');
  await initForm();
  const { name, arg } = parseHash();
  setTab(name || TABS.find(t => can(PAGES[t].perm)) || 'ariza',
         { silent: !name, arg });
  keepAlive();
}

/** Sessiya jonli ushlansin: foydalanuvchi ishlayotgan bo'lsa uzilib qolmasin. */
function keepAlive() {
  let last = Date.now();
  ['mousedown', 'keydown', 'scroll', 'touchstart'].forEach(e =>
    addEventListener(e, () => { last = Date.now(); }, { passive: true }));
  setInterval(() => {
    if (Date.now() - last < 5 * 60 * 1000) fetch('/api/auth/me').catch(() => {});
  }, 4 * 60 * 1000);
}

(async function boot() {
  initTheme(); initTabs(); await initGate();
  try {
    const r = await fetch('/api/auth/me');
    if (!r.ok) { showGate(''); return; }
    state.user = await r.json();
    $('#login-gate').hidden = true;
    await afterLogin();
  } catch (e) {
    showGate('Server bilan aloqa yo‘q: ' + e.message);
  }
})();
