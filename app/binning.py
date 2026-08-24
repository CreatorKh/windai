"""WOE / IV binning — BONUS ALGORITM.

Har bir belgini monoton bo'lmagan, lekin izohlanuvchi bucket'larga bo'lamiz va
har bir bucket uchun Weight of Evidence hisoblaymiz:

    WOE_i = ln( (bad_i / bad_total) / (good_i / good_total) )
    IV    = SUM_i (bad_rate_i - good_rate_i) * WOE_i

WOE ning ikkita foydasi bor:
  * chiziqli modelga monotonlik va outlier'ga chidamlilik beradi;
  * har bir bucket "risk birligi" da o'lchanadi -> qarorni tushuntirish oson.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from .config import LAPLACE, MAX_BINS, MIN_BIN_FRACTION, MIN_CATEGORY_N


class Bin:
    """Bitta bucket: chegara yoki kategoriyalar to'plami + WOE."""

    __slots__ = ("lo", "hi", "categories", "woe", "n", "bad", "label")

    def __init__(self, lo=None, hi=None, categories=None, woe=0.0,
                 n=0, bad=0, label=""):
        self.lo = lo
        self.hi = hi
        self.categories = categories
        self.woe = woe
        self.n = n
        self.bad = bad
        self.label = label

    def contains(self, value) -> bool:
        if self.categories is not None:
            return value in self.categories
        lo = -math.inf if self.lo is None else self.lo
        hi = math.inf if self.hi is None else self.hi
        return lo <= value < hi

    @property
    def bad_rate(self) -> float:
        return self.bad / self.n if self.n else 0.0

    def to_dict(self) -> dict:
        return {
            "lo": None if self.lo in (None, -math.inf) else self.lo,
            "hi": None if self.hi in (None, math.inf) else self.hi,
            "categories": sorted(self.categories) if self.categories else None,
            "woe": self.woe, "n": self.n, "bad": self.bad,
            "label": self.label, "bad_rate": self.bad_rate,
        }

    @staticmethod
    def from_dict(d: dict) -> "Bin":
        return Bin(
            lo=d.get("lo"), hi=d.get("hi"),
            categories=set(d["categories"]) if d.get("categories") else None,
            woe=d.get("woe", 0.0), n=d.get("n", 0), bad=d.get("bad", 0),
            label=d.get("label", ""),
        )


class FeatureBinning:
    """Bitta belgi uchun bin to'plami + IV."""

    def __init__(self, name: str, bins: List[Bin], iv: float, kind: str,
                 default_woe: float = 0.0):
        self.name = name
        self.bins = bins
        self.iv = iv
        self.kind = kind                 # "numeric" | "categorical"
        self.default_woe = default_woe   # ko'rilmagan qiymat uchun

    def woe_of(self, value) -> Tuple[float, Bin]:
        """Qiymatni bucket'ga solib WOE qaytaradi. O(k), k = binlar soni (<= 6)."""
        for b in self.bins:
            if b.contains(value):
                return b.woe, b
        # Ko'rilmagan kategoriya / NaN -> neytral WOE (yangi qiymat jazolanmasin).
        fallback = Bin(categories={value} if self.kind == "categorical" else None,
                       woe=self.default_woe, label="boshqa")
        return self.default_woe, fallback

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "iv": self.iv,
                "default_woe": self.default_woe,
                "bins": [b.to_dict() for b in self.bins]}

    @staticmethod
    def from_dict(d: dict) -> "FeatureBinning":
        return FeatureBinning(d["name"], [Bin.from_dict(b) for b in d["bins"]],
                              d["iv"], d["kind"], d.get("default_woe", 0.0))


# ---------------------------------------------------------------------------
# O'rgatish
# ---------------------------------------------------------------------------


def _woe_iv(groups: List[Tuple[int, int]], total_bad: int, total_good: int
            ) -> Tuple[List[float], float]:
    """Har bir (n, bad) guruh uchun WOE va umumiy IV. Laplace tekislash bilan."""
    woes, iv = [], 0.0
    for n, bad in groups:
        good = n - bad
        p_bad = (bad + LAPLACE) / (total_bad + LAPLACE * len(groups))
        p_good = (good + LAPLACE) / (total_good + LAPLACE * len(groups))
        woe = math.log(p_bad / p_good)
        woes.append(woe)
        iv += (p_bad - p_good) * woe
    return woes, iv


def fit_numeric(name: str, values: Sequence[float], labels: Sequence[int],
                max_bins: int = MAX_BINS,
                cuts_override: Optional[Sequence[float]] = None) -> FeatureBinning:
    """Kvantil (equal-frequency) binning + qo'shni binlarni birlashtirish.

    Nega kvantil? Daromad/DTI taqsimoti kuchli qiyshaygan (skewed) — teng
    kenglikdagi binlar bo'sh bucket'lar beradi. Kvantil har bir bucket'ga
    yetarli kuzatuv kafolatlaydi, ya'ni WOE statistik jihatdan barqaror.

    `cuts_override` — domen bilimi bilan qo'lda berilgan chegaralar. Diskret
    belgilar (masalan kechikish kunlari: 0 / 15 / 45 / 95) uchun kvantil
    yaroqsiz: kuzatuvlarning 79% i nolda turadi va kvantil ularni bitta
    bucket'ga tiqib, ma'noli 90+ kun segmentini yo'qotadi.

    Big-O: O(n log n) (saralash) + O(n) (taqsimlash).
    Chekka holat: bitta noyob qiymat -> yagona bin, WOE = 0 (belgi ishlamaydi).
    """
    pairs = sorted(zip(values, labels), key=lambda p: p[0])
    n = len(pairs)
    if n == 0:
        return FeatureBinning(name, [Bin(None, None, woe=0.0, label="hammasi")], 0.0, "numeric")

    uniq = sorted({v for v, _ in pairs})
    if len(uniq) <= 1:
        return FeatureBinning(name, [Bin(None, None, woe=0.0, n=n,
                                         bad=sum(labels), label="konstanta")],
                              0.0, "numeric")

    if cuts_override:
        cuts = [c for c in sorted(set(cuts_override)) if uniq[0] < c <= uniq[-1]]
        return _finalize_numeric(name, pairs, cuts, labels, merge_small=False)

    # 1) Kvantil chegaralari (takrorlanuvchi qiymatlar siqib chiqariladi).
    k = min(max_bins, max(2, len(uniq)))
    cuts: List[float] = []
    for i in range(1, k):
        idx = int(round(i * n / k))
        idx = min(max(idx, 0), n - 1)
        c = pairs[idx][0]
        if not cuts or c > cuts[-1]:
            cuts.append(c)
    cuts = [c for c in cuts if uniq[0] < c <= uniq[-1]]
    return _finalize_numeric(name, pairs, cuts, labels, merge_small=True)


def _finalize_numeric(name, pairs, cuts, labels, merge_small: bool) -> FeatureBinning:
    """Chegaralar berilgach: taqsimlash -> kichik binlarni birlashtirish -> WOE."""
    n = len(pairs)
    cuts = list(cuts)

    # 2) Chegaralar bo'yicha taqsimlash.
    def assign(v: float) -> int:
        for i, c in enumerate(cuts):
            if v < c:
                return i
        return len(cuts)

    nb = len(cuts) + 1
    counts = [[0, 0] for _ in range(nb)]
    for v, y in pairs:
        b = assign(v)
        counts[b][0] += 1
        counts[b][1] += y

    # 3) Juda kichik binlarni qo'shnisiga qo'shib yuborish.
    min_n = max(20, int(n * MIN_BIN_FRACTION)) if merge_small else 15
    i = 0
    while len(counts) > 2 and i < len(counts):
        if counts[i][0] < min_n:
            j = i - 1 if i > 0 else i + 1
            counts[j][0] += counts[i][0]
            counts[j][1] += counts[i][1]
            del counts[i]
            del cuts[i - 1 if i > 0 else 0]
            i = 0
            continue
        i += 1

    total_bad = sum(labels)
    total_good = len(labels) - total_bad
    woes, iv = _woe_iv([(c[0], c[1]) for c in counts], total_bad, total_good)

    bins: List[Bin] = []
    edges = [None] + list(cuts) + [None]
    for i, (cnt, woe) in enumerate(zip(counts, woes)):
        lo, hi = edges[i], edges[i + 1]
        label = _range_label(lo, hi)
        bins.append(Bin(lo=lo, hi=hi, woe=woe, n=cnt[0], bad=cnt[1], label=label))
    return FeatureBinning(name, bins, iv, "numeric")


def _fmt(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.1f}mln"
    if abs(v) >= 1000:
        return f"{v/1000:.0f}k"
    if abs(v) >= 10:
        return f"{v:.0f}"
    return f"{v:.2f}"


def _range_label(lo, hi) -> str:
    if lo is None and hi is None:
        return "hammasi"
    if lo is None:
        return f"< {_fmt(hi)}"
    if hi is None:
        return f">= {_fmt(lo)}"
    return f"{_fmt(lo)} … {_fmt(hi)}"


def fit_categorical(name: str, values: Sequence[str], labels: Sequence[int],
                    max_bins: int = MAX_BINS) -> FeatureBinning:
    """Kategoriyalarni bad-rate bo'yicha tartiblab, kamdagilarni birlashtirish.

    Big-O: O(n + c log c), c = noyob kategoriyalar soni.
    Chekka holat: kam uchraydigan kategoriyalar `kam_uchraydi` guruhiga
    yig'iladi — aks holda 3 ta kuzatuvli bucket ekstremal WOE beradi.
    """
    stat: Dict[str, List[int]] = {}
    for v, y in zip(values, labels):
        s = stat.setdefault(v, [0, 0])
        s[0] += 1
        s[1] += y

    n = len(values)
    # Kategoriyalarda absolyut chegara — nisbiy emas (config dagi izohga qarang).
    # Juda kichik o'quv to'plamida (masalan 300 satr) 30 ham qattiqlik qiladi,
    # shuning uchun 2% dan oshmasin, lekin 10 dan past ham tushmasin.
    min_n = max(10, min(MIN_CATEGORY_N, int(0.02 * n)))
    rare = {c for c, s in stat.items() if s[0] < min_n}
    groups: List[Tuple[set, int, int]] = []
    for c, s in stat.items():
        if c not in rare:
            groups.append(({c}, s[0], s[1]))
    if rare:
        rn = sum(stat[c][0] for c in rare)
        rb = sum(stat[c][1] for c in rare)
        groups.append((set(rare), rn, rb))

    # Ko'p kategoriya bo'lsa — bad-rate bo'yicha tartiblab, qo'shnilarni qo'shamiz.
    groups.sort(key=lambda g: (g[2] / g[1]) if g[1] else 0.0)

    def _merge(i: int) -> None:
        a, b = groups[i], groups[i + 1]
        groups[i:i + 2] = [(a[0] | b[0], a[1] + b[1], a[2] + b[2])]

    while len(groups) > max_bins:
        best_i, best_d = 0, math.inf
        for i in range(len(groups) - 1):
            a, b = groups[i], groups[i + 1]
            d = abs((a[2] / a[1] if a[1] else 0) - (b[2] / b[1] if b[1] else 0))
            if d < best_d:
                best_i, best_d = i, d
        _merge(best_i)

    # `rare` guruhining o'zi ham min_n dan kichik chiqishi mumkin (masalan
    # jami 3 ta kuzatuv). Bunday bucket ekstremal WOE beradi va modelni
    # chalg'itadi — uni bad-rate bo'yicha eng yaqin qo'shnisiga qo'shamiz.
    i = 0
    while len(groups) > 1 and i < len(groups):
        if groups[i][1] < min_n:
            _merge(i - 1 if i > 0 else i)
            i = 0
            continue
        i += 1

    total_bad = sum(labels)
    total_good = len(labels) - total_bad
    woes, iv = _woe_iv([(g[1], g[2]) for g in groups], total_bad, total_good)

    bins = [
        Bin(categories=g[0], woe=w, n=g[1], bad=g[2],
            label=", ".join(sorted(g[0])[:3]) + ("…" if len(g[0]) > 3 else ""))
        for g, w in zip(groups, woes)
    ]
    return FeatureBinning(name, bins, iv, "categorical")


def iv_strength(iv: float) -> str:
    """Siegel/Thomas an'anaviy talqin shkalasi."""
    if iv < 0.02:
        return "foydasiz"
    if iv < 0.10:
        return "kuchsiz"
    if iv < 0.30:
        return "o'rtacha"
    if iv < 0.50:
        return "kuchli"
    return "juda kuchli"
