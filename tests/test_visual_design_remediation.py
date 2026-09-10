from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.io import read_json
from core.visual_semantics import _attempt_trace
from core.visual_design_kit_compiler import cleaned_source_claims, _compile_func_story
from core.vision_gemini_client import (
    _gemini_native_payload, _parse_sse_text_candidates, _parse_generate_content_candidates,
    _response_finish_reasons,
)


class VisualDesignRemediationTests(unittest.TestCase):
    def test_reference_crops_remove_page_layout_without_altering_product_pixels(self):
        from PIL import Image, ImageChops
        from core.io import file_sha256
        from core.image_reference_context import prepare_planning_views, planning_view_inputs, physical_views
        from core.final_source_intents import _semantic_revision
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            with Image.new("RGB", (100, 100), "magenta") as poster:
                poster.paste((180, 140, 80), (10, 10, 40, 40))
                poster.paste((20, 180, 90), (60, 60, 90, 90))
                poster.save(job / "source.png")
            views = [{"view_id": "upper", "region": [.1, .1, .4, .4]},
                     {"view_id": "lower", "region": [.6, .6, .9, .9]}]
            source = {"source_id": "source_02", "source_path": "source.png",
                      "source_sha256": file_sha256(job / "source.png"), "observation": {"physical_views": views}}
            paths = prepare_planning_views(job, [source], job / "trace")
            self.assertEqual([{"attachment_number": i + 1, "source_id": "source_02", "view_id": name}
                              for i, name in enumerate(("upper", "lower"))], planning_view_inputs([source]))
            with Image.open(job / "source.png") as original:
                for path, box in zip(paths, ((10, 10, 40, 40), (60, 60, 90, 90))):
                    with Image.open(path) as crop, original.crop(box) as expected:
                        self.assertIsNone(ImageChops.difference(crop, expected).getbbox())
                        self.assertNotIn((255, 0, 255), set(crop.getdata()))
            self.assertEqual(source["source_sha256"], file_sha256(job / "source.png"))
            before = _semantic_revision({"visual_evidence": {"physical_views": views}})
            views[0]["region"][0] = .09
            self.assertNotEqual(before, _semantic_revision({"visual_evidence": {"physical_views": views}}))
            for invalid in (None, [{"view_id": "x", "region": [0, 0, float('nan'), 1]}], [views[0], views[0]]):
                with self.assertRaises(ValueError):
                    physical_views(invalid)
            source["observation"]["physical_views"] = []
            with self.assertRaisesRegex(ValueError, "no observed physical views"):
                prepare_planning_views(job, [source], job / "empty")
            source["observation"]["physical_views"] = views
            source["source_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "source changed"):
                prepare_planning_views(job, [source], job / "changed")

    def test_local_repair_uses_same_independent_views_and_rejects_view_loss(self):
        import time
        from core.visual_design_kit import _finish_source_briefs
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction
        views = [{"view_id": "view_01", "region": [.1, .1, .4, .4]},
                 {"view_id": "view_02", "region": [.6, .6, .9, .9]}]
        source = {"source_id": "source_00", "role": "size", "source_sha256": "a" * 64,
                  "input_revision_id": "r", "measurements": [], "observation": {"physical_views": views}}
        direction = current_image_direction(environment="graphic_canvas")
        direction["layout"].append({"view_id": "view_02", "target_region": [.1, .6, .5, .9]})
        raw = {"family_art_direction": current_art_direction(), "source_briefs": [{
            "source_id": "source_00", "shopping_purpose": "", "image_direction": direction}]}
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp)
            paths = [trace / "view_001.png", trace / "view_002.png"]
            def repair(prompt, attachments, **kwargs):
                self.assertEqual(paths, attachments)
                self.assertIn('"attachment_number": 2', prompt)
                self.assertIn('"view_id": "view_02"', prompt)
                self.assertNotIn('"region":', prompt)
                return json.dumps({"source_briefs": [{**raw["source_briefs"][0],
                    "shopping_purpose": "Show both measured views clearly."}]})
            with patch("core.visual_design_kit.review_claims", return_value={}), patch(
                "core.visual_design_kit.gemini_stream_generate", side_effect=repair) as call:
                result = _finish_source_briefs(raw, source_manifest=[source], category_id="bed_frame",
                    source_paths=paths, trace_dir=trace, deadline_monotonic=time.monotonic() + 10, cached=None)
            self.assertEqual(1, call.call_count)
            self.assertEqual("ready", result["source_briefs"][0]["status"])
        raw["source_briefs"][0]["shopping_purpose"] = "Show both measured views clearly."
        direction["layout"].pop()
        rejected = compile_visual_design_kit_response(raw, source_manifest=[source])
        self.assertIn("every source physical view", rejected["source_briefs"][0]["error"])

    def test_independent_canvas_uses_one_design_contract_without_source_style(self):
        from core.visual_design_kit import visual_design_kit_prompt
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        from core.image_prompt_compiler import compile_task_prompt
        from core.plugin import load_plugin
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction, current_image_task
        source = {"source_id": "source_00", "source_index": 0, "role": "main", "input_revision_id": "r",
                  "source_sha256": "a" * 64, "shopping_intent": "OLD_PURPOSE", "claims": [], "measurements": [],
                  "observation": {"objects": [], "physical_views": [{"view_id": "view_01", "region": [.1, .2, .9, .8]}], "layout_summary": "OLD_CAPSULE_LAYOUT",
                                  "text_observations": [{"kind": "prop", "text": "OLD_PROP_WORDS"}]}}
        prompt = visual_design_kit_prompt(load_plugin("bed_frame"), {}, {}, [source])
        for old in ("OLD_PURPOSE", "OLD_CAPSULE_LAYOUT", "OLD_PROP_WORDS"):
            self.assertNotIn(old, prompt)
        raw = {"family_art_direction": current_art_direction(), "source_briefs": [{
            "source_id": "source_00", "shopping_purpose": "Understand physical construction.",
            "image_direction": "obsolete unconstrained string"}]}
        rejected = compile_visual_design_kit_response(raw, source_manifest=[source])
        self.assertEqual("pending", rejected["source_briefs"][0]["status"])
        raw["source_briefs"][0]["image_direction"] = current_image_direction()
        self.assertEqual("ready", compile_visual_design_kit_response(raw, source_manifest=[source])["source_briefs"][0]["status"])
        raw["source_briefs"][0]["image_direction"]["layout"] = "Use sage bedding and show 8 slats"
        self.assertEqual("pending", compile_visual_design_kit_response(raw, source_manifest=[source])["source_briefs"][0]["status"])
        raw["source_briefs"][0]["image_direction"] = current_image_direction()
        raw["source_briefs"][0]["image_direction"]["layout"][0]["source_region"] = [-.2, 0, 1, 1]
        self.assertEqual("pending", compile_visual_design_kit_response(raw, source_manifest=[source])["source_briefs"][0]["status"])
        source["role"] = "size"
        raw["source_briefs"][0]["image_direction"] = current_image_direction(environment="graphic_canvas")
        raw["source_briefs"][0]["image_direction"]["text_placement"] = [{"text_ref": "title", "target_region": [0, 0, 1, .1]}]
        size_brief = compile_visual_design_kit_response(raw, source_manifest=[source])["source_briefs"][0]
        self.assertEqual("ready", size_brief["status"])
        self.assertEqual([], size_brief["image_direction"]["text_placement"])
        self.assertFalse(size_brief["invent_text"])
        task = current_image_task("func")
        self.assertNotIn("role_purpose", task)
        task["image_direction"]["environment_mode"] = "graphic_canvas"
        compiled = compile_task_prompt(task=task)
        for old in ("Shopping purpose:", "Staging intent:", "Non-product object palette:"):
            self.assertNotIn(old, compiled)
        self.assertEqual(1, compiled.count("text_color = #303634"))
        self.assertEqual(1, compiled.count("Adjustable Shelf"))
        self.assertIn("without reconstructing unseen surfaces", compiled)

    def test_observed_size_facts_survive_projection_without_qa_false_failure(self):
        from core.final_source_intents import _observed_measurements, _measurement_rows
        from core.image_tasks import _measurement_authority, _measurement_role
        from core.visual_semantics import OBSERVATION_POLICY
        from core.image_qa import _semantic_gates
        from tests.test_qa_lite_v1 import _task, _observed
        visual = {"status": "success", "policy_version": OBSERVATION_POLICY, "visible_numbers_or_units": ['57"'],
                  "text_observations": [{"text": "Dimensions", "kind": "marketing"},
                                        {"text": "300 lbs", "kind": "measurement"}]}
        source = {"role": "size", "visual_evidence": visual,
                  "ocr_evidence": {"lines": [{"text": "300Ibs", "confidence": .93, "box": [0, 0, 1, 1]}]},
                  "measurements": _measurement_rows(_observed_measurements({}, visual), {})}
        authority = _measurement_authority("size", {}, source)
        self.assertEqual(2, len(authority["measurement_groups"]))
        self.assertIn("300 lbs", authority["source_visible_callouts"])
        self.assertIn("Dimensions", authority["source_visible_callouts"])
        self.assertEqual("300 lbs", authority["source_visible_text_artifacts"][0]["display_text"])
        self.assertEqual("weight", _measurement_role("Item Weight: 300 lbs"))
        self.assertEqual("mass_callout", _measurement_role("300 lbs"))
        self.assertEqual("load_capacity", _measurement_role("Weight Capacity: 300 lbs"))
        task = _task("size", "source_image")
        task["measurement_authority"] = authority
        obs = _observed(task)
        obs.update(texts=[{"text": text, "kind": "marketing", "confidence": .99} for text in ("Dimensions", "300 lbs")],
                   measurement_coverage="complete", measurements=[{
                       "measurement_id": row["id"], "candidate_text": row["render_text"], "source_text": row["source_text"],
                       "relationship": "same", "confidence": .99} for row in authority["measurement_groups"]])
        obs["measurements"].append({"measurement_id": None, "source_text": '4.5"', "candidate_text": '4.5"', "relationship": "same", "confidence": .99})
        self.assertEqual(["pass", "pass"], [r["status"] for r in _semantic_gates(task, obs)[:2]])
        obs["measurements"][-1]["candidate_text"] = '6"'
        self.assertEqual("fail", _semantic_gates(task, obs)[1]["status"])
        obs["texts"].append({"text": "Waterproof", "kind": "marketing", "confidence": .99})
        self.assertEqual("fail", _semantic_gates(task, obs)[0]["status"])

    def test_complete_single_word_claims_remain_bindable(self):
        source = {"claims": [{"evidence_id": str(i), "text": word}
                             for i, word in enumerate(("Pathway", "Wedding", "Q", "T o", "\ufffd"))]}
        self.assertEqual(["Pathway", "Wedding"], [row["text"] for row in cleaned_source_claims(source)])
        result = _compile_func_story(source, {"title": None, "labels": [
            {"text": "Pathway", "evidence_ids": ["0"]}, {"text": "Wedding", "evidence_ids": ["1"]}]})
        self.assertEqual(["Pathway", "Wedding"], result["labels"])

    def test_native_json_ignores_thoughts_and_keeps_failed_response_evidence(self):
        payload = {"candidates": [{"content": {"parts": [
            {"thought": True, "text": '{"draft": 1}'}, {"text": '{"sources": []}'}]}, "finishReason": "STOP"}]}
        body = json.dumps(payload)
        self.assertEqual(["STOP"], _response_finish_reasons(body))
        self.assertEqual(["length"], _response_finish_reasons('data: {"choices": [{"finish_reason": "length"}]}'))
        self.assertEqual(['{"sources": []}'], _parse_generate_content_candidates(body))
        self.assertEqual(['{"sources": []}'], _parse_sse_text_candidates("data: " + body))
        config = _gemini_native_payload([], {"protocol": "google_gemini", "max_output_tokens": "12000"})
        self.assertEqual("application/json", config["generationConfig"]["responseMimeType"])
        self.assertEqual(12000, config["generationConfig"]["maxOutputTokens"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attempts.json"
            _, record = _attempt_trace(path)
            record({"status": "validation_failure", "response_text": '{"sources": [',
                    "response_candidates": [{"validation_error": "incomplete object"}]})
            event = read_json(path)[0]
            self.assertEqual('{"sources": [', (path.parent / event["response_path"]).read_text())
            self.assertEqual(["incomplete object"], event["validation_errors"])

    def test_color_aid_varies_graphics_and_does_not_guess_unknown_names(self):
        from core.palette_registry import select_palette_route
        from core.visual_design_kit import _palette_planning_reference
        from core.plugin import load_plugin
        inks = set()
        for color in ("White", "Natural", "Blue", "Espresso"):
            route = select_palette_route(category_id="bed_frame", product_color=color, route_key="child-1")
            inks.add(route["recipe"]["graphic_ink"])
            self.assertGreaterEqual(route["metrics"]["graphic_text_contrast"], 4.5)
        self.assertGreater(len(inks), 1)
        aid = _palette_planning_reference(load_plugin("artificial_tree"), {"color": "Begonia"})
        self.assertEqual({}, aid["computed_starting_palette"])
        self.assertIn("unresolved_color_name", aid["color_basis"])
        self.assertNotIn("quality_metrics", aid)

    def test_incomplete_copy_shape_uses_complete_object_repair(self):
        from core.copy_writer import _is_non_json_copy_error, _only_title_validation_errors
        error = "Copy AI response must contain title, item_highlights, bullets, and description keys only"
        self.assertTrue(_is_non_json_copy_error(error))
        self.assertFalse(_only_title_validation_errors(error))
        self.assertTrue(_only_title_validation_errors("title exceeds 70 characters"))


if __name__ == "__main__":
    unittest.main()
