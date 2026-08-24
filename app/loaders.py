"""CSV yuklovchilar. Faqat stdlib — og'ir bog'liqliklar yo'q, deterministik."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional

from .config import DATA_DIR


def _num(value: Optional[str], default: float = 0.0) -> float:
    """Bo'sh / buzuq maydonni default ga aylantiradi (chekka holat: '', None, 'NA')."""
    if value is None:
        return default
    value = value.strip()
    if not value or value.upper() in {"NA", "NULL", "NONE", "-"}:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _read(path: Path) -> List[Dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class Dataset:
    """Xom CSV larni applicant_id bo'yicha indekslangan ko'rinishga keltiradi."""

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = Path(data_dir)
        self.applicants: Dict[str, dict] = {}
        self.flows: Dict[str, List[dict]] = {}
        self.loans: Dict[str, List[dict]] = {}
        self.applications: List[dict] = []
        self._load()

    def _load(self) -> None:
        for row in _read(self.data_dir / "applicants.csv"):
            self.applicants[row["applicant_id"]] = {
                "applicant_id": row["applicant_id"],
                "ism": row.get("ism", ""),
                "jins": row.get("jins", ""),
                "yosh": int(_num(row.get("yosh"), 0)),
                "viloyat": row.get("viloyat", ""),
                "bandlik": row.get("bandlik", "").strip() or "nomalum",
                "ish_staji_oy": _num(row.get("ish_staji_oy")),
                "deklaratsiya_daromad": _num(row.get("deklaratsiya_daromad")),
                "oila_azolari": int(_num(row.get("oila_azolari"), 1)),
                "talim": row.get("talim", "").strip() or "nomalum",
                "mijoz_boldi_oy": _num(row.get("mijoz_boldi_oy")),
            }

        for row in _read(self.data_dir / "monthly_flows.csv"):
            self.flows.setdefault(row["applicant_id"], []).append({
                "oy": row["oy"],
                "kirim": _num(row.get("kirim")),
                "chiqim": _num(row.get("chiqim")),
                "naqd_yechish": _num(row.get("naqd_yechish")),
                "oy_oxiri_qoldiq": _num(row.get("oy_oxiri_qoldiq")),
            })
        for rows in self.flows.values():
            rows.sort(key=lambda r: r["oy"])   # vaqt bo'yicha tartib kafolatlanadi

        for row in _read(self.data_dir / "existing_loans.csv"):
            self.loans.setdefault(row["applicant_id"], []).append({
                "loan_id": row["loan_id"],
                "bank": row.get("bank", ""),
                "summa": _num(row.get("summa")),
                "muddat_oy": _num(row.get("muddat_oy")),
                "oylik_tolov": _num(row.get("oylik_tolov")),
                "qoldiq": _num(row.get("qoldiq")),
                "max_kechikish_kun": _num(row.get("max_kechikish_kun")),
                "status": row.get("status", "").strip(),
            })

        for row in _read(self.data_dir / "applications.csv"):
            self.applications.append({
                "application_id": row["application_id"],
                "applicant_id": row["applicant_id"],
                "ariza_sana": row.get("ariza_sana", ""),
                "sorlgan_summa": _num(row.get("sorlgan_summa")),
                "maqsad": row.get("maqsad", "").strip() or "nomalum",
                "muddat_oy": _num(row.get("muddat_oy"), 12) or 12,
                "mavjud_oylik_yuk": _num(row.get("mavjud_oylik_yuk")),
                "natija": (row.get("natija") or "").strip(),
            })

    # -- yordamchilar ---------------------------------------------------------
    def train(self) -> List[dict]:
        return [a for a in self.applications if a["natija"]]

    def test(self) -> List[dict]:
        return [a for a in self.applications if not a["natija"]]

    def profile(self, applicant_id: str) -> dict:
        """Bitta arizachining to'liq 360° kesimi."""
        return {
            "applicant": self.applicants.get(applicant_id, {}),
            "flows": self.flows.get(applicant_id, []),
            "loans": self.loans.get(applicant_id, []),
        }


def label_of(application: dict) -> Optional[int]:
    """'defolt' -> 1 (bad), 'toladi' -> 0 (good), bo'sh -> None (test)."""
    natija = application.get("natija", "")
    if not natija:
        return None
    return 1 if natija == "defolt" else 0
