"""Scenario Evidence Check: one planned condition in, TESTED / PARTIAL / GAP out.

Deterministic. No model, no interpolation, no risk or safety score. The check compares the
requested condition with the canonical NASA core tables (PSI-25 BASS-II and PSI-69 FLEX) and
says which conditions match, which differ, and which
are simply not recorded in those tables. "GAP" means absent from these indexed tables, never
that NASA never tested it.

Status rules (tolerances are returned with every result):
- TESTED : a recorded test matches the fuel/material AND every condition the user gave.
- PARTIAL: tests match the fuel/material and the oxygen level, but at least one other condition
           the user gave (pressure, gravity) differs or is not recorded in the table.
- GAP    : no recorded test matches the fuel/material at the requested oxygen level.

Text comes in English ("en") or Turkish ("tr"); the status codes stay TESTED / PARTIAL / GAP.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Any

from .data.contracts import ExperimentRecord, MeasurementStatus

O2_TOL = 0.05         # percentage points; matches recorded rounded table values only
P_TOL = 0.01          # atm; accommodates recorded precision without broad interpolation
G_MICRO = 0.01        # g; all indexed tests ran in microgravity (ISS / Cygnus)

# user text -> substring of the material / fuel name in the data (Turkish spellings are folded to ASCII first)
ALIASES = {"pmma": "pmma", "plexiglas": "pmma", "acrylic": "pmma", "akrilik": "pmma", "nomex": "nomex",
           "sibal": "sibal", "wax": "wax", "candle": "wax", "mum": "wax",
           "methanol": "methanol", "metanol": "methanol", "heptane": "heptane", "heptan": "heptane"}
FUEL_LABEL = {"pmma": "PMMA", "nomex": "Nomex", "sibal": "SIBAL", "wax": "Wax candle",
              "methanol": "Methanol", "heptane": "Heptane"}
SRC_LABEL = {"en": {"material": "Material lab table", "flex": "FLEX table (PSI-69)"},
             "tr": {"material": "Malzeme laboratuvarı tablosu", "flex": "FLEX tablosu (PSI-69)"}}
SCOPE = {"en": "PSI-25 BASS-II (129 runs) + PSI-69 FLEX (274 runs), kept separate",
         "tr": "PSI-25 BASS-II (129 koşu) + PSI-69 FLEX (274 koşu), ayrı tutulur"}

STATUS_TEXT = {
    "en": {"TESTED": "TESTED: a recorded NASA test matches every condition you gave.",
           "PARTIAL": "PARTIAL: tests match the fuel and oxygen, but not every other condition.",
           "GAP": "GAP: no recorded test in the indexed tables matches this fuel at this oxygen level."},
    "tr": {"TESTED": "TESTED: kayıtlı bir NASA testi verdiğiniz tüm koşullarla eşleşiyor.",
           "PARTIAL": "PARTIAL: testler yakıt ve oksijenle eşleşiyor, ama verdiğiniz diğer koşulların hepsiyle değil.",
           "GAP": "GAP: indekslenen tablolarda bu yakıt için bu oksijen düzeyinde kayıtlı test yok."}}
LIMITS = {
    "en": ["GAP means absent from these indexed tables, not that NASA never tested it.",
           "This is a coverage check, not a safety or fire-risk rating."],
    "tr": ["GAP, bu indekslenmiş tablolarda yok demektir; NASA'nın hiç test etmediği anlamına gelmez.",
           "Bu bir kapsam kontrolüdür; güvenlik veya yangın riski değerlendirmesi değildir."]}
MSG = {
    "en": {
        "unknown": "'{fuel}' is not a fuel or material in the indexed tables "
                   "(PMMA, Nomex, SIBAL, wax, methanol, heptane).",
        "gravity": "Gravity {g:g} g: every indexed test ran in microgravity; no partial-gravity (Moon/Mars) "
                   "or 1 g tests are recorded.",
        "o2_range": "Oxygen {o2:g}%: recorded {fuel} tests cover {lo:g}% to {hi:g}% O₂ only (±{tol:g} point match).",
        "o2_none": "Oxygen {o2:g}%: recorded {fuel} tests have no oxygen value.",
        "p_unrec": "Pressure {p:g} atm: the matching tests do not record pressure in the table.",
        "p_span": "Pressure {p:g} atm: matching FLEX tests span {lo:g} to {hi:g} atm.",
        "p_unrec_short": "pressure not recorded"},
    "tr": {
        "unknown": "'{fuel}' indekslenen tablolarda yakıt veya malzeme olarak yok "
                   "(PMMA, Nomex, SIBAL, mum, metanol, heptan).",
        "gravity": "Yerçekimi {g:g} g: indekslenen tüm testler mikro yerçekiminde yapıldı; kısmi yerçekimi (Ay/Mars) "
                   "veya 1 g testi kayıtlı değil.",
        "o2_range": "Oksijen %{o2:g}: kayıtlı {fuel} testleri yalnızca %{lo:g} – %{hi:g} O₂ aralığını kapsıyor "
                    "(±{tol:g} puan eşleşme).",
        "o2_none": "Oksijen %{o2:g}: kayıtlı {fuel} testlerinde oksijen değeri yok.",
        "p_unrec": "Basınç {p:g} atm: eşleşen testlerin tablosunda basınç kaydedilmemiş.",
        "p_span": "Basınç {p:g} atm: eşleşen FLEX testleri {lo:g} – {hi:g} atm aralığında.",
        "p_unrec_short": "basınç kayıtlı değil"}}

HABITATS = {  # same presets as the Fire page (frontend/js/lib.js); hypothetical planning conditions, not NASA tests
    "moon": {"o2": 34.0, "p": 0.558, "g": 0.166, "label": {"en": "Moon habitat (hypothetical)", "tr": "Ay habitatı (varsayımsal)"}},
    "mars": {"o2": 34.0, "p": 0.558, "g": 0.378, "label": {"en": "Mars habitat (hypothetical)", "tr": "Mars habitatı (varsayımsal)"}},
    "iss": {"o2": 21.0, "p": 1.0, "g": 0.0, "label": {"en": "ISS cabin", "tr": "ISS kabini"}},
}
REPORT_FUELS = ("PMMA", "Nomex", "SIBAL", "Methanol")


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text.lower().replace("ı", "i"))
    return "".join(c for c in t if not unicodedata.combining(c)).replace("₂", "2")


def _measured(rec: ExperimentRecord, field_name: str, *, extra_unit: str | None = None) -> float | None:
    measurement = rec.measurements.get(field_name)
    if measurement is None or measurement.status != MeasurementStatus.MEASURED:
        return None
    value = (measurement.extra_conversions.get(extra_unit, {}).get("value")
             if extra_unit else measurement.normalized_value)
    return None if value is None else float(value)


def _solid_key(label: str) -> str | None:
    low = label.casefold()
    if "pmma" in low or "rod" in low:
        return "pmma"
    if "nomex" in low:
        return "nomex"
    if "sibal" in low:
        return "sibal"
    if "wax" in low or "candle" in low:
        return "wax"
    return None


class ScenarioChecker:
    def __init__(self, records: Sequence[ExperimentRecord]) -> None:
        self.records = tuple(records)
        self.material = tuple(r for r in self.records if r.investigation_id == "PSI-25")
        self.flex = tuple(r for r in self.records if r.investigation_id == "PSI-69")

    # -- helpers -------------------------------------------------------------------------
    @staticmethod
    def _key(text: str) -> str | None:
        t = _fold(text)
        for k, v in ALIASES.items():
            if re.search(r"(?<![a-z])" + k, t):
                return v
        return None

    def _pool(self, key: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for r in self.material:
            raw_name = str(r.normalized_fields.get("fuel_norm") or "")
            if _solid_key(raw_name) == key:
                out.append({"pool": "material", "id": r.record_pk, "record_pk": r.record_pk,
                            "investigation_id": r.investigation_id, "name": raw_name,
                            "o2": _measured(r, "initial_o2_vol_pct"), "p": None,
                            "src": "PSI-25 BASS-II", "source_relpath": r.source.source_relpath,
                            "source_sha256": r.source.source_sha256,
                            "csv_record_index": r.source.csv_record_index,
                            "physical_line_start": r.source.physical_line_start,
                            "physical_line_end": r.source.physical_line_end})
        for r in self.flex:
            fuel_name = str(r.normalized_fields.get("fuel_norm") or "")
            if key == fuel_name.casefold():
                pressure_atm = _measured(r, "ambient_pressure_kpa", extra_unit="atm")
                if pressure_atm is not None and pressure_atm <= 0.0:
                    pressure_atm = None
                out.append({"pool": "flex", "id": r.record_pk, "record_pk": r.record_pk,
                            "investigation_id": r.investigation_id, "name": fuel_name,
                            "o2": _measured(r, "initial_o2_flex_mol_pct"),
                            "p": pressure_atm,
                            "src": "PSI-69 FLEX", "source_relpath": r.source.source_relpath,
                            "source_sha256": r.source.source_sha256,
                            "csv_record_index": r.source.csv_record_index,
                            "physical_line_start": r.source.physical_line_start,
                            "physical_line_end": r.source.physical_line_end})
        return out

    # -- main ----------------------------------------------------------------------------
    def check(self, fuel: str, o2: float | None = None, pressure_atm: float | None = None,
              gravity_g: float | None = None, purpose: str = "", lang: str = "en") -> dict[str, Any]:
        lang = "tr" if lang == "tr" else "en"
        m = MSG[lang]
        key = self._key(fuel or "")
        req = {"fuel": fuel, "o2_percent": o2, "pressure_atm": pressure_atm, "gravity_g": gravity_g,
               "purpose": purpose or None}
        tol = {"o2_percentage_points": O2_TOL, "pressure_atm": P_TOL, "gravity_microgravity_below_g": G_MICRO}
        base = {"requested": req, "tolerances": tol, "scope": SCOPE[lang], "lang": lang, "limitations": list(LIMITS[lang])}
        if key is None:
            return {**base, "status": "GAP", "status_text": STATUS_TEXT[lang]["GAP"], "matching_tests": 0,
                    "matching_pool_size": 0, "fuel_o2_range": None,
                    "differences": [m["unknown"].format(fuel=fuel)], "nearest": [], "sources": []}
        label = FUEL_LABEL[key]
        pool = self._pool(key)
        diffs: list[str] = []
        grav_ok = not (gravity_g is not None and gravity_g > G_MICRO)   # every indexed test is microgravity
        with_o2 = [r for r in pool if r["o2"] is not None]
        o2_range = [min(r["o2"] for r in with_o2), max(r["o2"] for r in with_o2)] if with_o2 else None
        o2_ok = [r for r in with_o2 if o2 is None or abs(r["o2"] - o2) <= O2_TOL]
        if o2 is not None and not o2_ok:
            diffs.append(m["o2_range"].format(o2=o2, fuel=label, lo=o2_range[0], hi=o2_range[1], tol=O2_TOL)
                         if o2_range else m["o2_none"].format(o2=o2, fuel=label))
        rows = o2_ok
        if pressure_atm is not None:
            known = [r for r in o2_ok if r["p"] is not None]
            rows = [r for r in known if abs(r["p"] - pressure_atm) <= P_TOL]
            if o2_ok and not known:
                diffs.append(m["p_unrec"].format(p=pressure_atm))
            elif o2_ok and not rows:
                ps = [r["p"] for r in known]
                diffs.append(m["p_span"].format(p=pressure_atm, lo=min(ps), hi=max(ps)))
        if not grav_ok:                                          # reasons ordered: oxygen, pressure, gravity
            diffs.append(m["gravity"].format(g=gravity_g))
        full = rows if grav_ok else []
        status = "GAP" if not o2_ok else ("TESTED" if full else "PARTIAL")

        def dist(r: dict[str, Any]) -> tuple[float, float]:     # nearest by oxygen, then pressure
            return (abs(r["o2"] - o2) if o2 is not None and r["o2"] is not None else 99.0,
                    abs(r["p"] - pressure_atm) if pressure_atm is not None and r["p"] is not None else 0.0)
        nearest = sorted(pool, key=dist)[:5]
        near = [{"id": r["id"], "record_pk": r["record_pk"], "investigation_id": r["investigation_id"],
                 "name": r["name"], "o2_percent": r["o2"], "pressure_atm": r["p"],
                 "source": r["src"],
                 "link": f"data.html?exp={r['investigation_id']}&pick={r['record_pk']}#s-explorer",
                 "source_relpath": r["source_relpath"], "source_sha256": r["source_sha256"],
                 "csv_record_index": r["csv_record_index"],
                 "physical_line_start": r["physical_line_start"],
                 "physical_line_end": r["physical_line_end"]} for r in nearest]
        pools = sorted({r["pool"] for r in nearest})
        return {**base, "status": status, "status_text": STATUS_TEXT[lang][status], "matching_tests": len(full),
                "matching_pool_size": len(pool), "fuel_o2_range": o2_range, "differences": diffs, "nearest": near,
                "sources": [{"label": SRC_LABEL[lang][p],
                             "href": "material-lab.html" if p == "material" else "fire.html"} for p in pools]}

    # -- habitat report ------------------------------------------------------------------
    def habitat_report(self, habitat: str = "moon", fuels: list[str] | None = None, o2: float | None = None,
                       pressure_atm: float | None = None, gravity_g: float | None = None,
                       lang: str = "en") -> dict[str, Any]:
        """Same check for several materials under one habitat condition, summarised in one table."""
        lang = "tr" if lang == "tr" else "en"
        h = HABITATS.get(habitat)
        if h is None and (o2 is None or pressure_atm is None or gravity_g is None):
            raise ValueError("habitat")
        cond = {"o2_percent": o2 if o2 is not None else h["o2"], "pressure_atm": pressure_atm if pressure_atm is not None else h["p"],
                "gravity_g": gravity_g if gravity_g is not None else h["g"]}
        rows, counts = [], {"TESTED": 0, "PARTIAL": 0, "GAP": 0}
        for f in (fuels or list(REPORT_FUELS)):
            r = self.check(f, cond["o2_percent"], cond["pressure_atm"], cond["gravity_g"], lang=lang)
            counts[r["status"]] += 1
            rows.append({"fuel": f, "status": r["status"], "differences": r["differences"],
                         "fuel_o2_range": r["fuel_o2_range"], "matching_pool_size": r["matching_pool_size"],
                         "nearest": r["nearest"][:1]})
        n = len(rows)
        label = (h or {"label": {"en": "Custom habitat", "tr": "Özel habitat"}})["label"][lang]
        c = cond
        if lang == "tr":
            summary = (f"{label}: %{c['o2_percent']:g} O₂, {c['pressure_atm']:g} atm, {c['gravity_g']:g} g koşulunda "
                       f"{n} malzemeden {counts['TESTED']} tanesi TESTED, {counts['PARTIAL']} tanesi PARTIAL, {counts['GAP']} tanesi GAP.")
        else:
            summary = (f"{label}: at {c['o2_percent']:g}% O₂, {c['pressure_atm']:g} atm, {c['gravity_g']:g} g, "
                       f"{counts['TESTED']} of {n} materials are TESTED, {counts['PARTIAL']} PARTIAL, {counts['GAP']} GAP.")
        return {"habitat": habitat, "label": label, "condition": cond, "rows": rows, "counts": counts, "summary": summary,
                "lang": lang, "tolerances": {"o2_percentage_points": O2_TOL, "pressure_atm": P_TOL},
                "hypothetical": h is not None and habitat in ("moon", "mars"),
                "limitations": list(LIMITS[lang]) + ([
                    "Habitat conditions are hypothetical planning presets, not NASA test conditions or a flight design."
                    if lang == "en" else
                    "Habitat koşulları varsayımsal planlama ön ayarlarıdır; NASA test koşulu veya uçuş tasarımı değildir."]
                    if habitat in ("moon", "mars") else [])}


# ---------------------------------------------------------------------------------------
# Coverage map (grid of checks)
# ---------------------------------------------------------------------------------------
GRID_O2 = [10 + 2.5 * i for i in range(15)]            # 10 .. 45 % O2
GRID_P = [round(0.2 + 0.1 * i, 1) for i in range(19)]  # 0.2 .. 2.0 atm


def coverage_grid(checker: ScenarioChecker, fuel: str, gravity_g: float | None, lang: str = "en") -> dict[str, Any]:
    """Status for every (oxygen, pressure) cell at one gravity. Same rules as ``check``; nothing is interpolated."""
    lang = "tr" if lang == "tr" else "en"
    cells = [[checker.check(fuel, o2, p, gravity_g)["status"] for o2 in GRID_O2] for p in GRID_P]
    flat = [s for r in cells for s in r]
    note = {"en": ["GAP means absent from the indexed tables, not that NASA never tested it.",
                   "Fuels from the Material lab table do not record pressure, so a pressure-specific cell can be PARTIAL at best.",
                   "Coverage map, not a safety rating."],
            "tr": ["GAP, indekslenen tablolarda yok demektir; NASA'nın hiç test etmediği anlamına gelmez.",
                   "Malzeme laboratuvarı tablosundaki yakıtlarda basınç kaydı yok; bu yüzden basınca göre bir hücre en iyi PARTIAL olabilir.",
                   "Kapsam haritasıdır, güvenlik değerlendirmesi değildir."]}[lang]
    warn = {"en": {"p": "{fuel} tests in these tables record no pressure, so every row is the same: the cells show the oxygen match only, "
                        "and no cell can be TESTED at a specific pressure.",
                   "g": "No recorded test exists at {g:g} g (all indexed tests ran in microgravity). Cells show only whether fuel and "
                        "oxygen match; none can be TESTED."},
            "tr": {"p": "Bu tablolardaki {fuel} testlerinde basınç kaydı yok; bu yüzden tüm satırlar aynıdır: hücreler yalnızca oksijen "
                        "eşleşmesini gösterir ve belirli bir basınçta hiçbir hücre TESTED olamaz.",
                   "g": "{g:g} g için kayıtlı test yok (indekslenen tüm testler mikro yerçekiminde yapıldı). Hücreler yalnızca yakıt ve "
                        "oksijen eşleşmesini gösterir; hiçbiri TESTED olamaz."}}[lang]
    warnings = []
    key = ScenarioChecker._key(fuel or "")
    if key is not None and not any(r["p"] is not None for r in checker._pool(key)):
        warnings.append(warn["p"].format(fuel=FUEL_LABEL[key]))
    if gravity_g is not None and gravity_g > G_MICRO:
        warnings.append(warn["g"].format(g=gravity_g))
    return {"fuel": fuel, "gravity_g": gravity_g, "o2_values": GRID_O2, "pressure_values": GRID_P, "cells": cells,
            "warnings": warnings, "counts": {s: flat.count(s) for s in ("TESTED", "PARTIAL", "GAP")},
            "tolerances": {"o2_percentage_points": O2_TOL, "pressure_atm": P_TOL}, "limitations": note, "lang": lang}


# ---------------------------------------------------------------------------------------
# Free-text questions (English and Turkish)
# ---------------------------------------------------------------------------------------
_STAT = re.compile(r"\b(highest|lowest|maximum|minimum|how many|average|median|largest|smallest|"
                   r"en yuksek|en dusuk|en fazla|en az|kac|ortalama|maksimum|minimum|medyan)\b")
_CUE = re.compile(r"\b(tested|covered|coverage|evidence|gap|scenario|habitat|data exist|has nasa|did nasa|"
                  r"was it tested|is there|any test|test edil\w*|test\w* var|kapsa\w*|kanit\w*|veri\w* var|bosluk|"
                  r"senaryo|denen\w*|var mi)\b")
_TR_HINT = re.compile(r"\b(oksijen|yercekim\w*|mikro\w*|malzeme\w*|test edil\w*|var mi|mi\?|kapsa\w*|nasa'?nin|icin|"
                      r"habitat[ia]|ay'?(?:da|in)|bosluk|senaryo|denen\w*|yuzde|atm'?de)\b|%\s*\d")
_O2 = re.compile(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:o2|oxygen|oksijen)|(?:o2|oxygen|oksijen)\s*(?:of|at|=|:|orani|oranı)?\s*%?\s*(\d+(?:[.,]\d+)?)\s*%?|"
                 r"%\s*(\d+(?:[.,]\d+)?)\s*(?:o2|oxygen|oksijen)")


def _lang_of(q: str, folded: str) -> str:
    return "tr" if (re.search(r"[çğıöşüÇĞİÖŞÜ]", q) or _TR_HINT.search(folded)) else "en"


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_question(q: str) -> dict[str, Any] | None:
    """Extract a scenario (fuel, O2 %, optional pressure / gravity) from a free-text question, else None.

    Fires only when a known fuel AND an oxygen percentage are present, the question is not a statistic request,
    and it either asks about coverage or names a pressure / gravity condition.
    """
    ql = _fold(q)
    if _STAT.search(ql):
        return None
    key = ScenarioChecker._key(ql)
    m = None
    for m in _O2.finditer(ql):
        if m.group(1) or m.group(3) or (m.group(2) and "%" in m.group(0)):
            break
        m = None
    if key is None or not m:
        return None
    o2 = _num(m.group(1) or m.group(2) or m.group(3))
    pressure = None
    for pat, div in ((r"(\d+(?:[.,]\d+)?)\s*atm\b", 1.0), (r"(\d+(?:[.,]\d+)?)\s*psi\b", 14.696),
                     (r"(\d+(?:[.,]\d+)?)\s*kpa\b", 101.325), (r"(\d+(?:[.,]\d+)?)\s*bar\b", 1.01325)):
        pm = re.search(pat, ql)
        if pm:
            pressure = round(_num(pm.group(1)) / div, 3)
            break
    gravity = None
    gm = re.search(r"(\d+(?:[.,]\d+)?)\s*g\b", ql)
    if re.search(r"\b(moon|lunar|ay|ayda|ay'da|ayin)\b", ql):
        gravity = 0.166
    elif re.search(r"\b(mars|martian|marsta|mars'ta)\b", ql):
        gravity = 0.378
    elif re.search(r"microgravity|zero[- ]g|weightless|\biss\b|orbit|mikro ?yercekim\w*|mikrograv\w*|agirliksiz|yorunge|uzay istasyon\w*", ql):
        gravity = 0.0
    elif re.search(r"\b(earth|dunya\w*)\b|sea level|deniz seviye\w*", ql):
        gravity = 1.0
    elif gm:
        gravity = _num(gm.group(1))
    if not (_CUE.search(ql) or pressure is not None or gravity is not None) or not 0 <= o2 <= 100:
        return None
    return {"fuel": FUEL_LABEL[key], "o2": o2, "pressure_atm": pressure, "gravity_g": gravity, "lang": _lang_of(q, ql)}


def parse_report_question(q: str) -> dict[str, Any] | None:
    """'Which materials are covered for a Moon/Mars habitat?' style questions (no fuel or oxygen given)."""
    ql = _fold(q)
    if _STAT.search(ql) or _O2.search(ql) or ScenarioChecker._key(ql):
        return None
    if not re.search(r"habitat|\bkolonisi|\bussu|\bkapsul", ql):
        return None
    hab = "mars" if re.search(r"\b(mars|martian|marsta|mars'ta)\b", ql) else \
        "moon" if re.search(r"\b(moon|lunar|ay|ayda|ay'da|ayin)\b", ql) else None
    if hab is None or not re.search(r"material|malzeme|which|hangi|report|rapor|ozet|summary|covered|kapsa\w*|test edil\w*", ql):
        return None
    return {"habitat": hab, "lang": _lang_of(q, ql)}


def _near_text(n: dict[str, Any], lang: str) -> str:
    p = f"{n['pressure_atm']:g} atm" if n["pressure_atm"] is not None else MSG[lang]["p_unrec_short"]
    o2 = f"%{n['o2_percent']:g} O₂" if lang == "tr" else f"{n['o2_percent']:g}% O₂"
    return f"{n['id']} ({n['name']}, {o2}, {p}, {n['source']})"


def _source_reference(n: dict[str, Any]) -> dict[str, Any]:
    return {
        "citation_id": f"TBL:{n['record_pk']}",
        "source_type": "table_row",
        "investigation_id": n["investigation_id"],
        "locator_label": f"{n['record_pk']} · CSV row {n['csv_record_index']}",
        "source_relpath": n["source_relpath"],
        "source_sha256": n["source_sha256"],
        "record_pk": n["record_pk"],
        "csv_record_index": n["csv_record_index"],
        "physical_line_start": n["physical_line_start"],
        "physical_line_end": n["physical_line_end"],
        "chunk_id": None,
        "document_id": None,
        "section_title": None,
        "printed_page_start": None,
        "printed_page_end": None,
        "pdf_page_start": None,
        "pdf_page_end": None,
        "source_url": None,
    }


def answer_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Chatbot view of a ``check`` result with the field names the chat UI already renders (no LLM, no recomputation)."""
    lang = result.get("lang", "en")
    r = result["requested"]
    cond = ", ".join(x for x in (r["fuel"], (f"%{r['o2_percent']:g} O₂" if lang == "tr" else f"{r['o2_percent']:g}% O₂")
                                 if r["o2_percent"] is not None else None,
                                 f"{r['pressure_atm']:g} atm" if r["pressure_atm"] is not None else None,
                                 f"{r['gravity_g']:g} g" if r["gravity_g"] is not None else None) if x)
    detail = result["status_text"].split(": ", 1)[1]
    first = ("İ" if lang == "tr" and detail[0] == "i" else detail[0].upper())
    summary = f"{result['status']} — {cond}. {first + detail[1:]}"
    if result["differences"]:
        summary += " " + " ".join(result["differences"])
    pre = "En yakın kayıtlı test: " if lang == "tr" else "Nearest recorded test: "
    cited = [n for n in result["nearest"][:3] if n["o2_percent"] is not None]
    findings = [{"text": pre + _near_text(n, lang) + ".", "citation_ids": [f"TBL:{n['record_pk']}"]}
                for n in cited]
    t = result["tolerances"]
    tol = (f"Eşleşme toleransı: ±{t['o2_percentage_points']:g} puan O₂, ±{t['pressure_atm']:g} atm; "
           "indekslenen tüm testler mikro yerçekiminde yapıldı." if lang == "tr" else
           f"Match tolerance: ±{t['o2_percentage_points']:g} points O₂, ±{t['pressure_atm']:g} atm; "
           "every indexed test ran in microgravity.")
    disc = ("Kayıtlı NASA testlerine karşı kapsam kontrolü; güvenlik veya yangın riski değerlendirmesi değildir."
            if lang == "tr" else "Coverage check against recorded NASA tests; not a safety or fire-risk rating.")
    return _envelope_data(summary, findings, result["limitations"] + [tol], disc, "scenario_check",
                          "Scenario Evidence Check", {"scenario_check": result}, result.get("matching_pool_size", 0),
                          [_source_reference(n) for n in cited])


def report_answer_payload(rep: dict[str, Any]) -> dict[str, Any]:
    """Chatbot view of a habitat report."""
    lang = rep["lang"]
    findings = []
    source_rows: dict[str, dict[str, Any]] = {}
    for row in rep["rows"]:
        why = row["differences"][0] if row["differences"] else ""
        rng = (f" ({row['fuel']}: " + (f"%{row['fuel_o2_range'][0]:g}–{row['fuel_o2_range'][1]:g} O₂" if lang == "tr"
               else f"{row['fuel_o2_range'][0]:g}–{row['fuel_o2_range'][1]:g}% O₂ recorded") + ")") if row["fuel_o2_range"] else ""
        nearest = row.get("nearest") or []
        citation_ids = []
        if nearest:
            source_rows[nearest[0]["record_pk"]] = nearest[0]
            citation_ids.append(f"TBL:{nearest[0]['record_pk']}")
        findings.append({"text": f"{row['fuel']}: {row['status']}.{rng} {why}".strip(),
                         "citation_ids": citation_ids})
    disc = ("Kayıtlı NASA testlerine karşı kapsam kontrolü; güvenlik veya yangın riski değerlendirmesi değildir."
            if lang == "tr" else "Coverage check against recorded NASA tests; not a safety or fire-risk rating.")
    return _envelope_data(rep["summary"], findings, rep["limitations"], disc, "scenario_check", "Habitat Evidence Report",
                          {"habitat_report": rep}, 0,
                          [_source_reference(n) for n in source_rows.values()])


def _envelope_data(summary: str, findings: list[dict[str, Any]], limitations: list[str], disclaimer: str, mode: str,
                   badge: str, extra: dict[str, Any], pool: int,
                   sources: list[dict[str, Any]]) -> dict[str, Any]:
    citation_ids = [source["citation_id"] for source in sources]
    return {
        "status": "OK", "answer_mode": mode, "answer_badge": badge, "llm_used": False, "llm_calls": 0,
        "resolved_investigation_id": None, "summary": summary, "findings": findings, "limitations": limitations,
        "warnings": [], "disclaimers": [disclaimer], "sources": sources, "citation_ids": citation_ids, **extra,
        "abstention": {"abstained": False, "reason_code": None, "explanation": None},
        "evidence_overview": {"table_total_runs": pool, "table_shown_runs": len(sources), "document_hit_count": 0,
                              "citation_count": len(sources)},
        "coverage": None,
        "numerical_audit": {"checked": False, "status": "not_applicable",
                            "reason": "Values computed from table records; no generated text to audit.",
                            "violation_count": 0, "checked_claim_count": 0},
        "failure_reason": "NONE",
    }
