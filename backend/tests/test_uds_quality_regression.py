import unittest
import shutil
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import app


class UdsQualityRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        base = Path.cwd() / ".codex_tmp" / "backend_uds_quality_regression"
        base.mkdir(parents=True, exist_ok=True)
        self.root = base / uuid.uuid4().hex
        self.root.mkdir(parents=True, exist_ok=True)
        self.src = self.root / "src"
        self.src.mkdir(parents=True, exist_ok=True)
        self.req = self.root / "req.md"
        self.req.write_text(
            "\n".join(
                [
                    "# SRS",
                    "- system shall initialize state",
                    "- system shall call update routine each cycle",
                ]
            ),
            encoding="utf-8",
        )
        (self.src / "demo.c").write_text(
            "\n".join(
                [
                    "static int g_state = 0;",
                    "int helper(int x) { return x + 1; }",
                    "int update(int in) { g_state = helper(in); return g_state; }",
                    "int main(void) { return update(1); }",
                ]
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _generate(self, **extra):
        data = {
            "source_root": str(self.src),
            "req_paths": str(self.req),
            "doc_only": "true",
            "ai_enable": "false",
            "test_mode": "false",
            "report_dir": "reports",
        }
        data.update(extra or {})
        return self.client.post("/api/local/uds/generate", data=data)

    def test_generate_returns_quality_evaluation(self):
        res = self._generate()
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        self.assertTrue(payload.get("ok"))
        gate = payload.get("quick_quality_gate") or {}
        quality = payload.get("quality_evaluation") or {}
        counts = gate.get("counts") or {}
        rates = gate.get("rates") or {}
        self.assertGreater(int(counts.get("total_functions") or 0), 0)
        self.assertGreater(float(rates.get("called_fill") or 0.0), 0.0)
        self.assertGreater(float(rates.get("calling_fill") or 0.0), 0.0)
        self.assertGreater(float(rates.get("input_fill") or 0.0), 0.0)
        self.assertGreater(float(rates.get("output_fill") or 0.0), 0.0)
        self.assertIn("description_fill", rates)
        self.assertIn("asil_fill", rates)
        self.assertIn("related_fill", rates)
        self.assertIn("description_trusted_fill", rates)
        self.assertIn("asil_trusted_fill", rates)
        self.assertIn("related_trusted_fill", rates)
        self.assertIn("gate_pass", quality)
        self.assertIn("reason_codes", quality)
        self.assertIn("action_hints", quality)
        self.assertIn("confidence_gate_pass", quality)
        self.assertIsInstance(quality.get("action_hints"), list)
        self.assertEqual(str(quality.get("gate_source") or ""), "quick_only")

    def test_template_invalid_fallback_reason_code(self):
        files = {
            "template_file": ("broken.docx", b"not-a-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        }
        res = self.client.post(
            "/api/local/uds/generate",
            data={
                "source_root": str(self.src),
                "req_paths": str(self.req),
                "doc_only": "true",
                "ai_enable": "false",
                "template_strict": "false",
                "report_dir": "reports",
            },
            files=files,
        )
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        codes = (payload.get("quality_evaluation") or {}).get("reason_codes") or []
        self.assertIn("TEMPLATE_INVALID", codes)

    def test_template_invalid_strict_mode_fails(self):
        files = {
            "template_file": ("broken.docx", b"not-a-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        }
        res = self.client.post(
            "/api/local/uds/generate",
            data={
                "source_root": str(self.src),
                "req_paths": str(self.req),
                "doc_only": "true",
                "ai_enable": "false",
                "template_strict": "true",
                "report_dir": "reports",
            },
            files=files,
        )
        self.assertEqual(res.status_code, 400, res.text)

    def test_view_payload_includes_mapping_summary(self):
        res = self._generate(show_mapping_evidence="true")
        self.assertEqual(res.status_code, 200, res.text)
        payload = res.json()
        filename = str(payload.get("filename") or "")
        self.assertTrue(filename)
        view = self.client.get(f"/api/local/uds/view/{filename}?report_dir=reports")
        self.assertEqual(view.status_code, 200, view.text)
        data = view.json()
        summary = data.get("summary") or {}
        mapping = summary.get("mapping") or {}
        self.assertGreaterEqual(int(mapping.get("total") or 0), 1)
        self.assertIn("direct", mapping)
        self.assertIn("fallback", mapping)
        self.assertIn("unmapped", mapping)
        self.assertIn("residual_tbd_count", mapping)


if __name__ == "__main__":
    unittest.main()
