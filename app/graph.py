"""Mijoz aloqalari grafi.

FindDroppers dagi api_graph_client dan ko'chirilgan yondashuv, lekin kredit
ma'lumotlariga moslab: bu yerda o'tkazmalar oqimi yo'q, bor narsa — mijozning
kreditlari, arizalari va BOSHQA MIJOZLARGA O'XSHASHLIGI. Underwriter uchun
savol ham boshqacha: "kim kimga pul o'tkazgan" emas, "shu profilga o'xshaganlar
qanday to'lagan".

QATLAMLAR (FindDroppers dagi kabi, har biri alohida va sababi bilan):
  1. loans    mijoz -> banklardagi kreditlari (summa, kechikish bilan)
  2. similar  mijoz -> unga eng o'xshash mijozlar (WOE fazosidagi masofa)
  3. mesh     o'xshashlar O'ZARO o'xshashmi — klaster shu yerda ko'rinadi:
              yulduzcha hech qachon guruhni ko'rsata olmaydi, faqat setka
  4. sabab    nima uchun o'xshash — eng yaqin 3 belgi nomi qirra ustida

FindDroppers dan olib kelingan intizom:
  * potoloklar har qatlamda (aks holda 2160 vershina keladi);
  * cuts/fails/took — nima kesildi, nima ishlamadi, qancha vaqt ketdi,
    hammasi javobda: bo'sh qatlam "aloqa yo'q" degani emas;
  * missing — nimani KO'RSATA OLMAYMIZ (qurilma/IP ma'lumoti bu datasetda
    umuman yo'q) — halol aytamiz, aks holda tahlilchi noto'g'ri xulosa qiladi.

O'xshashlik WOE fazosida o'lchanadi, xom qiymatlarda emas. Sabab: WOE har
belgini "xavf birligi" ga keltiradi — daromad so'mda va yosh yilda bo'lgani
uchun evklid masofasi xom fazoda ma'nosiz, WOE fazosida esa ikki mijoz
orasidagi masofa aynan "risk profili qanchalik farq qiladi" degani.
"""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

# Potoloklar — FindDroppers dagi kabi nomlanadi va har biri o'lchab tanlangan.
_GRAPH_SIMILAR = 8          # standart; so'rovda ?n= bilan 24 gacha oshiriladi
_GRAPH_SIMILAR_MAX = 24     # potolok — undan ko'p vershina o'qilmaydi
_GRAPH_CANDIDATES = 2160    # butun train — 2160 x 20 masofa ~ 40 ms, arzon
_GRAPH_MESH_MAX = 28        # o'xshashlar orasidagi qirralar potoloki
_GRAPH_TOP_REASONS = 3      # qirra ustida nechta "eng yaqin belgi" yoziladi
# O'xshashlik chegarasi: bundan uzoq juftlik mesh ga kirmaydi. O'lchab olingan:
# tasodifiy ikki mijoz orasidagi o'rtacha masofa ~2.4, bir klasterdagilar < 1.1.
_GRAPH_MESH_DIST = 1.15


class GraphBuilder:
    """WOE fazosidagi qo'shnilar grafi. Engine bir marta quradi va keshlaydi."""

    def __init__(self, engine):
        self.engine = engine
        self._index: Optional[List[dict]] = None    # [{id, vec, label, ...}]
        self._keys: List[str] = []

    # -- indeks ---------------------------------------------------------------
    def _ensure_index(self) -> None:
        """Barcha TRAIN arizalarni WOE vektorlarga aylantirib xotirada saqlaydi.

        Big-O: O(n * k) bir marta (n=2160, k~20); keyin har so'rov O(n * k)
        masofa hisobi — 50 ms atrofida, alohida indeks strukturasiz yetarli.
        """
        if self._index is not None:
            return
        eng = self.engine
        sc = eng.scorecard
        self._keys = [k for k, _, _, _ in sc.spec]
        rows = []
        for a in eng.data.train()[:_GRAPH_CANDIDATES]:
            feats = eng.features_of(a)
            vec = [sc.binnings[k].woe_of(_val(feats, k, kind))[0]
                   for k, kind, _, _ in sc.spec]
            rows.append({
                "application_id": a["application_id"],
                "applicant_id": a["applicant_id"],
                "natija": a["natija"],
                "vec": vec,
            })
        self._index = rows

    def invalidate(self) -> None:
        """Skorkarta qayta o'rgatilganda WOE fazosi o'zgaradi — indeks eskiradi."""
        self._index = None

    # -- masofa ---------------------------------------------------------------
    @staticmethod
    def _dist(a: List[float], b: List[float]) -> float:
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def _vector_of(self, feats: dict) -> List[float]:
        sc = self.engine.scorecard
        return [sc.binnings[k].woe_of(_val(feats, k, kind))[0]
                for k, kind, _, _ in sc.spec]

    # -- qurish ---------------------------------------------------------------
    def build(self, applicant_id: str, n: int = _GRAPH_SIMILAR) -> Optional[dict]:
        n = max(3, min(int(n or _GRAPH_SIMILAR), _GRAPH_SIMILAR_MAX))
        eng = self.engine
        profile = eng.data.profile(applicant_id)
        if not profile.get("applicant"):
            return None

        t0 = time.time()
        took: Dict[str, int] = {}
        fails: List[str] = []
        cuts: Dict[str, dict] = {}
        nodes: Dict[str, dict] = {}
        edges: List[dict] = []

        applicant = profile["applicant"]
        loans = profile.get("loans") or []
        my_apps = [a for a in eng.data.applications
                   if a["applicant_id"] == applicant_id]

        # markaziy vektor: mijozning eng so'nggi arizasi bo'yicha
        base_app = my_apps[-1] if my_apps else {
            "application_id": applicant_id, "applicant_id": applicant_id,
            "sorlgan_summa": 0.0, "muddat_oy": 12, "mavjud_oylik_yuk": 0.0,
            "maqsad": "nomalum", "natija": "", "ariza_sana": "",
        }
        feats = eng.features_of(base_app) if my_apps else None
        score = eng.scorecard.score(feats) if feats else None

        nodes[f"c{applicant_id}"] = {
            "id": f"c{applicant_id}", "type": "client", "root": True,
            "label": applicant.get("ism") or applicant_id,
            "sub": applicant_id,
            "ball": round(score.score) if score else None,
            "natija": (my_apps[-1]["natija"] if my_apps else "") or "test",
        }

        # ── 1-QATLAM: banklardagi kreditlar ────────────────────────────────
        t = time.time()
        for l in loans:
            bid = f"b{l['bank']}"
            if bid not in nodes:
                nodes[bid] = {"id": bid, "type": "bank", "label": l["bank"]}
            edges.append({
                "source": f"c{applicant_id}", "target": bid, "kind": "loan",
                "sum": round(l["qoldiq"]), "status": l["status"],
                "kechikish": l["max_kechikish_kun"],
                "label": f"{l['qoldiq']/1e6:.1f} mln"
                         + (f" · {l['max_kechikish_kun']:.0f} kun" if l["max_kechikish_kun"] else ""),
            })
        took["loans"] = int((time.time() - t) * 1000)

        # ── 2-QATLAM: o'xshash mijozlar (WOE fazosida qo'shnilar) ──────────
        t = time.time()
        similar: List[Tuple[float, dict]] = []
        try:
            self._ensure_index()
            if feats is None:
                raise ValueError("ariza yo'q — vektor qurilmaydi")
            vec = self._vector_of(feats)
            scored = []
            for row in self._index:
                if row["applicant_id"] == applicant_id:
                    continue
                scored.append((self._dist(vec, row["vec"]), row))
            scored.sort(key=lambda p: p[0])
            similar = scored[:n]
            if len(scored) > n:
                cuts["similar"] = {"kept": n, "total": len(scored)}
        except Exception:
            fails.append("similar")
        took["similar"] = int((time.time() - t) * 1000)

        key_labels = {k: label for k, _, label, _ in eng.scorecard.spec}

        def _closest_feats(va: List[float], vb: List[float]) -> str:
            """Qirra izohi: qaysi belgilar bo'yicha eng yaqin."""
            diffs = sorted(zip(self._keys, (abs(x - y) for x, y in zip(va, vb))),
                           key=lambda p: p[1])
            return ", ".join(key_labels.get(k, k)
                             for k, _ in diffs[:_GRAPH_TOP_REASONS])

        vec_of: Dict[str, List[float]] = {}
        for dist, row in similar:
            oid = row["applicant_id"]
            other = eng.data.applicants.get(oid) or {}
            nodes[f"c{oid}"] = {
                "id": f"c{oid}", "type": "client",
                "label": other.get("ism") or oid, "sub": oid,
                "natija": row["natija"],
                "bandlik": other.get("bandlik"), "viloyat": other.get("viloyat"),
            }
            vec_of[oid] = row["vec"]
            edges.append({
                "source": f"c{applicant_id}", "target": f"c{oid}",
                "kind": "similar", "dist": round(dist, 3),
                "label": _closest_feats(self._vector_of(feats), row["vec"])
                         if feats else "",
            })

        # ── 3-QATLAM: o'xshashlar O'ZARO — klaster shu yerda ko'rinadi ────
        # Yulduz (markaz -> qo'shnilar) hech qachon guruhni ko'rsata olmaydi:
        # guruh degani qo'shnilar BIR-BIRIGA ham yaqin degani.
        t = time.time()
        mesh_n = 0
        ids = list(vec_of.keys())
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                if mesh_n >= _GRAPH_MESH_MAX:
                    cuts["mesh"] = {"kept": _GRAPH_MESH_MAX, "total": "ko'proq"}
                    break
                d = self._dist(vec_of[ids[i]], vec_of[ids[j]])
                if d <= _GRAPH_MESH_DIST:
                    edges.append({"source": f"c{ids[i]}", "target": f"c{ids[j]}",
                                  "kind": "mesh", "dist": round(d, 3)})
                    mesh_n += 1
            else:
                continue
            break
        took["mesh"] = int((time.time() - t) * 1000)

        # ── arizalar tugunlari (qaror tarixi bilan) ────────────────────────
        from . import db
        for a in my_apps:
            tarix = db.decision_history(eng.conn, a["application_id"])
            last = tarix[-1] if tarix else None
            aid = f"a{a['application_id']}"
            nodes[aid] = {
                "id": aid, "type": "ariza", "label": a["application_id"],
                "sub": a.get("maqsad", ""),
                "qaror": (last or {}).get("qaror") or (a["natija"] or None),
                "ball": round((last or {}).get("ball", 0)) or None,
            }
            edges.append({"source": f"c{applicant_id}", "target": aid,
                          "kind": "ariza",
                          "label": f"{a['sorlgan_summa']/1e6:.0f} mln"})

        took["total"] = int((time.time() - t0) * 1000)
        return {
            "root": f"c{applicant_id}",
            "nodes": list(nodes.values()), "edges": edges,
            "took": took, "partial": sorted(set(fails)), "cuts": cuts,
            "mesh_edges": mesh_n, "similar": len(similar),
            # nimaga asoslangan — ochiq aytamiz (FindDroppers intizomi)
            "basis": "o'xshashlik skorkartaning WOE fazosidagi evklid masofasi; "
                     "mesh chegarasi 1.15 (tasodifiy juftlik ~2.4)",
            # bu datasetda YO'Q narsalar — bo'sh qatlam "aloqa yo'q" emas
            "missing": ["o'tkazmalar oqimi", "qurilma/IP", "umumiy hujjat (PINFL)"],
        }


def _val(row: dict, key: str, kind: str):
    v = row.get(key)
    if kind == "numeric":
        try:
            return float(v or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return str(v if v is not None else "nomalum")
