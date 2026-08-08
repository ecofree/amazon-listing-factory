from __future__ import annotations

import unittest

from core import env_layout


class EnvLayoutTests(unittest.TestCase):
    def test_normalize_env_removes_obsolete_provider_route_keys_and_preserves_values(self) -> None:
        raw = "\n".join(
            [
                "VISION_GEMINI_ENDPOINTS=https://old.example|key|model",
                "HOLDAI_API_KEY=secret-holdai",
                "YUNWU_API_KEY=secret-yunwu",
                "CCAPI_API_KEY=secret-ccapi",
                "GEMINI_API_KEY=secret-gemini",
                "NAMAX_API_KEY=secret-namax",
                "CCSUB_API_KEY=secret-ccsub",
                "MODEL_PULS_API_KEY=retired-model-puls",
                "NEWTOKEN_API_KEY=retired-newtoken",
                "R2_BUCKET=my-bucket",
                "UNKNOWN_KEEP=value",
                "VIP123_API_KEY=retired",
                "AMAZON_FACTORY_QA_REUSE_ACCEPTED=1",
                "AMAZON_FACTORY_STRICT_OCR=0",
            ]
        )

        normalized = env_layout.normalize_env_text(raw)

        self.assertIn("HOLDAI_API_KEY=secret-holdai", normalized)
        self.assertIn("YUNWU_API_KEY=secret-yunwu", normalized)
        self.assertIn("NAMAX_API_KEY=secret-namax", normalized)
        self.assertIn("CCAPI_API_KEY=secret-ccapi", normalized)
        self.assertIn("CCSUB_API_KEY=secret-ccsub", normalized)
        self.assertIn("R2_BUCKET=my-bucket", normalized)
        self.assertIn("UNKNOWN_KEEP=value", normalized)
        self.assertNotIn("GEMINI_API_KEY", normalized)
        self.assertNotIn("VISION_GEMINI_ENDPOINTS", normalized)
        self.assertNotIn("VIP123_API_KEY", normalized)
        self.assertNotIn("AMAZON_FACTORY_QA_REUSE_ACCEPTED", normalized)
        self.assertNotIn("AMAZON_FACTORY_STRICT_OCR", normalized)
        self.assertNotIn("MODEL_PULS_API_KEY", normalized)
        self.assertNotIn("NEWTOKEN_API_KEY", normalized)

    def test_normalize_env_groups_model_keys_by_scope(self) -> None:
        raw = "\n".join(
            [
                "CAVOTI_API_KEY=secret-cavoti",
                "HOLDAI_API_KEY=secret-holdai",
                "YUNWU_API_KEY=secret-yunwu",
                "NAMAX_API_KEY=secret-namax",
                "CCAPI_API_KEY=secret-ccapi",
                "CCSUB_API_KEY=secret-ccsub",
            ]
        )

        normalized = env_layout.normalize_env_text(raw)

        self.assertLess(normalized.index("# Vision models"), normalized.index("HOLDAI_API_KEY"))
        self.assertLess(normalized.index("# Vision models"), normalized.index("YUNWU_API_KEY"))
        self.assertLess(normalized.index("# Vision models"), normalized.index("NAMAX_API_KEY"))
        self.assertLess(normalized.index("# Vision models"), normalized.index("CCAPI_API_KEY"))
        self.assertLess(normalized.index("# Vision models"), normalized.index("CCSUB_API_KEY"))
        self.assertLess(normalized.index("# Image generation"), normalized.index("CAVOTI_API_KEY"))


if __name__ == "__main__":
    unittest.main()
