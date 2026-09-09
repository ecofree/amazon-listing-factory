import json
import unittest
from unittest.mock import patch

from core.copy_writer import (
    CopyWriterConfig,
    CopyWriterError,
    _parse_copy_response,
    _rewrite_listing_copy_with_openai,
)
from core.copy_polish import _validate_artifact_provenance


def _body(payload: dict) -> str:
    return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]})


class CopyV1ContractTests(unittest.TestCase):
    def test_parent_artifact_uses_optional_parent_highlight_contract(self) -> None:
        row = {
            "title": "Wall Mounted Medicine Cabinet",
            "item_highlights": [
                "Wall mounted design", "Adjustable shelf", "Two door storage",
                "Engineered wood", "Easy assembly", "Bathroom organization",
            ],
            "bullets": ["A useful fact"] * 5,
            "description": "A wall mounted cabinet for organized storage.",
            "provider": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "request_fingerprint": "parent-fingerprint",
        }
        row["bullets"] = [
            "Wall mounted storage for compact rooms",
            "Adjustable shelf supports varied item heights",
            "Two doors keep everyday items organized",
            "Engineered wood provides sturdy construction",
            "Simple assembly supports quick setup",
        ]
        _validate_artifact_provenance({
            "rows": {"__parent__": row},
            "groups": [],
            "parent_model_request_fingerprint": "parent-fingerprint",
        })

    def test_multiple_item_highlights_and_brandless_size_first_title(self) -> None:
        payload = {
            "title": "24 Inch Wall Mount Medicine Cabinet with Mirror",
            "item_highlights": ["Adjustable Shelf", "Mirrored Door", "Wall-Mounted Storage"],
            "bullets": [
                "Wall Mount: Keeps medicine organized in a compact cabinet",
                "Adjustable Shelf: Repositions storage for daily essentials",
                "Mirror Door: Provides a clear reflective surface",
                "Magnetic Catch: Keeps the door closed during normal use",
                "Home Placement: Fits bathroom and first-aid storage areas",
            ],
            "description": "A wall-mounted medicine cabinet for organized bathroom and first-aid storage.",
        }
        result = _parse_copy_response(_body(payload), brand="safeplus")
        self.assertEqual(payload["item_highlights"], result["item_highlights"])
        self.assertNotIn("safeplus", result["title"].lower())
        separated = {
            "title": "24 Inch Wall Mount Medicine Cabinet",
            "item_highlights": ["Adjustable Shelf, Mirrored Door", "Wall-Mounted Storage"],
            "bullets": [
                "Wall Mount: Keeps medicine organized in a compact cabinet",
                "Adjustable Shelf: Repositions storage for daily essentials",
                "Mirror Door: Provides a clear reflective surface",
                "Magnetic Catch: Keeps the door closed during normal use",
                "Home Placement: Fits bathroom and first-aid storage areas",
            ],
            "description": "A wall-mounted medicine cabinet for organized bathroom and first-aid storage.",
        }
        result = _parse_copy_response(_body(separated), brand="safeplus")
        self.assertEqual(
            ["Adjustable Shelf", "Mirrored Door", "Wall-Mounted Storage"],
            result["item_highlights"],
        )
        parent_payload = dict(separated)
        parent_payload["item_highlights"] = ["Green"]
        parent_result = _parse_copy_response(_body(parent_payload), brand="safeplus", row_type="parent")
        self.assertEqual([], parent_result["item_highlights"])

    def test_forbidden_claim_is_not_laundered(self) -> None:
        payload = {
            "title": "Wall Mount Medicine Cabinet with Mirror",
            "item_highlights": ["Adjustable Shelf", "Mirrored Door", "Wall-Mounted Storage"],
            "bullets": [
                "Best Seller: A practical cabinet for daily storage",
                "Adjustable Shelf: Repositions storage for daily essentials",
                "Mirror Door: Provides a clear reflective surface",
                "Magnetic Catch: Keeps the door closed during normal use",
                "Home Placement: Fits bathroom and first-aid storage areas",
            ],
            "description": "A wall-mounted medicine cabinet for organized bathroom and first-aid storage.",
        }
        with self.assertRaises(CopyWriterError):
            _parse_copy_response(_body(payload), brand="safeplus")
        payload["bullets"][0] = "Weight Capacity: Supports up to 900 lbs"
        with self.assertRaisesRegex(CopyWriterError, "capacity value"):
            _parse_copy_response(_body(payload), brand="safeplus", product_specific={"weight_capacity": "300 lbs", "shipping_weight": "900 lbs"})
        payload["bullets"][0] = "Weight Capacity: Supports up to 300 lbs"
        _parse_copy_response(_body(payload), brand="safeplus", product_specific={"weight_capacity": "300 lbs"})

    def test_model_repairs_all_reported_copy_errors_in_one_followup(self) -> None:
        invalid = {
            "title": "safeplus Wall Mount Medicine Cabinet with Adjustable Interior Shelf and Mirrored Door for Bathroom Organization",
            "item_highlights": ["Adjustable Interior Shelf Storage for Everyday Bathroom Organization Needs"],
            "bullets": [
                "Rust-Proof Storage: Supports up to 22 pounds while organizing medicine bottles, daily toiletries, first aid supplies, and compact bathroom essentials without wasting vertical cabinet space",
                "Mirrored Door: Provides a reflective front for daily bathroom routines",
                "Wall Mounting: Keeps stored items above the vanity and within reach",
                "Magnetic Catch: Helps keep the cabinet door closed during normal use",
                "Compact Storage: Organizes essentials in smaller bathroom spaces",
            ],
            "description": "A wall-mounted medicine cabinet for organized bathroom and first-aid storage.",
        }
        valid = {
            "title": "Wall Mount Medicine Cabinet with Mirror",
            "item_highlights": ["Adjustable Shelf", "Mirrored Door", "Wall-Mounted Storage"],
            "bullets": [
                "Adjustable Shelf: Repositions storage for medicine and toiletries",
                "Mirrored Door: Provides a reflective front for bathroom routines",
                "Wall Mounting: Keeps stored items above the vanity and within reach",
                "Magnetic Catch: Helps keep the cabinet door closed during normal use",
                "Compact Storage: Organizes essentials in smaller bathroom spaces",
            ],
            "description": "A wall-mounted medicine cabinet for organized bathroom and first-aid storage.",
        }
        responses = [_body(invalid), _body(valid)]
        config = CopyWriterConfig(
            enabled=True, api_key="test", base_url="https://example.test/v1",
            model="copy-model", timeout=10,
        )
        with patch("core.copy_writer._post_chat_completion", side_effect=responses) as post:
            result = _rewrite_listing_copy_with_openai(
                config=config,
                category="medicine_cabinet",
                brand="safeplus",
                row_type="child",
                source_title="Wall Mount Medicine Cabinet",
                source_bullets=["Adjustable shelf storage", "Wall-mounted organization"],
                source_description="",
                product_specific={
                    "mounting_type": "wall mount", "shelf": "adjustable",
                    "item_weight": "22", "item_weight_unit": "Pounds",
                },
            )
        self.assertEqual(valid["title"], result["title"])
        self.assertEqual(2, post.call_count)
        repair = json.loads(post.call_args_list[1].args[1]["messages"][1]["content"])
        error = repair["validation_error"]
        self.assertIn("title exceeds", error)
        self.assertIn("bullet exceeds", error)
        self.assertIn("unsupported rust-proof", error)
        self.assertIn("unsupported weight capacity", error)
        self.assertIn("Rust-Proof Storage", repair["invalid_copy_to_repair"])
        self.assertIn("item_highlights_repair_contract", repair)
        first_request = json.loads(post.call_args_list[0].args[1]["messages"][1]["content"])
        self.assertEqual(
            ["Adjustable shelf storage", "Wall-mounted organization"],
            first_request["source"]["item_highlights"],
        )
        self.assertIn("own mass only", first_request["fact_semantics"]["item_weight"])
        self.assertIn("structure nouns exact across the family", post.call_args_list[0].args[1]["messages"][0]["content"])
        title_only_invalid = {
            **valid,
            "title": "safeplus Wall Mounted Medicine Cabinet with Adjustable Interior Shelf and Mirrored Door for Bathroom Organization",
        }
        with patch(
            "core.copy_writer._post_chat_completion",
            side_effect=[_body(title_only_invalid), _body({"title": valid["title"]})],
        ) as title_post:
            focused = _rewrite_listing_copy_with_openai(
                config=config,
                category="medicine_cabinet",
                brand="safeplus",
                row_type="child",
                source_title="Wall Mount Medicine Cabinet",
                source_bullets=["Adjustable shelf storage"],
                source_description="",
                product_specific={"mounting_type": "wall mount", "shelf": "adjustable"},
            )
        self.assertEqual(valid["title"], focused["title"])
        title_repair = json.loads(title_post.call_args_list[1].args[1]["messages"][1]["content"])
        self.assertEqual(title_only_invalid["title"], title_repair["invalid_title"])
        self.assertIn("title exceeds", title_repair["validation_error"])
        self.assertEqual("55 characters or fewer", title_repair["title_only_contract"]["target"])
        self.assertIn("standalone measurement", title_repair["title_only_contract"]["ending"])
        self.assertIn("Preserve exact product structure nouns", title_post.call_args_list[1].args[1]["messages"][0]["content"])
        highlight_only_invalid = {**valid, "item_highlights": ["Adjustable Shelf"]}
        with patch(
            "core.copy_writer._post_chat_completion",
            side_effect=[
                _body(highlight_only_invalid),
                _body({"item_highlights": valid["item_highlights"]}),
            ],
        ) as highlight_post:
            focused_highlights = _rewrite_listing_copy_with_openai(
                config=config,
                category="medicine_cabinet",
                brand="safeplus",
                row_type="child",
                source_title="Wall Mount Medicine Cabinet",
                source_bullets=["Adjustable shelf storage", "Mirrored door", "Wall-mounted organization"],
                source_description="",
                product_specific={"mounting_type": "wall mount", "shelf": "adjustable"},
            )
        self.assertEqual(valid["item_highlights"], focused_highlights["item_highlights"])
        highlight_repair = json.loads(highlight_post.call_args_list[1].args[1]["messages"][1]["content"])
        self.assertEqual(3, len(highlight_repair["source_item_highlights"]))
        self.assertEqual(2, highlight_post.call_count)

        with patch(
            "core.copy_writer._post_chat_completion",
            side_effect=[_body(highlight_only_invalid), _body(valid)],
        ):
            full_envelope = _rewrite_listing_copy_with_openai(
                config=config,
                category="medicine_cabinet",
                brand="safeplus",
                row_type="child",
                source_title="Wall Mount Medicine Cabinet",
                source_bullets=["Adjustable shelf storage", "Mirrored door", "Wall-mounted organization"],
                source_description="",
                product_specific={"mounting_type": "wall mount", "shelf": "adjustable"},
            )
        self.assertEqual(valid["item_highlights"], full_envelope["item_highlights"])

        over_budget = [
            "Adjustable Interior Shelf",
            "Two Spacious Storage Drawers",
            "Mid Century Wooden Headboard",
            "Sturdy Wooden Slat Support",
            "No Box Spring Required",
        ]
        over_budget_invalid = {**valid, "item_highlights": over_budget}
        with patch(
            "core.copy_writer._post_chat_completion",
            side_effect=[_body(over_budget_invalid), _body({"item_highlights": over_budget})],
        ) as budget_post:
            budgeted = _rewrite_listing_copy_with_openai(
                config=config,
                category="bed_frame",
                brand="safeplus",
                row_type="child",
                source_title="Wood Bed Frame",
                source_bullets=over_budget,
                source_description="",
                product_specific={"frame_material": "wood"},
            )
        self.assertGreaterEqual(len(budgeted["item_highlights"]), 2)
        self.assertLess(len(", ".join(budgeted["item_highlights"])), 120)
        self.assertTrue(all(item in over_budget for item in budgeted["item_highlights"]))
        self.assertEqual(2, budget_post.call_count)
        bullet_only_invalid = {
            **valid,
            "bullets": [
                *valid["bullets"][:3],
                "Magnetic Catch: Helps keep the cabinet door closed during normal use while organizing daily essentials in compact bathroom spaces without loose movement during routines",
                valid["bullets"][4],
            ],
        }
        with patch(
            "core.copy_writer._post_chat_completion",
            side_effect=[
                _body(bullet_only_invalid),
                _body({"replacement_bullets": [{"index": 4, "text": valid["bullets"][3]}]}),
            ],
        ) as bullet_post:
            focused_bullet = _rewrite_listing_copy_with_openai(
                config=config,
                category="medicine_cabinet",
                brand="safeplus",
                row_type="child",
                source_title="Wall Mount Medicine Cabinet",
                source_bullets=["Adjustable shelf storage"],
                source_description="",
                product_specific={"mounting_type": "wall mount", "shelf": "adjustable"},
            )
        self.assertEqual(valid["bullets"], focused_bullet["bullets"])
        bullet_repair = json.loads(bullet_post.call_args_list[1].args[1]["messages"][1]["content"])
        self.assertEqual(4, bullet_repair["invalid_bullets"][0]["index"])
        self.assertEqual("105 characters or fewer per bullet", bullet_repair["contract"]["target"])
        with patch(
            "core.copy_writer._post_chat_completion",
            side_effect=[
                _body(highlight_only_invalid),
                _body({"item_highlights": ["Adjustable Shelf"]}),
            ],
        ):
            with self.assertRaises(CopyWriterError) as exhausted:
                _rewrite_listing_copy_with_openai(
                    config=config,
                    category="medicine_cabinet",
                    brand="safeplus",
                    row_type="child",
                    source_title="Wall Mount Medicine Cabinet",
                    source_bullets=["Adjustable shelf storage"],
                    source_description="",
                    product_specific={"mounting_type": "wall mount"},
                )
        self.assertTrue(exhausted.exception.retryable)
        payload = {
            "title": "Twin Loft Bed with 12\"",
            "item_highlights": ["Built-In Slide", "Access Ladder", "Upper Guardrails"],
            "bullets": [
                "Metal frame supports the loft sleeping area",
                "Guardrails help define the upper sleeping space",
                "Ladder provides access to the upper bed",
                "Slide adds a play feature beside the bed",
                "Under bed space supports room organization",
            ],
            "description": "A twin loft bed with a metal frame and slide.",
        }
        with self.assertRaisesRegex(CopyWriterError, "unattached_measurement"):
            _parse_copy_response(_body(payload), brand="safeplus")


if __name__ == "__main__":
    unittest.main()
