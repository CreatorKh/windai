"""Logistik regressiya — BONUS ALGORITM.

Sof Python (numpy siz) IRLS / Newton-Raphson. Belgilar soni kichik (~20), shu
sababli to'liq Gessian bilan Newton usuli eng tez yaqinlashuvni beradi:
odatda 6-8 iteratsiya. L2 regulyarizatsiya kolinear WOE belgilarini ushlab
turadi va Hessian ni musbat aniq qiladi.

Koeffitsientlar izohlanadi: WOE bo'yicha o'rgatilgani uchun beta_j > 0 =>
"bu belgi WOE oshgani sari xavf oshadi" degani, ya'ni ishorasi ma'noli.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple


def sigmoid(z: float) -> float:
    """Sonli barqaror logistik funksiya (overflow'siz)."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _solve(A: List[List[float]], b: List[float]) -> List[float]:
    """Gauss–Jordan qisman pivotlash bilan. O(k^3), k = belgilar soni + 1."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            M[col][col] += 1e-8            # singular -> kichik ridge qo'shamiz
            piv = col
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        M[col] = [v / pv for v in M[col]]
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            if f:
                M[r] = [vr - f * vc for vr, vc in zip(M[r], M[col])]
    return [M[i][n] for i in range(n)]


class LogisticRegression:
    """L2-regulyarizatsiyalangan logistik regressiya, IRLS bilan yechiladi."""

    def __init__(self, l2: float = 1.0, max_iter: int = 50, tol: float = 1e-7,
                 max_halvings: int = 30):
        self.l2 = l2
        self.max_iter = max_iter
        self.tol = tol
        self.max_halvings = max_halvings
        self.converged = False
        self.intercept: float = 0.0
        self.coef: List[float] = []
        self.names: List[str] = []
        self.n_iter: int = 0

    # -- o'rgatish -----------------------------------------------------------
    @staticmethod
    def _softplus(z: float) -> float:
        """log(1 + e^z), overflow'siz."""
        return z + math.log1p(math.exp(-z)) if z > 0 else math.log1p(math.exp(z))

    def _nll_from_z(self, zs: Sequence[float], y: Sequence[int],
                    beta: Sequence[float]) -> float:
        """Jarima qo'shilgan manfiy log-ehtimollik, tayyor z lar bo'yicha."""
        sp = self._softplus
        total = 0.0
        for z, yi in zip(zs, y):
            total += sp(z) - yi * z
        return total + 0.5 * self.l2 * sum(b * b for b in beta[1:])

    def _penalized_nll(self, X, y, beta) -> float:
        """Xom X dan hisoblaydigan variant (testlar va tashqi chaqiruvlar uchun)."""
        b0, bs = beta[0], beta[1:]
        zs = [b0 + sum(b * v for b, v in zip(bs, xi)) for xi in X]
        return self._nll_from_z(zs, y, beta)

    def fit(self, X: List[List[float]], y: Sequence[int],
            names: Optional[List[str]] = None) -> "LogisticRegression":
        """Damped Newton (IRLS + step-halving line search).

        Nega demplash kerak: kredit ma'lumotlarida deyarli to'liq ajralish
        (quasi-complete separation) odatiy hol — masalan "ishsiz" belgisi
        defoltni juda kuchli ajratadi. Sof Newton bunday holatda qadamni
        oshirib yuboradi: p -> 0/1, vazn w = p(1-p) -> 0, Gessian singular
        bo'lib qoladi va koeffitsientlar portlaydi (beta ~ 100, AUC -> 0.5).
        Har qadamda maqsad funksiyasi kamayishini talab qilib, qadamni
        kerak bo'lsa ikkiga bo'lamiz — bu global yaqinlashuvni kafolatlaydi.

        Tezlik nuqtasi: line search ichida z ni noldan qayta hisoblash
        O(n*k) turadi va halving har safar takrorlanadi. Buning o'rniga
        yo'nalish bo'yicha hosila dz = step . [1, x] bir marta hisoblanadi,
        keyin har bir sinov uchun z_cand = z + t*dz — ya'ni O(n).

        Big-O: O(iter * n * k^2) Gessian yig'ishga + O(iter * k^3) yechishga
        + O(iter * halvings * n) line search'ga. n = arizalar, k = belgilar.
        """
        n = len(X)
        if n == 0:
            raise ValueError("bo'sh o'quv to'plami")
        k = len(X[0])
        self.names = names or [f"x{i}" for i in range(k)]
        beta = [0.0] * (k + 1)                       # [intercept, ...coef]

        base = sum(y) / n
        base = min(max(base, 1e-6), 1 - 1e-6)
        beta[0] = math.log(base / (1 - base))        # aqlli boshlang'ich nuqta

        # Har bir satrga [1.0, *x] — Gessian ichida qayta-qayta yasamaslik uchun.
        rows = [[1.0] + list(xi) for xi in X]
        kk = k + 1
        zs = [beta[0]] * n
        obj = self._nll_from_z(zs, y, beta)
        l2 = self.l2
        tol = self.tol

        for it in range(self.max_iter):
            grad = [0.0] * kk
            H = [[0.0] * kk for _ in range(kk)]
            for row, yi, z in zip(rows, y, zs):
                p = sigmoid(z)
                w = max(p * (1.0 - p), 1e-6)         # Gessian singular bo'lmasin
                r = yi - p
                for a in range(kk):
                    ra_row = row[a]
                    if ra_row == 0.0:
                        continue
                    grad[a] += r * ra_row
                    ra = w * ra_row
                    Ha = H[a]
                    for bidx in range(a, kk):
                        Ha[bidx] += ra * row[bidx]
            for a in range(kk):                      # simmetriyani to'ldirish
                for bidx in range(a):
                    H[a][bidx] = H[bidx][a]
            # L2 (intercept jazolanmaydi)
            for a in range(1, kk):
                grad[a] -= l2 * beta[a]
                H[a][a] += l2

            if max(abs(g) for g in grad) < tol:
                self.n_iter = it
                break

            step = _solve(H, grad)

            # Yo'nalish bo'yicha z ning o'zgarishi — bir marta hisoblanadi.
            dz = [sum(s * v for s, v in zip(step, row)) for row in rows]

            # --- line search: maqsad kamaymaguncha qadamni yarimlaymiz -------
            t, accepted, delta = 1.0, False, 0.0
            for _ in range(self.max_halvings):
                cand = [b + t * s for b, s in zip(beta, step)]
                cand_zs = [z + t * d for z, d in zip(zs, dz)]
                cand_obj = self._nll_from_z(cand_zs, y, cand)
                if cand_obj <= obj:
                    beta, zs, delta, obj = cand, cand_zs, obj - cand_obj, cand_obj
                    accepted = True
                    break
                t *= 0.5
            self.n_iter = it + 1
            if not accepted:            # hech qanday qadam yaxshilamadi -> optimum
                break
            if delta < tol * (1.0 + abs(obj)):
                break

        self.intercept, self.coef = beta[0], beta[1:]
        self.converged = self.n_iter < self.max_iter
        return self

    # -- bashorat ------------------------------------------------------------
    def decision_value(self, x: Sequence[float]) -> float:
        return self.intercept + sum(b * v for b, v in zip(self.coef, x))

    def predict_proba(self, x: Sequence[float]) -> float:
        return sigmoid(self.decision_value(x))

    def contributions(self, x: Sequence[float]) -> Dict[str, float]:
        """Har bir belgining log-odds ga qo'shgan hissasi (beta_j * x_j)."""
        return {n: b * v for n, b, v in zip(self.names, self.coef, x)}

    # -- serializatsiya ------------------------------------------------------
    def to_dict(self) -> dict:
        return {"intercept": self.intercept, "coef": self.coef,
                "names": self.names, "l2": self.l2, "n_iter": self.n_iter,
                "converged": self.converged}

    @staticmethod
    def from_dict(d: dict) -> "LogisticRegression":
        m = LogisticRegression(l2=d.get("l2", 1.0))
        m.intercept = d["intercept"]
        m.coef = list(d["coef"])
        m.names = list(d["names"])
        m.n_iter = d.get("n_iter", 0)
        m.converged = d.get("converged", True)
        return m


# ---------------------------------------------------------------------------
# Baholash metrikalari
# ---------------------------------------------------------------------------


def auc_roc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Mann–Whitney U orqali AUC. Teng ballar uchun o'rtacha rank.

    Big-O: O(n log n). Chekka holat: bitta sinf bo'lsa -> 0.5.
    """
    pairs = sorted(zip(y_score, y_true), key=lambda p: p[0])
    n = len(pairs)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for t in range(i, j + 1):
            ranks[t] = avg
        i = j + 1
    n_pos = sum(t for _, t in pairs)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum = sum(r for r, (_, t) in zip(ranks, pairs) if t == 1)
    return (rank_sum - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def gini(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    return 2.0 * auc_roc(y_true, y_score) - 1.0


def ks_statistic(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    """Kolmogorov–Smirnov: good/bad kumulyativ taqsimotlari orasidagi maksimal farq."""
    pairs = sorted(zip(y_score, y_true), key=lambda p: p[0])
    n_pos = sum(t for _, t in pairs) or 1
    n_neg = (len(pairs) - sum(t for _, t in pairs)) or 1
    cp = cn = 0
    best = 0.0
    for _, t in pairs:
        cp += t
        cn += 1 - t
        best = max(best, abs(cp / n_pos - cn / n_neg))
    return best


def brier_score(y_true: Sequence[int], y_prob: Sequence[float]) -> float:
    if not y_true:
        return 0.0
    return sum((p - t) ** 2 for t, p in zip(y_true, y_prob)) / len(y_true)
