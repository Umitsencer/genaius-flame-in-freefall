"""Unit tests for NASA/TP-2015-216046 Table IX vs PSI-69 CSV reconciliation."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from genaius.flex_reconciliation import (
    DEFAULT_RECONCILIATION_REL_PATH,
    FlexReconciliationError,
    build_flex_reconciliation,
    load_flex_reconciliation,
)


class FlexReconciliationTests(unittest.TestCase):
    def test_reconciliation_resolves_274_vs_276_and_50_vs_51_helium(self) -> None:
        data = load_flex_reconciliation(ROOT)
        summary = data["reconciliation_summary"]

        self.assertEqual(summary["psi69_csv_rows"], 274)
        self.assertEqual(summary["table_ix_rows"], 276)
        self.assertEqual(summary["matched_shared_rows"], 274)
        self.assertEqual(summary["table_ix_only_rows"], 2)
        self.assertEqual(summary["table_ix_only_labels"], ["FLEX-216", "FLEX-230"])
        self.assertEqual(summary["shared_row_value_mismatches"], 0)
        self.assertEqual(summary["psi69_helium_runs"], 50)
        self.assertEqual(summary["table_ix_helium_runs"], 51)
        self.assertEqual(summary["co2_he_overlap_count"], 0)
        self.assertEqual(summary["gas_sum_out_of_0_98_to_1_01_count"], 0)
        self.assertEqual(summary["known_anomalies"]["missing_table_ix_sequence_numbers"], [156, 205, 213, 228])
        self.assertEqual(summary["known_anomalies"]["corrupted_zero_pressure"]["psi_test_id"], "114")

        unresolved_items = {item["item"]: item for item in summary["unresolved"]}
        self.assertEqual(unresolved_items["omission_of_flex_216_and_flex_230_from_psi69_csv"]["status"], "unresolved")

        tp_only = [entry for entry in data["entries"] if entry["status"] == "TP_TABLE_IX_ONLY"]
        self.assertEqual(len(tp_only), 2)
        by_num = {item["tp_number"]: item for item in tp_only}
        self.assertEqual(by_num[216]["flex_identifier"], "N03H201")
        self.assertEqual(by_num[216]["test_end"], "Completion")
        self.assertEqual(by_num[230]["flex_identifier"], "H01H103")
        self.assertEqual(by_num[230]["test_end"], "Disruption")
        self.assertAlmostEqual(by_num[230]["measurements"]["initial_he_mol_frac"], 0.05)

        dup_193 = [entry for entry in data["entries"] if entry["flex_identifier"] == "193F001"]
        self.assertEqual(len(dup_193), 2)
        self.assertEqual([item["psi_test_id"] for item in dup_193], ["70", "73"])

    def test_saved_artifact_matches_live_build_summary(self) -> None:
        loaded = load_flex_reconciliation(ROOT)
        rebuilt = build_flex_reconciliation(ROOT)
        self.assertEqual(loaded["reconciliation_summary"], rebuilt["reconciliation_summary"])
        self.assertEqual(len(loaded["entries"]), 276)

    def test_load_rejects_missing_artifact(self) -> None:
        missing_root = ROOT / "tests" / "_nonexistent_recon_root"
        with self.assertRaises(FlexReconciliationError):
            load_flex_reconciliation(missing_root)

    def test_artifact_file_exists_and_uses_json_not_pickle(self) -> None:
        path = ROOT / DEFAULT_RECONCILIATION_REL_PATH
        self.assertTrue(path.is_file())
        parsed = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(parsed["entries"]), 276)


if __name__ == "__main__":
    unittest.main()
