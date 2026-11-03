from __future__ import annotations

import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from ti5_app.models import PRECISION_PROFILES, Precision
from ti5_app.codex_agent import RESULT_SCHEMA, _apply_precision_gate
from ti5_app.codex_runtime import find_codex
from ti5_app.settings import DEFAULT_CODEX_MODEL, SettingsStore, ProviderSettings
from ti5_app.stl_analyzer import analyze_stl, detect_format
from ti5_app.task_engine import run_task
from ti5_app.task_engine import run_forward_rebuild


def write_binary_triangle(path: Path) -> None:
    vertices = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    with path.open("wb") as handle:
        handle.write(b"Ti5 test".ljust(80, b"\0"))
        handle.write(struct.pack("<I", 1))
        handle.write(struct.pack("<12fH", 0.0, 0.0, 1.0, *vertices, 0))


class CoreTests(unittest.TestCase):
    def temp_dir(self):
        return tempfile.TemporaryDirectory()

    def test_binary_analysis(self):
        with self.temp_dir() as temp:
            path = Path(temp) / "one.stl"
            write_binary_triangle(path)
            self.assertEqual(detect_format(path), ("binary", 1))
            result = analyze_stl(path, Precision.SIMPLE)
            self.assertEqual(result.triangle_count, 1)
            self.assertEqual(result.dimensions, [1.0, 1.0, 0.0])
            self.assertEqual(result.boundary_edge_count, 3)

    def test_ascii_analysis(self):
        with self.temp_dir() as temp:
            path = Path(temp) / "one.stl"
            path.write_text("solid x\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 2 0 0\nvertex 0 2 0\nendloop\nendfacet\nendsolid x\n")
            result = analyze_stl(path)
            self.assertEqual(result.format, "ascii")
            self.assertEqual(result.triangle_count, 1)

    def test_task_without_solidworks(self):
        with self.temp_dir() as temp:
            source = Path(temp) / "one.stl"
            output = Path(temp) / "out"
            write_binary_triangle(source)
            result = run_task(source, Precision.MEDIUM, output, False, "mm")
            self.assertTrue(result.analysis_path.exists())
            self.assertTrue(result.plan_path.exists())
            self.assertTrue(result.report_path.exists())
            self.assertTrue(result.task_dir.is_absolute())
            plan = __import__("json").loads(result.plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["min_refinement_iterations"], 2)
            self.assertEqual(plan["min_surface_coverage"], 0.60)

    def test_precision_profiles_become_stricter(self):
        simple = PRECISION_PROFILES[Precision.SIMPLE]
        medium = PRECISION_PROFILES[Precision.MEDIUM]
        fine = PRECISION_PROFILES[Precision.FINE]
        self.assertGreater(simple.target_deviation_mm, medium.target_deviation_mm)
        self.assertGreater(medium.target_deviation_mm, fine.target_deviation_mm)
        self.assertLess(simple.min_surface_coverage, medium.min_surface_coverage)
        self.assertLess(medium.min_surface_coverage, fine.min_surface_coverage)

    def test_codex_schema_uses_strict_objects_recursively(self):
        def inspect_schema(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                    self.assertEqual(set(node.get("required", [])), set(node.get("properties", {})))
                for value in node.values():
                    inspect_schema(value)
            elif isinstance(node, list):
                for value in node:
                    inspect_schema(value)
        inspect_schema(RESULT_SCHEMA)

    @staticmethod
    def passing_engineering_checks():
        return {
            "functional_datum_aligned": True, "single_solid_body": True,
            "all_production_sketches_fully_defined": True, "fix_relations_absent": True,
            "native_reopen_passed": True, "dimension_roundtrip_passed": True,
            "step_reimport_solid_count": 1, "step_max_extreme_delta_mm": 0.001,
            "visual_review_passed": True, "section_review_passed": True,
            "required_features": ["核心外形", "主接口"], "simplified_features": ["小孔", "细筋"],
        }

    def test_yesterday_standard_does_not_reject_scan_noise_alone(self):
        result = {
            "status": "completed", "solid_body_count": 1, "feature_count": 3, "limitations": [],
            "quality_metrics": {
                "rms_deviation_mm": 2.24, "p95_deviation_mm": 4.53,
                "surface_coverage_ratio": 0.37, "feature_coverage_ratio": 0.90,
                "refinement_iterations": 3, "region_results": [{}, {}, {}, {}, {}, {}],
            },
            "engineering_checks": self.passing_engineering_checks(),
        }
        self.assertEqual(_apply_precision_gate(result, "fine"), [])
        self.assertTrue(result["precision_gate"]["passed"])

    def test_gate_rejects_multibody_and_step_mismatch(self):
        checks = self.passing_engineering_checks()
        checks.update(single_solid_body=False, step_reimport_solid_count=3, step_max_extreme_delta_mm=17.5)
        result = {"status":"completed", "solid_body_count":3, "feature_count":10, "limitations":[],
                  "quality_metrics":{"feature_coverage_ratio":1.0,"refinement_iterations":3,
                                     "region_results":[{}, {}, {}, {}, {}, {}]},
                  "engineering_checks":checks}
        failures = _apply_precision_gate(result, "fine")
        self.assertTrue(any("单一实体" in item for item in failures))
        self.assertTrue(any("STEP" in item for item in failures))

    def test_simple_gate_accepts_compliant_metrics(self):
        result = {
            "status": "completed", "solid_body_count": 1, "feature_count": 1, "limitations": [],
            "quality_metrics": {
                "rms_deviation_mm": 1.5, "p95_deviation_mm": 3.0,
                "surface_coverage_ratio": 0.70, "feature_coverage_ratio": 0.75,
                "refinement_iterations": 1, "region_results": [{}, {}, {}],
            },
            "engineering_checks": self.passing_engineering_checks(),
        }
        self.assertEqual(_apply_precision_gate(result, "simple"), [])
        self.assertTrue(result["precision_gate"]["passed"])

    def test_solidworks_failure_keeps_analysis_outputs(self):
        with self.temp_dir() as temp:
            source = Path(temp) / "one.stl"
            output = Path(temp) / "out"
            write_binary_triangle(source)
            with patch("ti5_app.task_engine.import_reference", side_effect=RuntimeError("CAD not ready")):
                result = run_task(source, Precision.MEDIUM, output, True)
            self.assertTrue(result.analysis_path.exists())
            self.assertTrue(result.plan_path.exists())
            self.assertTrue(result.report_path.exists())
            self.assertIsNone(result.output_sldprt)
            self.assertIn("CAD not ready", result.warnings[0])

    def test_settings_round_trip(self):
        with self.temp_dir() as temp:
            store = SettingsStore(Path(temp) / "settings.json")
            expected = ProviderSettings(api_key="secret", model="test-model")
            store.save(expected)
            actual = store.load()
            self.assertEqual(actual.api_key, "secret")
            self.assertEqual(actual.model, "test-model")
            self.assertNotIn("secret", store.path.read_text(encoding="utf-8"))

    def test_default_codex_model_is_astra(self):
        self.assertEqual(DEFAULT_CODEX_MODEL, "gpt-6-astra")

    def test_codex_discovery_supports_desktop_app_private_bin(self):
        with self.temp_dir() as temp:
            local = Path(temp)
            executable = local / "OpenAI" / "Codex" / "bin" / "version-a" / "codex.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"test")
            with patch.dict("os.environ", {"LOCALAPPDATA": str(local)}, clear=False), \
                 patch("ti5_app.codex_runtime.shutil.which", return_value=None):
                self.assertEqual(find_codex(), str(executable.resolve()))

    def test_review_required_keeps_generated_outputs(self):
        with self.temp_dir() as temp:
            root = Path(temp)
            source = root / "one.stl"
            write_binary_triangle(source)

            def fake_agent(_source, task_dir, *_args, **_kwargs):
                files = {
                    "sldprt_path": task_dir / "editable_rebuild.SLDPRT",
                    "step_path": task_dir / "editable_rebuild.STEP",
                    "alignment_manifest_path": task_dir / "alignment_manifest.json",
                    "review_report_path": task_dir / "review_report.json",
                }
                for path in files.values():
                    path.write_text("test", encoding="utf-8")
                return {
                    "status": "review_required", "summary": "STEP 已生成，约束需复核",
                    "solid_body_count": 1, "feature_count": 2, "evidence": [], "limitations": [],
                    **{key: str(value) for key, value in files.items()},
                }

            with patch("ti5_app.task_engine.run_codex_rebuild", side_effect=fake_agent):
                result = run_forward_rebuild(source, Precision.MEDIUM, root / "out")
            self.assertTrue(result.output_sldprt.is_file())
            self.assertTrue(result.output_step.is_file())
            self.assertTrue(result.warnings)

    def test_forward_task_honors_pre_cancel(self):
        with self.temp_dir() as temp:
            root = Path(temp)
            source = root / "one.stl"
            write_binary_triangle(source)
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(InterruptedError):
                run_forward_rebuild(source, Precision.SIMPLE, root / "out", cancel_event=cancelled)


if __name__ == "__main__":
    unittest.main()
