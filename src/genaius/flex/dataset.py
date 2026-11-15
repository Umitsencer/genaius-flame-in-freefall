"""PSI-69 FLEX training rows built strictly from pre-test inputs, plus the support reference."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..data.contracts import MeasurementStatus
from ..data.loader import load_investigation_records
from .common import (
    GAS_SUM_MAX,
    GAS_SUM_MIN,
    JOINT_DISTANCE_THRESHOLD_STD,
    _diluent_regime,
    _nominal_pressure_bin,
)


@dataclass(frozen=True)
class FlexPreparedRow:
    """Single eligible FLEX training row built strictly from pre-test inputs."""

    test_id: str
    record_pk: str
    csv_row: int
    flex_identifier: str
    fuel: str
    diluent_regime: str
    o2: float
    n2: float
    co2: float
    he: float
    pressure_mmhg: float
    d0_mm: float
    group_atm_p: str
    group_fuel_atm_p: str
    test_end: str
    y_extinction: int
    burning_rate_mm2_s: float | None

    def raw6(self) -> list[float]:
        return [
            1.0 if self.fuel == "Heptane" else 0.0,
            self.o2,
            self.co2,
            self.he,
            self.pressure_mmhg,
            self.d0_mm,
        ]

    def to_reference_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "record_pk": self.record_pk,
            "csv_row": self.csv_row,
            "flex_identifier": self.flex_identifier,
            "fuel": self.fuel,
            "diluent_regime": self.diluent_regime,
            "o2_mol_frac": self.o2,
            "n2_mol_frac": self.n2,
            "co2_mol_frac": self.co2,
            "he_mol_frac": self.he,
            "pressure_mmhg": self.pressure_mmhg,
            "droplet_initial_diameter_mm": self.d0_mm,
            "test_end": self.test_end,
            "burning_rate_mm2_s": self.burning_rate_mm2_s,
        }


def prepare_psi69_training_dataset(repo_root: str | Path) -> dict[str, Any]:
    """Load PSI-69 canonical CSV records into strictly pre-test eligible datasets."""
    root = Path(repo_root).resolve()
    records, meta = load_investigation_records("PSI-69", root)

    rows_clf: list[FlexPreparedRow] = []
    rows_reg: list[FlexPreparedRow] = []
    excluded_clf: list[dict[str, str]] = []
    excluded_reg: list[dict[str, str]] = []

    for rec in records:
        d0_m = rec.measurements["droplet_initial_diameter_mm"]
        p_m = rec.measurements["ambient_pressure_kpa"]
        k_m = rec.measurements["burning_rate_mm2_s"]

        if d0_m.status != MeasurementStatus.MEASURED or d0_m.parsed_value is None or d0_m.parsed_value <= 0:
            excluded_clf.append({"test_id": rec.test_id, "reason": "missing_droplet_initial_diameter_mm"})
            excluded_reg.append({"test_id": rec.test_id, "reason": "missing_droplet_initial_diameter_mm"})
            continue
        if p_m.status != MeasurementStatus.MEASURED or p_m.parsed_value is None or p_m.parsed_value <= 0:
            excluded_clf.append({"test_id": rec.test_id, "reason": "corrupted_nonpositive_ambient_pressure"})
            excluded_reg.append({"test_id": rec.test_id, "reason": "corrupted_nonpositive_ambient_pressure"})
            continue

        fuel = rec.normalized_fields["fuel_norm"]
        o2 = float(rec.measurements["initial_o2_flex_mol_pct"].parsed_value or 0.0)
        n2 = float(rec.measurements["initial_n2_flex_mol_pct"].parsed_value or 0.0)
        co2 = float(rec.measurements["initial_co2_flex_mol_pct"].parsed_value or 0.0)
        he = float(rec.measurements["initial_he_flex_mol_pct"].parsed_value or 0.0)
        pressure_mmhg = float(p_m.parsed_value)
        d0_mm = float(d0_m.parsed_value)
        dil = _diluent_regime(co2, he)
        grp_atm = f"{o2:.2f}_{co2:.2f}_{he:.2f}_{_nominal_pressure_bin(pressure_mmhg)}"
        grp_fuel = f"{fuel}_{grp_atm}"
        tend = rec.normalized_fields["test_end"]
        k_val = float(k_m.parsed_value) if k_m.status == MeasurementStatus.MEASURED and k_m.parsed_value is not None else None

        prepared = FlexPreparedRow(
            test_id=rec.test_id,
            record_pk=rec.record_pk,
            csv_row=rec.source.physical_line_start,
            flex_identifier=rec.normalized_fields["flex_identifier"],
            fuel=fuel,
            diluent_regime=dil,
            o2=o2,
            n2=n2,
            co2=co2,
            he=he,
            pressure_mmhg=pressure_mmhg,
            d0_mm=d0_mm,
            group_atm_p=grp_atm,
            group_fuel_atm_p=grp_fuel,
            test_end=tend,
            y_extinction=1 if tend == "Extinction" else 0,
            burning_rate_mm2_s=k_val,
        )
        rows_clf.append(prepared)
        if k_val is not None:
            rows_reg.append(prepared)
        else:
            excluded_reg.append({"test_id": rec.test_id, "reason": "missing_burning_rate_mm2_s"})

    return {
        "csv_sha256": meta["sha256"],
        "total_records": len(records),
        "rows_clf": rows_clf,
        "rows_reg": rows_reg,
        "excluded_clf": excluded_clf,
        "excluded_reg": excluded_reg,
    }


def _build_support_reference(rows: list[FlexPreparedRow]) -> dict[str, Any]:
    cont_indices = (1, 2, 3, 4, 5)
    raw_vecs = [r.raw6() for r in rows]
    global_stds = []
    for idx in cont_indices:
        s = statistics.pstdev([v[idx] for v in raw_vecs])
        global_stds.append(s if s > 1e-12 else 1.0)

    regime_envelopes: dict[str, Any] = {}
    grouped: dict[tuple[str, str], list[FlexPreparedRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.fuel, row.diluent_regime)].append(row)

    feat_keys = ("o2_mol_frac", "co2_mol_frac", "he_mol_frac", "pressure_mmhg", "droplet_initial_diameter_mm")
    for (fuel, dil), items in sorted(grouped.items()):
        vecs = [it.raw6() for it in items]
        bounds = {
            feat_keys[pos]: {
                "min": round(min(v[pos + 1] for v in vecs), 4),
                "max": round(max(v[pos + 1] for v in vecs), 4),
            }
            for pos in range(5)
        }
        regime_envelopes[f"{fuel}|{dil}"] = {
            "fuel": fuel,
            "diluent_regime": dil,
            "count": len(items),
            "bounds": bounds,
        }

    return {
        "distance_metric": "standardized_euclidean_within_fuel_and_diluent_regime",
        "distance_threshold_std": JOINT_DISTANCE_THRESHOLD_STD,
        "continuous_feature_names": list(feat_keys),
        "global_feature_stds": global_stds,
        "gas_sum_bounds": [GAS_SUM_MIN, GAS_SUM_MAX],
        "n2_bounds": [0.09, 0.88],
        "regime_envelopes": regime_envelopes,
        "reference_runs": [r.to_reference_dict() for r in rows],
    }
