from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.final_source_intents import (
    _authored_claims,
    build_final_source_intents,
    read_final_source_intents,
)
from core.image_prompt_compiler import (
    PROMPT_HARD_LIMIT_CHARS,
    _measurement_content,
    build_image_prompts,
    compile_task_prompt,
    read_image_prompts,
)
from core.image_task_inputs import (
    build_func_story_contract,
    func_story_title_is_specific,
    measurement_contract,
    visual_product_color,
    visual_variation_values,
)
from core.image_tasks import (
    _editable_source_for_task,
    _reference_mode,
    _task_specs,
    build_image_tasks,
    read_image_tasks,
)
from core.io import file_sha256
from core.run_scope import row_in_scope
from core.visual_design_kit import (
    build_visual_design_kits,
    compact_product_claims,
    read_visual_design_kits,
)
from core.visual_design_kit_compiler import (
    VisualDesignKitCompileError,
    compile_visual_design_kit_response,
)
from tests.current_image_contract_fixture import (
    current_art_direction,
    current_image_task,
)


class _Plugin:
    category_id = "bathroom_cabinet"
    display_name = "Bathroom Cabinet"
    product_type = "BATHROOM_CABINET"
    root = Path("products/bathroom_cabinet")

    @staticmethod
    def merged_config() -> dict:
        return {
            "product_type": "BATHROOM_CABINET",
            "display_name": "Bathroom Cabinet",
            "required_role_policy": {
                "counts": {"main": 1, "scene": 1, "func": 1, "size": 1}
            },
            "image_generation": {
                "main_image_policy": "white_background",
                "structure_invariants": ["cabinet body", "door count", "drawer count", "hinges", "shelves"],
                "allowed_internal_props": ["small toiletries on intended storage surfaces"],
                "replaceable_staging": ["loose toiletries, towels, flowers, and wall decor"],
                "forbidden_additions": [{"part": "new handles", "unless_source_visible": True}],
                "role_specific_rules": {
                    "main": ["keep the external canvas pure white"], "scene": ["show realistic bathroom use"],
                    "func": ["show only source-demonstrated functions"], "size": ["preserve the complete source measurement diagram"],
                },
                "template_image_role_order": ["main", "scene", "func", "size"],
            },
        }


def _child() -> dict:
    return {
        "asin": "B000000001",
        "title": "White Bathroom Storage Cabinet with Adjustable Shelf",
        "bullets": ["Adjustable interior shelf organizes tall and short toiletries.", "Wall-mounted storage keeps bathroom essentials within reach.", "Painted engineered wood surface wipes clean."],
        "description": "A compact white cabinet for organized bathroom storage.",
        "specs": {"Material": "Painted engineered wood", "Product Dimensions": "24 W x 8 D x 30 H in", "Mounting Type": "Wall Mount"},
        "normalized_facts": {"color": "white", "style": "shaker", "variation": {"Color": "White"}, "sold_unit_count": 1},
        "sold_unit_count": 1,
        "reference_images": [
            {"url": f"https://example.com/source_{index:02d}.png", "source": "test"}
            for index in range(4)
        ],
    }


def _family() -> dict:
    return {
        "family": {
            "parent_asin": "B000000001",
            "product_type": "BATHROOM_CABINET",
            "children": [_child()],
        }
    }


def _scope() -> dict:
    return {"selected_children": ["B000000001"], "selected_sources": {"B000000001": [0, 1, 2, 3]}}


def _evidence(role: str) -> dict:
    base = {
        "ocr_evidence": {"available": True, "lines": []},
        "trusted_text": [],
        "measurements": [],
        "claims": [],
        "pixel_evidence": {"scene_pixels": False, "product_view_pixels": True},
        "visual_evidence": {
            "status": "not_needed",
            "reason": "deterministic evidence is sufficient",
        },
    }
    if role == "scene":
        base["pixel_evidence"] = {
            "scene_pixels": True,
            "product_view_pixels": False,
        }
    elif role == "func":
        base.update({
            "trusted_text": ["Adjustable shelf provides 3positions for different object heights."],
            "claims": _authored_claims(["Adjustable shelf provides 3positions for different object heights."]),
            "visual_evidence": {
                "status": "success",
                "role_guess": "func",
                "confidence": 0.92,
                "has_callouts_or_panels": True,
                "evidence": ["Adjustable Shelf", "Open Storage Access"],
            },
        })
    elif role == "size":
        base.update({
            "trusted_text": ["Width 24 in", "Height 30 in"],
            "measurements": [
                {
                    "text": "24 in",
                    "raw_text": "24 in",
                    "canonical_pair": "24:in",
                },
                {
                    "text": "30 in",
                    "raw_text": "30 in",
                    "canonical_pair": "30:in",
                },
            ],
        })
    return base


def _planner_payload(intents: list[dict]) -> dict:
    by_role = {row["role"]: row for row in intents}
    claims = compact_product_claims(_child())
    func = by_role["func"]
    source_id = func["claims"][0]["evidence_id"]
    return {
        "family_art_direction": current_art_direction(),
        "source_briefs": [
            {
                "source_id": "source_01",
                "shopping_purpose": "Show realistic bathroom placement, storage access, and product scale.",
                "image_direction": (
                    "Show a believable bathroom use moment with newly selected towels and containers around the unchanged cabinet, using "
                    "realistic wall contact, residential depth, quiet negative space, coordinated surfaces, and enough environmental context "
                    "to explain placement and scale while keeping every source-visible sold-product relationship intact and immediately legible."
                ),
            },
            {
                "source_id": "source_02",
                "shopping_purpose": "Explain how the cabinet adapts storage for everyday bathroom essentials.",
                "func_story": {
                    "title": {
                        "evidence_ids": [source_id],
                        "text": "Adjustable Shelf",
                    },
                    "labels": [
                        {"evidence_ids": [source_id], "text": "Different Object Heights"},
                        {"evidence_ids": [claims[1]["evidence_id"]], "text": "Wall-Mounted Organization"},
                    ],
                },
            },
            {
                "source_id": "source_03",
                "shopping_purpose": "Present the complete source measurement diagram.",
            },
        ],
    }

class ImageBranchCurrentBehaviorTests(unittest.TestCase):
    def test_task_specs_and_size_prompt_preserve_source_coverage(self) -> None:
        sources = [
            {"source_index": 0, "role": "main"},
            {"source_index": 1, "role": "scene"},
            {"source_index": 2, "role": "scene"},
            {"source_index": 3, "role": "func"},
            {"source_index": 4, "role": "func"},
            {"source_index": 5, "role": "size"},
        ]
        specs = _task_specs({"asin": "B1"}, sources)
        self.assertEqual(
            ["main", "scene", "scene_02", "func", "func_02", "size"],
            [row["role"] for row in specs],
        )
        missing = {row["role"]: row for row in _task_specs({}, [{"source_index": 0, "role": "main"}])}
        self.assertTrue(missing["scene"]["evidence_pending"])
        self.assertTrue(missing["func"]["evidence_pending"])
        self.assertTrue(missing["size"]["evidence_pending"])
        main = {"source_path": "main.jpg", "source_sha256": "main-sha"}
        partial_func = {
            "source_path": "func.jpg", "source_sha256": "func-sha",
            "signals": {"reference_completeness": "partial_feature_view"},
        }
        editable = _editable_source_for_task(
            partial_func, main, family="func", product_type="ARTIFICIAL_TREE",
        )
        self.assertIs(editable, main)
        self.assertEqual("func_main_identity_edit", _reference_mode("func", partial_func, editable))
        content = _measurement_content({
            "mode": "source_image",
            "measurement_groups": [
                {"render_text": '28"'},
                {"render_text": '23.5"'},
                {"render_text": "44 lbs"},
            ],
        })
        self.assertIn("44 lbs", content)
        self.assertIn("remove them without adding a replacement heading", content)
        with patch("core.run_scope.read_run_scope", return_value={"selected_children": ["B1"], "selected_sources": {"B1": []}}):
            self.assertFalse(row_in_scope("unused", {"child": "B1", "index": 0}))

    def _source_fixture(
        self,
        job: Path,
    ) -> tuple[list[dict], dict[str, dict]]:
        rows: list[dict] = []
        evidence: dict[str, dict] = {}
        for index, role in enumerate(("main", "scene", "func", "size")):
            relative = Path("images") / "source" / f"source_{index:02d}.png"
            path = job / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new(
                "RGB",
                (320, 320),
                (248 - index * 12, 246 - index * 10, 242 - index * 8),
            ).save(path)
            sha = file_sha256(path)
            rows.append({
                "child": "B000000001",
                "index": index,
                "url": f"https://example.com/source_{index:02d}.png",
                "status": "ok",
                "raw_path": relative.as_posix(),
                "source_sha256": sha,
            })
            evidence[sha] = _evidence(role)
        return rows, evidence

    def test_current_artifact_chain_has_one_fact_authority_and_one_editable_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "reports").mkdir(parents=True)
            visual_child = {
                "variation_values": {"color": "Grey Full Over Full with Trundle"},
                "normalized_facts": {
                    "color": "Grey Full Over Full with Trundle",
                    "variation": {"color": "Grey Full Over Full with Trundle"},
                },
                "specs": {"color": "Grey"},
            }
            self.assertEqual("Grey", visual_product_color(visual_child))
            self.assertEqual({"color": "Grey"}, visual_variation_values(visual_child))
            self.assertEqual("Grey Full Over Full with Trundle", visual_child["variation_values"]["color"])
            rows, evidence = self._source_fixture(job)
            family, scope = _family(), _scope()
            with (
                patch("core.final_source_intents.ensure_run_scope"),
                patch(
                    "core.final_source_intents.download_artifacts_current",
                    return_value=(True, []),
                ),
                patch(
                    "core.final_source_intents.read_download_manifest",
                    return_value={"schema_version": "download-manifest-v2", "rows": rows},
                ),
                patch("core.final_source_intents.read_product_family", return_value=family),
                patch("core.final_source_intents.row_in_scope", return_value=True),
                patch(
                    "core.final_source_intents._collect_evidence_by_sha",
                    return_value=evidence,
                ),
            ):
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                intents = read_final_source_intents(job, plugin=_Plugin())
            self.assertEqual(
                ["main", "scene", "func", "size"],
                [row["role"] for row in intents],
            )
            self.assertGreater(len(intents[2]["claims"][0]["text"].split()), 6)

            payload = _planner_payload(intents)

            def fake_planner(_prompt: str, _paths: list[Path], **kwargs: object) -> str:
                self.assertIn("Use physical colors, materials, light behavior", _prompt)
                self.assertIn("Product identity:", _prompt)
                self.assertNotIn("Known product facts:", _prompt)
                self.assertIn("what the buyer can do or gain", _prompt)
                self.assertLessEqual(len(_prompt), 8000)
                observer = kwargs.get("attempt_observer")
                if callable(observer):
                    observer({
                        "provider": "ccsub",
                        "model": "gemini-3.5-flash",
                        "attempt": 1,
                        "status": "success",
                        "elapsed_ms": 10,
                    })
                return json.dumps(payload)

            with (
                patch("core.visual_design_kit.read_product_family", return_value=family),
                patch("core.visual_design_kit.read_run_scope", return_value=scope),
                patch("core.visual_design_kit.selected_task_source_intents", return_value=intents),
                patch("core.visual_design_kit.load_job", return_value={}),
                patch("core.visual_design_kit.load_env", return_value={}),
                patch(
                    "core.visual_design_kit.gemini_scope_identity",
                    return_value=[{
                        "provider": "ccsub",
                        "model": "gemini-3.5-flash",
                    }],
                ),
                patch(
                    "core.visual_design_kit.gemini_stream_generate",
                    side_effect=fake_planner,
                ),
            ):
                result = build_visual_design_kits(
                    job_dir=job,
                    plugin=_Plugin(),
                    workers=1,
                )
            self.assertFalse(result["failures"])
            kit = read_visual_design_kits(job, plugin=_Plugin())["tasks"][0]
            self.assertIn("family_art_direction", kit)
            self.assertNotIn("product_visual_read", kit)
            self.assertNotIn("family_visual_signature", kit)
            self.assertNotIn("open storage", json.dumps(kit["source_briefs"]).casefold())
            self.assertGreaterEqual(len(Path(kit["planner"]["prompt_path"]).parts), 6)
            scene_brief = next(row for row in kit["source_briefs"] if row["role"] == "scene")
            scene_intent = next(row for row in intents if row["role"] == "scene")
            self.assertEqual(scene_intent["shopping_intent"], scene_brief["shopping_purpose"])

            with (
                patch("core.image_tasks.read_product_family", return_value=family),
                patch("core.image_tasks.read_run_scope", return_value=scope),
                patch("core.image_tasks.selected_task_source_intents", return_value=intents),
                patch("core.image_tasks.planning_source_intents", return_value=intents),
            ):
                task_result = build_image_tasks(job_dir=job, plugin=_Plugin())
            self.assertFalse(task_result["failures"])
            tasks = read_image_tasks(job, category_id=_Plugin.category_id)["tasks"]
            self.assertEqual(4, len(tasks))
            self.assertTrue(all(len(task["generation_references"]) == 1 for task in tasks))
            self.assertTrue(all(task["product_facts"]["product_type"] == "BATHROOM_CABINET" for task in tasks))
            self.assertTrue(all("mirror" not in json.dumps(task["product_boundary"]).casefold() for task in tasks))

            prompt_result = build_image_prompts(job_dir=job, plugin=_Plugin())
            self.assertFalse(prompt_result["failures"])
            prompts = read_image_prompts(
                job,
                category_id=_Plugin.category_id,
            )["prompts"]
            for row in prompts:
                self.assertLessEqual(len(row["prompt"]), PROMPT_HARD_LIMIT_CHARS)
                self.assertIn("[FAMILY ART DIRECTION]", row["prompt"])
                self.assertNotIn("Product Visual Read", row["prompt"])
                self.assertNotIn("Family Visual Signature", row["prompt"])
                self.assertTrue((job / row["prompt_path"]).is_file())
            func_prompt = next(row["prompt"] for row in prompts if row["role"] == "func")
            self.assertIn("Treat all readable text already visible in the editable reference as evidence only", func_prompt)
            self.assertNotIn("layout archetype", func_prompt.casefold())
            self.assertNotIn("Image direction:", func_prompt)
            self.assertIn("Adjustable Shelf", func_prompt)
            self.assertIn("Different Object Heights", func_prompt)
            self.assertIn("Wall-Mounted Organization", func_prompt)
            self.assertIn("do not reconstruct hidden product regions", func_prompt)
            self.assertIn("Retain the presence, coverage, and functional relationship of state-bearing staging", func_prompt)
            self.assertIn("never remove a source-visible mattress, bedding, drawer contents", func_prompt)
            self.assertIn("Palette Direction:", func_prompt)
            self.assertNotIn("Derive the new palette from sold-product body color", func_prompt)
            self.assertIn("do not copy its composition, crop, banner, card geometry", func_prompt)
            self.assertIn("Family visual rules are immutable", func_prompt)
            self.assertNotIn("when it improves hierarchy", func_prompt)
            self.assertIn("large and readable", func_prompt)
            self.assertNotIn("Cohesion Rule:", func_prompt)
            size_prompt = next(row["prompt"] for row in prompts if row["role"] == "size")
            self.assertIn("exact product instance each line measures", size_prompt)
            self.assertIn("Family visual rules are immutable", size_prompt)
            self.assertNotIn("when it improves hierarchy", size_prompt)
            self.assertNotIn("Audience And Market:", size_prompt)
            self.assertNotIn("Environment And Staging:", size_prompt)

    def test_environment_text_does_not_promote_a_scene_to_func(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "reports").mkdir(parents=True)
            rows, evidence = self._source_fixture(job)
            rows = rows[:2]
            source = evidence[rows[1]["source_sha256"]]
            source.update({
                "ocr_evidence": {
                    "available": True,
                    "raw_text": "Multi-scene Application Pathway Wedding Living Room",
                    "lines": [
                        {"text": "Multi-scene Application", "confidence": 0.95},
                        {"text": "Pathway", "confidence": 0.92},
                    ],
                },
                "trusted_text": ["Multi-scene Application", "Pathway"],
                "claims": [],
                "pixel_evidence": {
                    "scene_pixels": True,
                    "product_view_pixels": False,
                },
                "visual_evidence": {
                    "status": "failed",
                    "role_guess": "unknown",
                    "confidence": 0.0,
                    "error": "visual provider unavailable",
                },
            })
            with (
                patch("core.final_source_intents.ensure_run_scope"),
                patch(
                    "core.final_source_intents.download_artifacts_current",
                    return_value=(True, []),
                ),
                patch(
                    "core.final_source_intents.read_download_manifest",
                    return_value={"schema_version": "download-manifest-v2", "rows": rows},
                ),
                patch("core.final_source_intents.read_product_family", return_value=_family()),
                patch("core.final_source_intents.row_in_scope", return_value=True),
                patch(
                    "core.final_source_intents._collect_evidence_by_sha",
                    return_value={
                        row["source_sha256"]: evidence[row["source_sha256"]]
                        for row in rows
                    },
                ),
            ):
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                classified = read_final_source_intents(job, plugin=_Plugin())
            recovered = classified[1]
            self.assertEqual("func", recovered["role"])
            self.assertEqual([], recovered["claims"])
            self.assertIn("func", recovered["classification_reason"])
            self.assertNotIn("source_review_required", recovered["warnings"])
            source["visual_evidence"] = {
                "status": "success",
                "role_guess": "func",
                "confidence": 0.9,
                "has_callouts_or_panels": True,
                "evidence": ["A labeled multi-scene panel"],
            }
            with (
                patch("core.final_source_intents.ensure_run_scope"),
                patch("core.final_source_intents.download_artifacts_current", return_value=(True, [])),
                patch("core.final_source_intents.read_download_manifest", return_value={"schema_version": "download-manifest-v2", "rows": rows}),
                patch("core.final_source_intents.read_product_family", return_value=_family()),
                patch("core.final_source_intents.row_in_scope", return_value=True),
                patch(
                    "core.final_source_intents._collect_evidence_by_sha",
                    return_value={row["source_sha256"]: evidence[row["source_sha256"]] for row in rows},
                ),
            ):
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                classified = read_final_source_intents(job, plugin=_Plugin())
            recovered = classified[1]
            self.assertEqual("func", recovered["role"])
            self.assertEqual([], recovered["claims"])

    def test_measurements_merge_equivalent_units_and_reject_zero_weight(self) -> None:
        equivalent = {
            "normalized_facts": {
                "spec_measurement_records": [
                    {"field": "Height", "text": "3 ft"},
                    {"field": "Height", "text": "36 in"},
                ]
            }
        }
        contract = measurement_contract(equivalent)
        self.assertEqual("confirmed", contract["status"])
        self.assertEqual(1, len(contract["render_text"]))
        zero = {
            "normalized_facts": {
                "spec_measurement_records": [
                    {"field": "Maximum Weight Recommendation", "text": "0 lbs"}
                ]
            }
        }
        self.assertEqual("conflicted", measurement_contract(zero)["status"])

    def test_planner_cannot_reintroduce_product_fact_authority(self) -> None:
        sources = [{
            "source_id": "source_00",
            "source_index": 0,
            "role": "main",
            "source_path": "main.png",
            "source_sha256": "m",
            "input_revision_id": "mr",
            "shopping_intent": "",
            "claims": [],
            "product_claims": [],
            "measurements": [],
        }, {
            "source_id": "source_01",
            "source_index": 1,
            "role": "scene",
            "source_path": "scene.png",
            "source_sha256": "s",
            "input_revision_id": "sr",
            "shopping_intent": "Show realistic room use and product scale.",
            "claims": [],
            "product_claims": [],
            "measurements": [],
        }]
        draft = {
            "family_art_direction": current_art_direction(),
            "source_briefs": [{
                "source_id": "source_01",
                "image_direction": "Show an authentic room use moment.",
                "shopping_purpose": "Show realistic room use and product scale.",
            }],
            "product_visual_read": {
                "sold_product_parts": ["invented mirror"],
            },
        }
        compiled = compile_visual_design_kit_response(
            draft,
            source_manifest=sources,
        )
        self.assertEqual(
            {"family_art_direction", "source_briefs"},
            set(compiled),
        )
        self.assertEqual(
            "Show an authentic room use moment.",
            compiled["source_briefs"][0]["image_direction"],
        )
        open_feel = json.loads(json.dumps(draft))
        open_feel["family_art_direction"]["typography_direction"] = (
            "Use a geometric sans-serif with generous spacing to preserve the open feel of the room."
        )
        compiled_open_feel = compile_visual_design_kit_response(open_feel, source_manifest=sources)
        self.assertIn("open feel", compiled_open_feel["family_art_direction"]["typography_direction"])
        visible_state = json.loads(json.dumps(draft))
        visible_state["family_art_direction"]["environment_and_staging"] = (
            "Keep the two open doors visible as shown in the editable reference."
        )
        compiled_state = compile_visual_design_kit_response(visible_state, source_manifest=sources)
        self.assertIn("two open doors", compiled_state["family_art_direction"]["environment_and_staging"])
        state_decision = json.loads(json.dumps(draft))
        state_decision["family_art_direction"]["environment_and_staging"] = (
            "Show two open doors in every role."
        )
        with self.assertRaisesRegex(VisualDesignKitCompileError, "changes a source-visible product state"):
            compile_visual_design_kit_response(state_decision, source_manifest=sources)
        overlong = json.loads(json.dumps(draft))
        overlong["family_art_direction"]["palette_direction"] = "x" * 2201
        with self.assertRaisesRegex(VisualDesignKitCompileError, "exceeds 2200"):
            compile_visual_design_kit_response(overlong, source_manifest=sources)
        for field, instruction in (
            ("source_brief", "Title: Spacious Everyday Storage"),
            ("typography_direction", "Set the headline to Modern Loft Bed in charcoal ink."),
            ("negative_visuals", "The visible label reads Premium Storage"),
        ):
            polluted = json.loads(json.dumps(draft))
            if field == "source_brief":
                polluted["source_briefs"][0]["image_direction"] = instruction
            elif field == "negative_visuals":
                polluted["family_art_direction"][field][0] = instruction
            else:
                polluted["family_art_direction"][field] = instruction
            if field == "source_brief":
                with self.assertRaisesRegex(VisualDesignKitCompileError, "renderable-copy instruction"):
                    compile_visual_design_kit_response(polluted, source_manifest=sources)
            else:
                with self.assertRaisesRegex(VisualDesignKitCompileError, "renderable-copy instruction"):
                    compile_visual_design_kit_response(polluted, source_manifest=sources)
        artificial_scene = json.loads(json.dumps(draft))
        artificial_scene["source_briefs"][0]["image_direction"] = (
            "Restyle the front door, wall siding, floor, and doormat while keeping the tree and pot unchanged."
        )
        compiled_tree = compile_visual_design_kit_response(
            artificial_scene, source_manifest=sources, category_id="artificial_tree",
        )
        self.assertIn("front door", compiled_tree["source_briefs"][0]["image_direction"])
        sold_change = json.loads(json.dumps(artificial_scene))
        sold_change["source_briefs"][0]["image_direction"] = "Replace the tree and pot with a new container."
        with self.assertRaisesRegex(VisualDesignKitCompileError, "source-visible product state"):
            compile_visual_design_kit_response(
                sold_change, source_manifest=sources, category_id="artificial_tree",
            )

    def test_func_story_contract_is_single_evidence_bound_authority(self) -> None:
        self.assertFalse(func_story_title_is_specific("Secure Wall Mounting"))
        self.assertFalse(func_story_title_is_specific("Secure Wall-Mounting"))
        self.assertFalse(func_story_title_is_specific("Durable Painted Finish"))
        self.assertFalse(func_story_title_is_specific("User Friendly Details"))
        self.assertTrue(func_story_title_is_specific("Adjust Shelf Height"))
        sources = [
            {
                "source_id": "source_00",
                "source_index": 0,
                "role": "main",
                "source_path": "main.png",
                "source_sha256": "m",
                "input_revision_id": "mr",
                "shopping_intent": "",
                "claims": [],
                "product_claims": [],
                "measurements": [],
            },
            {
                "source_id": "source_01",
                "source_index": 1,
                "role": "func",
                "source_path": "func.png",
                "source_sha256": "f",
                "input_revision_id": "fr",
                "shopping_intent": "show adjustable storage",
                "claims": [
                    {"evidence_id": "e1", "source_sha256": "f", "text": "Adjustable Shelf", "type": "visible_function_text", "confidence": "source_visible"},
                    {"evidence_id": "e2", "source_sha256": "f", "text": "Wall-Mounted Storage", "type": "visible_function_text", "confidence": "source_visible"},
                    {"evidence_id": "e3", "source_sha256": "f", "text": "Painted Wood Surface", "type": "visible_function_text", "confidence": "source_visible"},
                ],
                "product_claims": [
                    {"evidence_id": "e4", "text": "Floor Mount", "type": "apify_feature"},
                ],
                "measurements": [],
            },
        ]
        draft = {
            "family_art_direction": current_art_direction(),
            "source_briefs": [{
                "source_id": "source_01",
                "shopping_purpose": "Explain flexible bathroom organization.",
                "func_story": {
                    "title": {"evidence_ids": ["e1"], "text": "Customizable Storage Space"},
                    "labels": [
                        {"evidence_ids": ["e1"], "text": "Adjustable Interior Shelf"},
                        {"evidence_ids": ["e2"], "text": "Wall-Mounted Organization"},
                        {"evidence_ids": ["e3"], "text": "Premium Painted Surface"},
                    ],
                },
            }],
        }
        compiled = compile_visual_design_kit_response(
            draft,
            source_manifest=sources,
        )
        brief = compiled["source_briefs"][0]
        self.assertNotIn("formation_status", brief)
        self.assertEqual("Customizable Storage Space", brief["func_story_contract"]["title"])
        self.assertEqual(3, len(brief["func_story_contract"]["labels"]))
        self.assertEqual("Premium Painted Surface", brief["func_story_contract"]["labels"][-1])
        sparse = json.loads(json.dumps(draft))
        sparse["source_briefs"][0]["func_story"]["labels"] = []
        sparse_compiled = compile_visual_design_kit_response(
            sparse,
            source_manifest=sources,
        )
        sparse_story = build_func_story_contract(
            sources[1],
            sparse_compiled["source_briefs"][0],
            product_claims=sources[1]["product_claims"],
        )
        self.assertEqual("Customizable Storage Space", sparse_story["title"])
        self.assertEqual([], sparse_story["labels"])
        empty = json.loads(json.dumps(draft))
        empty["source_briefs"][0]["func_story"]["title"] = {}
        with self.assertRaises(VisualDesignKitCompileError):
            compile_visual_design_kit_response(empty, source_manifest=sources)
        laundered = json.loads(json.dumps(draft))
        laundered["source_briefs"][0]["func_story"]["title"] = {"evidence_ids": ["e4"], "text": "Sturdy Floor Mount"}
        with self.assertRaisesRegex(VisualDesignKitCompileError, "evidence-bound"):
            compile_visual_design_kit_response(laundered, source_manifest=sources)

        sparse_sources = json.loads(json.dumps(sources))
        sparse_sources[1]["claims"] = [{
            "evidence_id": "e0", "source_sha256": "f", "text": "Storage",
            "type": "visible_function_text", "confidence": "source_visible",
        }]
        sparse_sources[1]["product_claims"] = [{
            "evidence_id": "e5", "text": "Adjustable Interior Shelf",
            "type": "apify_feature",
        }]
        product_fact_draft = json.loads(json.dumps(draft))
        product_fact_draft["source_briefs"][0]["func_story"] = {
            "title": {"evidence_ids": ["e5"], "text": "Adjustable Interior Shelf"},
            "labels": [],
        }
        product_fact_compiled = compile_visual_design_kit_response(
            product_fact_draft, source_manifest=sparse_sources,
        )
        self.assertNotIn("formation_status", product_fact_compiled["source_briefs"][0])


if __name__ == "__main__":
    unittest.main()
