from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.io import read_json
from tests.current_image_contract_fixture import current_physical_view
from core.visual_semantics import _attempt_trace
from core.visual_design_kit_compiler import cleaned_source_claims, _compile_display_copy
from core.vision_gemini_client import (
    _gemini_native_payload, _parse_sse_text_candidates, _parse_generate_content_candidates,
    _response_finish_reasons,
)


class VisualDesignRemediationTests(unittest.TestCase):
    def test_observed_bounds_preserve_pixels_and_feature_extent(self):
        from PIL import Image, ImageChops
        from core.io import file_sha256
        from core.image_reference_context import prepare_planning_views, planning_view_inputs, physical_views
        from core.final_source_intents import _semantic_revision
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            with Image.new("RGB", (200, 120), "magenta") as poster:
                poster.paste((180, 140, 80), (20, 30, 80, 60))
                poster.paste((20, 180, 90), (120, 75, 180, 105))
                poster.save(job / "source.png")
            views = [current_physical_view('upper', [.1, .25, .4, .5], feature='slats'),
                     current_physical_view('lower', [.6, .625, .9, .875], feature='edge_joint')]
            source = {"source_id": "source_02", "source_path": "source.png",
                      "source_sha256": file_sha256(job / "source.png"), "observation": {"physical_views": views}}
            paths = prepare_planning_views(job, [source], job / "trace")
            self.assertEqual([{"attachment_number": i + 1, "source_id": "source_02", 'view_id': view['view_id']}
                              for i, view in enumerate(views)], planning_view_inputs([source]))
            with Image.open(job / "source.png") as original:
                for path, box in zip(paths, ((20, 30, 80, 60), (120, 75, 180, 105))):
                    with Image.open(path) as crop, original.crop(box) as expected:
                        self.assertIsNone(ImageChops.difference(crop, expected).getbbox())
                        self.assertNotIn((255, 0, 255), set(crop.getdata()))
            self.assertEqual(source["source_sha256"], file_sha256(job / "source.png"))
            from core.image_reference_context import view_reference, measurement_attachment_location
            from core.visual_semantics import _validate_source_measurements
            from tests.current_image_contract_fixture import current_observed_measurement
            badge = {**current_observed_measurement('300 lbs', kind='capacity'), 'view_id': 'upper',
                     'region': dict(left=.125, top=.0625, right=.375, bottom=.1875)}
            _validate_source_measurements([badge], views)
            located = {'source_id': 'source_02', 'view_id': 'upper', 'source_region': badge['region'], 'source_endpoints': None}
            source['measurements'] = [located]
            prepare_planning_views(job, [source], job / 'with_badge')
            ref = view_reference(source, views[0], job=job, child='B1', kind='edit_base')
            self.assertEqual(dict(left=.1, top=7/120, right=.4, bottom=.5), ref['original_region'])
            with Image.open(job / ref['path']) as crop:
                self.assertEqual((60, 53), crop.size)
            projected = measurement_attachment_location(located, [ref])
            self.assertEqual(1, projected['attachment'])
            self.assertAlmostEqual(5/60, projected['label']['left'])
            self.assertAlmostEqual(.5/53, projected['label']['top'])
            self.assertIsNone(projected['endpoints'])
            located['source_endpoints'] = [dict(x=.1, y=.25), dict(x=.4, y=.5)]
            projected = measurement_attachment_location(located, [ref])
            self.assertEqual(dict(x=1.0, y=1.0), projected['endpoints'][1])
            source.pop('measurements')
            narrow = current_physical_view('drawer', [.29, .457, .299, .838], feature='drawer')
            narrow['evidence'][0]['region'] = dict(left=.04, top=.457, right=.299, bottom=.838)
            with self.assertRaisesRegex(ValueError, 'truncates observed feature'):
                physical_views([narrow])
            before = _semantic_revision({"visual_evidence": {"physical_views": views}})
            views[0]["region"]['left'] = .09
            self.assertNotEqual(before, _semantic_revision({"visual_evidence": {"physical_views": views}}))
            for invalid in (None, [{"view_id": "x", "region": [0, 0, float('nan'), 1]}], [views[0], views[0]]):
                with self.assertRaises(ValueError):
                    physical_views(invalid)
            from core.visual_design_kit_compiler import compile_visual_design_kit_response, design_binding_request
            from tests.current_image_contract_fixture import current_art_direction, current_image_direction
            from core.visual_semantics import CLAIM_REVIEW_POLICY
            cropped = {**source, 'role': 'scene', 'input_revision_id': 'crop',
                       'observation': {'physical_views': [current_physical_view(region=[.201, .237, .985, .708])]},
                       'crop_provenance': [{'view_id': 'view_01', 'pixel_size': [784, 471]}]}
            draft = {'source_id': cropped['source_id'], 'image_direction': current_image_direction()}
            raw = {'family_art_direction': current_art_direction(), 'source_briefs': [draft]}
            request = design_binding_request(draft, raw['family_art_direction'], source=cropped)
            self.assertEqual(['view_fidelity:view_01'], request['physical_operations'])
            self.assertEqual('pending', compile_visual_design_kit_response(raw, source_manifest=[cropped])['source_briefs'][0]['status'])
            review = {'key': request['key'], 'policy': CLAIM_REVIEW_POLICY, 'response_sha256': 'b' * 64,
                      'status': 'supported', 'findings': [{'kind': 'physical_structure', 'operation': 'view_fidelity:view_01',
                          'status': 'contradiction', 'reason': 'Actual crop cuts the cabinet feet visible in original'}]}
            blocked = compile_visual_design_kit_response(raw, source_manifest=[cropped], claim_reviews={request['key']: review})
            self.assertIn('cuts the cabinet feet', blocked['source_briefs'][0]['error'])
            self.assertEqual('observation', blocked['source_briefs'][0]['failure_owner'])
            import time
            from core.visual_design_kit import _finish_source_briefs, _planner_source_view
            with patch('core.visual_design_kit.review_planning_bindings', return_value={request['key']: review}), patch('core.visual_design_kit.gemini_stream_generate') as repair:
                result = _finish_source_briefs(raw, source_manifest=[cropped], category_id='bed_frame',
                    source_paths=[], source_originals=[], trace_dir=job, deadline_monotonic=time.monotonic()+10, cached=None)
                self.assertEqual('observation', result['source_briefs'][0]['failure_owner'])
                repair.assert_not_called()
            # Full-size fixtures do not acquire a second mandatory aesthetic approval.
            cropped['crop_provenance'] = []
            cropped['observation']['objects'] = [{'object_id': 'pillow', 'sale_membership': 'staging', 'visibility': 'visible',
                                                 'kind': 'pillow', 'state': 'one pillow partially covering the frame',
                                                 'relations': [{'predicate': 'occludes', 'target_id': 'frame'}]}]
            self.assertEqual(cropped['observation']['objects'], _planner_source_view(cropped)['objects'])
            missing = compile_visual_design_kit_response(raw, source_manifest=[cropped])
            self.assertIn('pillow', missing['source_briefs'][0]['error'])
            draft['image_direction']['scene_objects']['pillow'] = 'towels'
            self.assertEqual('ready', compile_visual_design_kit_response(raw, source_manifest=[cropped])['source_briefs'][0]['status'])
            source["observation"]["physical_views"] = []
            with self.assertRaisesRegex(ValueError, "no observed physical views"):
                prepare_planning_views(job, [source], job / "empty")
            source["observation"]["physical_views"] = views
            source["source_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "source changed"):
                prepare_planning_views(job, [source], job / "changed")

    def test_local_repair_keeps_view_inventory_and_rejects_uncovered_feature_ids(self):
        import time
        from core.visual_design_kit import _finish_source_briefs
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction
        views = [current_physical_view('view_01', [.1, .1, .4, .4], feature='slats'),
                 current_physical_view('view_02', [.6, .6, .9, .9], feature='edge_joint')]
        source = {"source_id": "source_00", "role": "size", "source_sha256": "a" * 64,
                  "input_revision_id": "r", "measurements": [], "observation": {"physical_views": views}}
        direction = current_image_direction(environment="graphic_canvas")
        direction["layout"].append({"view_id": "view_02", "target_region": [.1, .6, .5, .9]})
        direction["evidence_usage"].append({"view_id": "view_02", "usage": "display", "covered_by": []})
        direction["visual_goal"] = ""
        raw = {"family_art_direction": current_art_direction(), "source_briefs": [{
            "source_id": "source_00", "image_direction": direction, "display_copy": {"title": None, "labels": []}}]}
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp)
            paths = [trace / "view_001.png", trace / "view_002.png"]
            def repair(prompt, attachments, **kwargs):
                self.assertEqual(paths, attachments)
                self.assertNotIn('total_timeout_seconds', kwargs)
                self.assertEqual(1, kwargs['max_physical_requests'])
                self.assertGreater(kwargs['deadline_monotonic'], time.monotonic())
                self.assertIn('"attachment_number": 2', prompt)
                self.assertIn('"view_id": "view_02"', prompt)
                self.assertIn('"feature_id": "edge_joint"', prompt)
                return json.dumps({"source_briefs": [{**raw["source_briefs"][0],
                    "image_direction": {**direction, "visual_goal": "Show both measured views clearly."}}]})
            with patch("core.visual_design_kit.review_planning_bindings", return_value={}), patch(
                "core.visual_design_kit.gemini_stream_generate", side_effect=repair) as call:
                result = _finish_source_briefs(raw, source_manifest=[source], category_id="bed_frame",
                    source_paths=paths, source_originals=[], trace_dir=trace, deadline_monotonic=time.monotonic() + 10, cached=None)
            self.assertEqual(1, call.call_count)
            self.assertEqual("ready", result["source_briefs"][0]["status"])
        direction["visual_goal"] = "Show both measured views clearly."
        direction["layout"].pop()
        direction["evidence_usage"][1].update(usage="integrated", covered_by=["view_01"])
        denied = compile_visual_design_kit_response(raw, source_manifest=[source])["source_briefs"][0]
        self.assertIn('unique physical evidence is not covered', denied['error'])
        views[0]['evidence'].append({**views[1]['evidence'][0], 'region': views[0]['region'].copy()})
        self.assertEqual("pending", compile_visual_design_kit_response(raw, source_manifest=[source])["source_briefs"][0]["status"])
        from core.visual_design_kit_compiler import design_binding_request
        from core.visual_semantics import CLAIM_REVIEW_POLICY
        request = design_binding_request(raw['source_briefs'][0], raw['family_art_direction'], source=source)
        verdict = {'key': request['key'], 'policy': CLAIM_REVIEW_POLICY, 'response_sha256': 'c' * 64,
                   'status': 'inconclusive', 'reason': 'Cannot verify merged corner', 'findings': []}
        self.assertEqual('pending', compile_visual_design_kit_response(raw, source_manifest=[source],
            claim_reviews={request['key']: verdict})['source_briefs'][0]['status'])
        verdict.update(status='supported', findings=[{'kind': 'physical_structure', 'operation': 'coverage_transfer:view_02',
                       'status': 'supported', 'reason': 'Reviewer compared both actual corner views'}])
        self.assertEqual('ready', compile_visual_design_kit_response(raw, source_manifest=[source],
            claim_reviews={request['key']: verdict})['source_briefs'][0]['status'])
        support = {**source, 'source_id': 'source_01', 'source_sha256': 'b' * 64}
        draft_with_support = {**raw['source_briefs'][0], 'supporting_sources': [
            {'source_id': 'source_01', 'view_id': 'view_01', 'purpose': 'Verify corner', 'evidence_ids': []}]}
        before = design_binding_request(draft_with_support, raw['family_art_direction'], source=source, source_manifest=[source, support])
        draft_with_support['supporting_sources'][0]['view_id'] = 'view_02'
        after = design_binding_request(draft_with_support, raw['family_art_direction'], source=source, source_manifest=[source, support])
        self.assertNotEqual(before['key'], after['key'])
        direction["evidence_usage"].pop()
        rejected = compile_visual_design_kit_response(raw, source_manifest=[source])
        self.assertIn("Every observed view", rejected["source_briefs"][0]["error"])

        from core.visual_semantics import CLAIM_REVIEW_POLICY
        from core.visual_design_kit_compiler import design_binding_request
        from copy import deepcopy
        source = {"source_id": "source_00", "role": "func", "source_sha256": "a" * 64,
                  "input_revision_id": "r", "measurements": [], "claims": [{"evidence_id": "drawer", "text": "Drawers on wheels"}],
                  "observation": {"physical_views": [views[0]]}}
        draft = {"source_id": "source_00", "image_direction": current_image_direction(),
                 "display_copy": {"title": None, "labels": [
                     {"text": "Drawers stay aligned", "evidence_ids": ["drawer"]},
                     {"text": "Effortless pull-out", "evidence_ids": ["drawer"]}]}}
        raw = {"family_art_direction": current_art_direction(), "source_briefs": [draft]}
        raw["source_briefs"][0]["image_direction"]["creative_brief"] = "Place sage green towels beside the intact product."
        def review(requests, **kwargs):
            return {row["key"]: {"key": row["key"], "policy": CLAIM_REVIEW_POLICY, "response_sha256": "b" * 64,
                "status": "contradiction" if row["kind"] == "design_binding" else "inconclusive",
                "reason": "towels conflicts with shared palette" if row["kind"] == "design_binding" else row["proposed_text"],
                'findings': [{'kind': 'design_binding', 'operation': 'target:towels', 'status': 'contradiction',
                              'reason': 'towels conflicts with shared palette'}] if row['kind'] == 'design_binding' else []}
                for row in requests}
        def repair_all(prompt, attachments, **kwargs):
            for detail in ("Drawers stay aligned", "Effortless pull-out", "towels conflicts with shared palette"):
                self.assertIn(detail, prompt)
            repaired = deepcopy(draft)
            repaired["image_direction"]["creative_brief"] = current_image_direction()["creative_brief"]
            repaired["display_copy"]["labels"] = [{"text": "Drawers on wheels", "evidence_ids": ["drawer"]}]
            return json.dumps({"source_briefs": [repaired], "shared_prose": {
                "environment_and_staging": "Place the shared towels beside the product with clear access."}})
        calls = []
        def review_once(requests, **kwargs):
            calls.append(requests)
            if len(calls) == 1:
                return review(requests, **kwargs)
            return {row["key"]: {"key": row["key"], "policy": CLAIM_REVIEW_POLICY,
                "response_sha256": "c" * 64, "status": "supported", "reason": "Shared role reused"} for row in requests}
        with tempfile.TemporaryDirectory() as tmp, patch("core.visual_design_kit.review_planning_bindings", side_effect=review_once), patch(
                "core.visual_design_kit.gemini_stream_generate", side_effect=repair_all) as repair_call:
            result = _finish_source_briefs(raw, source_manifest=[source], category_id="bed_frame", source_paths=[], source_originals=[],
                trace_dir=Path(tmp), deadline_monotonic=time.monotonic() + 10, cached=None)
        self.assertEqual(1, repair_call.call_count)
        self.assertEqual("ready", result["source_briefs"][0]["status"])
        self.assertEqual(["Drawers on wheels"], result["source_briefs"][0]["display_copy_contract"]["labels"])
        self.assertEqual(raw["family_art_direction"]["palette_direction"], result["family_art_direction"]["palette_direction"])
        self.assertEqual(raw["family_art_direction"]["graphic_direction"], result["family_art_direction"]["graphic_direction"])
        self.assertEqual(3, len(calls[0]))
        self.assertEqual(1, len(calls[1]))
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=TimeoutError('review clock')):
            unavailable = _finish_source_briefs(raw, source_manifest=[source], category_id='bed_frame', source_paths=[], source_originals=[],
                trace_dir=Path(tmp), deadline_monotonic=time.monotonic() + 10, cached=None)
        self.assertIn('Planning review unavailable: TimeoutError', unavailable['source_briefs'][0]['error'])
        exact = deepcopy(draft)
        exact["display_copy"]["labels"] = [{"text": "Drawers on wheels", "evidence_ids": ["drawer"]}]
        request = design_binding_request(exact, raw["family_art_direction"], source=source)
        conflict = review([request])
        checked = compile_visual_design_kit_response({**raw, "source_briefs": [exact]}, source_manifest=[source], claim_reviews=conflict)
        self.assertIn("planning evidence conflict", checked["source_briefs"][0]["error"])
        conflict[request["key"]]["status"] = "inconclusive"
        conflict[request['key']]['findings'] = []
        checked = compile_visual_design_kit_response({**raw, "source_briefs": [exact]}, source_manifest=[source], claim_reviews=conflict)
        self.assertEqual("ready", checked["source_briefs"][0]["status"])

    def test_independent_canvas_uses_one_design_contract_without_source_style(self):
        from core.visual_design_kit import visual_design_kit_prompt
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        from core.image_prompt_compiler import compile_task_prompt
        from core.plugin import load_plugin
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction, current_image_task
        source = {"source_id": "source_00", "source_index": 0, "role": "main", "input_revision_id": "r",
                  "source_sha256": "a" * 64, "shopping_intent": "OLD_PURPOSE", "claims": [], "measurements": [],
                  "observation": {"objects": [], "physical_views": [current_physical_view()], "layout_summary": "OLD_CAPSULE_LAYOUT",
                                  "text_observations": [{"kind": "prop", "text": "OLD_PROP_WORDS"}]}}
        prompt = visual_design_kit_prompt(load_plugin("bed_frame"), {}, {}, [source])
        for old in ("OLD_PURPOSE", "OLD_CAPSULE_LAYOUT", "OLD_PROP_WORDS"):
            self.assertNotIn(old, prompt)
        raw = {"family_art_direction": current_art_direction(), "source_briefs": [{
            "source_id": "source_00", "image_direction": "obsolete unconstrained string"}]}
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
        source['claims'] = [{'evidence_id': 'heading', 'text': 'Product Dimensions'}]
        raw['source_briefs'][0]['display_copy'] = {'title': {'evidence_ids': ['heading'], 'text': 'Product Dimensions'}, 'labels': []}
        raw["source_briefs"][0]["image_direction"] = current_image_direction(environment="graphic_canvas")
        raw["source_briefs"][0]["image_direction"]["text_placement"] = [{"text_ref": "title", "target_region": [0, 0, 1, .1]}]
        size_brief = compile_visual_design_kit_response(raw, source_manifest=[source])["source_briefs"][0]
        self.assertEqual("ready", size_brief["status"])
        self.assertEqual('title', size_brief['image_direction']['text_placement'][0]['text_ref'])
        self.assertEqual('Product Dimensions', size_brief['display_copy_contract']['title'])
        task = current_image_task("func")
        self.assertNotIn("role_purpose", task)
        task["image_direction"]["environment_mode"] = "graphic_canvas"
        compiled = compile_task_prompt(task=task)
        self.assertIn('towels = #8A999E', compiled)
        task['product_boundary']['observed_objects'] = [{'object_id': 'towel', 'relations': [{'predicate': 'contained_in', 'target_id': 'drawer_1'}]}]
        before = compile_task_prompt(task=task)
        task['product_boundary']['observed_objects'][0]['relations'][0]['target_id'] = 'drawer_2'
        self.assertNotEqual(before, compile_task_prompt(task=task))
        for old in ("Shopping purpose:", "Staging intent:"):
            self.assertNotIn(old, compiled)
        self.assertEqual(1, compiled.count("text_color = #303634"))
        self.assertEqual(1, compiled.count("Adjustable Shelf"))
        task["product_boundary"]["observed_objects"] = [
            {"object_id": "frame", "kind": "bed frame", "state": "four visible legs", "sale_membership": "product", "visibility": "visible", "relations": []},
            {"object_id": "quilt", "kind": "quilt", "state": "SOURCE_SAGE_PRINT", "sale_membership": "staging", "visibility": "visible",
             "relations": [{"predicate": "occludes", "target_id": "frame"}]},
            {"object_id": "book", "kind": "book", "state": "SOURCE_BRAND_STYLE", "sale_membership": "staging", "visibility": "visible", "relations": []}]
        task['generation_references'][0]['visible_evidence'] = [dict(current_physical_view()['evidence'][0], physical_facts=['Platform frame without headboard'])]
        projected = compile_task_prompt(task=task)
        self.assertNotIn("SOURCE_SAGE_PRINT", projected)
        self.assertNotIn("SOURCE_BRAND_STYLE", projected)
        self.assertIn("four visible legs", projected)
        self.assertEqual(1, projected.count('Platform frame without headboard'))
        self.assertNotIn("cyan dashed outline", projected)
        self.assertIn("occludes", projected)
        from copy import deepcopy
        support = deepcopy(task['generation_references'][0])
        support.update(kind='product_evidence', source_id='source_99')
        support['visible_evidence'][0]['physical_facts'] = ['OTHER_VIEW_STATE']
        task['generation_references'].append(support)
        scoped = compile_task_prompt(task=task)
        self.assertIn('Platform frame without headboard', scoped)
        self.assertNotIn('OTHER_VIEW_STATE', scoped)

    def test_observed_size_facts_survive_projection_without_qa_false_failure(self):
        from core.final_source_intents import _observed_measurements, _measurement_rows
        from core.image_tasks import _measurement_authority
        from core.visual_semantics import OBSERVATION_POLICY
        from core.image_qa import _semantic_gates
        from tests.test_qa_lite_v1 import _task, _observed
        from tests.current_image_contract_fixture import current_observed_measurement
        visual = {"status": "success", "policy_version": OBSERVATION_POLICY, "visible_numbers_or_units": ['57"'],
                  'measurements': [current_observed_measurement(), current_observed_measurement('300 lbs', 'Bed capacity', 'capacity', key='load', kind='capacity')],
                  "text_observations": [{"text": "Dimensions", "kind": "marketing"},
                                        {"text": "300 lbs", "kind": "measurement"}]}
        source = {"role": "size", "visual_evidence": visual,
                  "ocr_evidence": {"lines": [{"text": "17'", "confidence": .93, "box": [0, 0, 1, 1]}]},
                  "measurements": _measurement_rows(_observed_measurements(visual), {})}
        authority = _measurement_authority("size", {}, source)
        self.assertEqual(2, len(authority["measurement_groups"]))
        self.assertEqual(['17 in', '300 lb'], authority['render_text'])
        self.assertEqual('load_capacity', authority['measurement_groups'][1]['measurement_role'])
        self.assertNotIn('source_visible_callouts', authority)
        values = _observed_measurements(visual)
        self.assertEqual(2, len(values))
        self.assertNotIn('17 ft', [r['text'] for r in values])
        from core.visual_semantics import _validate_source_measurements, _validate_candidate_observation
        from copy import deepcopy
        repeated = deepcopy(visual['measurements'])
        repeated[1] = {**repeated[0], 'measurement_id': 'ocr-read', 'text': '17 ft'}
        with self.assertRaisesRegex(ValueError, 'competing readings'):
            _validate_source_measurements(repeated, [current_physical_view()])
        task = _task("size", "source_image")
        task['renderable_text_contract'] = {'mode': 'exact', 'strings': ['Dimensions']}
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
        located = _observed(task)
        located['measurement_coverage'] = 'complete'
        located['measurements'] = [{'measurement_id': 'width', 'object': 'cabinet width', 'source_id': 'source_00',
            'attachment_index': 2, 'source_text': '17 in', 'candidate_text': '13.5 in', 'relationship': 'different',
            'confidence': .99, 'source_region': dict(left=.1, top=.1, right=.2, bottom=.2), 'candidate_region': dict(left=.2, top=.2, right=.3, bottom=.3)},
            {'measurement_id': 'ghost', 'object': 'unlocatable OCR', 'source_id': 'source_00', 'attachment_index': 2,
             'source_text': '17 ft', 'candidate_text': '17 in', 'relationship': 'different', 'confidence': .99,
             'source_region': dict(left=0, top=0, right=0, bottom=0), 'candidate_region': dict(left=.2, top=.2, right=.3, bottom=.3)}]
        _validate_candidate_observation(located)
        self.assertEqual('unknown', located['measurements'][1]['relationship'])
        self.assertEqual('fail', _semantic_gates(task, located)[1]['status'])
        located['measurements'].pop(0)
        self.assertEqual('inconclusive', _semantic_gates(task, located)[1]['status'])

    def test_complete_single_word_claims_remain_bindable(self):
        source = {"source_id": "source_00", "claims": [{"evidence_id": str(i), "text": word}
                             for i, word in enumerate(("Pathway", "Wedding", "Q", "T o", "\ufffd"))]}
        self.assertEqual(["Pathway", "Wedding"], [row["text"] for row in cleaned_source_claims(source)])
        result = _compile_display_copy(source, {"title": None, "labels": [
            {"text": "Pathway", "evidence_ids": ["0"]}, {"text": "Wedding", "evidence_ids": ["1"]}]})
        self.assertEqual(["Pathway", "Wedding"], result["labels"])
        from core.visual_design_kit_compiler import claim_review_requests
        from core.visual_semantics import CLAIM_REVIEW_POLICY
        source.update(role='func', observation={'physical_views': [current_physical_view()]})
        physical_id = 'physical:source_00:view_01:frame_support:0'
        copy = {'title': None, 'labels': [{'text': 'Visible frame support and its joints', 'evidence_ids': [physical_id]}]}
        requests = claim_review_requests({'source_briefs': [{'source_id': 'source_00', 'display_copy': copy}]}, [source])
        self.assertEqual(1, len(requests))  # Visual descriptions never bypass independent claim verification.
        self.assertEqual({physical_id: copy['labels'][0]['text']}, requests[0]['evidence'])
        with self.assertRaisesRegex(ValueError, 'independent evidence review'):
            _compile_display_copy(source, copy)
        reviewed = {requests[0]['key']: {'key': requests[0]['key'], 'status': 'supported',
                                       'policy': CLAIM_REVIEW_POLICY, 'response_sha256': 'a' * 64}}
        self.assertEqual([copy['labels'][0]['text']], _compile_display_copy(source, copy, claim_reviews=reviewed)['labels'])
        import time
        from core.visual_semantics import review_planning_bindings
        from tests.current_image_contract_fixture import current_art_direction
        deadline = time.monotonic() + 80
        response = json.dumps({'reviews': [{'key': requests[0]['key'], 'status': 'supported', 'reason': 'Visible local structure',
            'findings': [{'kind': 'copy_fact', 'operation': 'source_00', 'status': 'supported', 'reason': 'Visible frame joints'}]}]})
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_semantics.gemini_stream_generate', return_value=response) as remote:
            review_planning_bindings(requests, trace_dir=Path(tmp), shared_design=current_art_direction(), deadline_monotonic=deadline)
        self.assertEqual(deadline, remote.call_args.kwargs['deadline_monotonic'])
        self.assertEqual(1, remote.call_args.kwargs['max_physical_requests'])
        self.assertNotIn('total_timeout_seconds', remote.call_args.kwargs)

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

    def test_color_tools_measure_gemini_choices_without_selecting_or_mutating(self):
        from copy import deepcopy
        from core.palette_registry import planned_palette_diagnostics
        from tests.current_image_contract_fixture import current_art_direction
        direction = current_art_direction()
        before = deepcopy(direction)
        report = planned_palette_diagnostics(direction)
        self.assertEqual(before, direction)
        self.assertIn("palette_direction.wall", report["colors"])
        self.assertTrue(report["pairs"])
        self.assertEqual("diagnostics_only_no_design_or_qa_decision", report["authority"])
        self.assertNotIn("score", report)
        direction["graphic_direction"]["text_color"] = "#FFFFFF"
        self.assertNotEqual(report, planned_palette_diagnostics(direction))
        direction["graphic_direction"]["backing_color"] = "#FFFFFF80"
        transparent = planned_palette_diagnostics(direction)
        self.assertAlmostEqual(128 / 255, transparent["colors"]["graphic_direction.backing_color"]["alpha"])
        pairs = [row for row in transparent["pairs"] if row["second"] == "graphic_direction.backing_color"]
        self.assertTrue(pairs)
        self.assertTrue(all(row["underlay"] for row in pairs))
        self.assertTrue(all(row["first"].startswith("graphic_direction.") for row in transparent["pairs"]))

    def test_incomplete_copy_shape_uses_complete_object_repair(self):
        from core.copy_writer import _is_non_json_copy_error, _only_title_validation_errors
        error = "Copy AI response must contain title, item_highlights, bullets, and description keys only"
        self.assertTrue(_is_non_json_copy_error(error))
        self.assertFalse(_only_title_validation_errors(error))
        self.assertTrue(_only_title_validation_errors("title exceeds 70 characters"))

    def test_approved_reference_import_reaches_planner_and_only_selected_role(self):
        from copy import deepcopy
        from PIL import Image
        from core.io import write_json, file_sha256
        from core.job import create_job, load_job
        from core.plugin import load_plugin
        from core.design_reference_library import approved_design_references, brand_design_brief, design_reference_usage
        from core.visual_design_kit import visual_design_kit_prompt
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        from core.image_tasks import _generation_references_for_task
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction, current_image_task
        from core.image_prompt_compiler import compile_task_prompt
        plugin = load_plugin("bed_frame")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with Image.new("RGB", (32, 32), "magenta") as image:
                image.paste((255, 255, 255), (8, 8, 24, 24))
                image.save(root / "owned-fixture.png")
            approval = {"status": "approved", "approved_by": "test-fixture-only", "approved_at": "2026-09-11",
                        "allowed_uses": ["image_generation_reference"], "license_evidence": "Test-generated pixels"}
            visual = {**approval, "product_clarity": "Test-only clear product field", "information_hierarchy": "Test-only hierarchy",
                      "evidence_fit": "No unseen product parts required", "series_cohesion": "Test-only shared typography",
                      "transfer_scope": "Reviewed central blank area; excluded magenta frame stands for unrelated reference product"}
            asset = {"asset_id": "owned-layout", "roles": ["func"], "children": ["B1"],
                     "local_path": "owned-fixture.png", "sha256": file_sha256(root / "owned-fixture.png"),
                     "author": "test", "source_url": "local-test-fixture", "asset_license": "test-owned",
                     "rights_review": approval, "visual_review": visual,
                     "reference_region": [.25, .25, .75, .75],
                     "purpose": "Asymmetric hierarchy and generous breathing room"}
            pack = {"schema_version": "design-pack-v4", "pack_id": "fixture", "version": "1", 'approval_scope': 'production',
                    "status": "approved", "production_ready": True,
                    "design_system": "Test-only light photography and editorial information hierarchy",
                    "compatibility": {"categories": ["bed_frame"]}, "assets": [asset]}
            write_json(root / "pack.json", pack)
            write_json(root / "brief.json", {"positioning": "quiet modern residential"})
            kwargs = dict(plugin=plugin, seed_asin="B1", brand="safeplus", sku_prefix="test", out_root=root / "jobs")
            empty = create_job(**kwargs)
            self.assertEqual([], approved_design_references(empty, "B1"))
            job = create_job(**kwargs, design_pack_path=str(root / "pack.json"), brand_brief_path=str(root / "brief.json"))
            self.assertEqual("safeplus", load_job(job)["brand"])
            refs = approved_design_references(job, "B1")
            self.assertEqual([], approved_design_references(job, "B2"))
            self.assertEqual(asset["sha256"], refs[0]["original_sha256"])
            self.assertNotEqual(asset["sha256"], file_sha256(job / refs[0]["path"]))
            with Image.open(job / refs[0]["path"]) as image:
                self.assertEqual((16, 16), image.size)
                self.assertEqual({(255, 255, 255)}, set(image.getdata()))
            source = {"source_id": "source_00", "source_index": 0, "role": "func", "source_path": "source.png",
                      "source_sha256": "a" * 64, "input_revision_id": "r", "claims": [], "measurements": [],
                      "observation": {"objects": [], "physical_views": [current_physical_view(region=[0, 0, 1, 1])]}}
            from core.image_reference_context import prepare_planning_views
            Image.new('RGB', (100, 100), 'white').save(job / 'source.png')
            source['source_sha256'] = file_sha256(job / 'source.png')
            prepare_planning_views(job, [source], job / 'trace')
            prompt = visual_design_kit_prompt(plugin, {}, {}, [source], refs, brand_design_brief(job))
            self.assertIn("quiet modern residential", prompt)
            self.assertIn('"attachment_number": 2', prompt)
            self.assertNotIn("license_evidence", prompt)
            direction = current_image_direction()
            direction["design_transfer"] = [{"reference_id": asset["asset_id"],
                "inherit": "Keep the reference detail-to-product hierarchy with shared typography",
                "adapt": "Use the available frontal view for this product instead of an unseen angle"}]
            raw = {"family_art_direction": current_art_direction(), "source_briefs": [{
                "source_id": "source_00", "image_direction": direction,
                "display_copy": {"title": None, "labels": []}}]}
            compiled = compile_visual_design_kit_response(raw, source_manifest=[source], design_references=refs)
            brief = compiled["source_briefs"][0]
            self.assertEqual("ready", brief["status"])
            from core.visual_design_kit_compiler import design_binding_request, validate_compiled_visual_design_kit
            from core.visual_semantics import CLAIM_REVIEW_POLICY
            request = design_binding_request(raw['source_briefs'][0], compiled['family_art_direction'], source=source, design_references=refs)
            self.assertEqual(refs[0]['purpose'], request['reference_scopes'][0]['purpose'])
            self.assertEqual(refs[0]['visual_review']['transfer_scope'], request['reference_scopes'][0]['approval_boundary'])
            brief['design_review'] = {'key': request['key'], 'policy': CLAIM_REVIEW_POLICY, 'status': 'supported', 'response_sha256': 'a' * 64}
            changed_refs = deepcopy(refs)
            changed_refs[0]['purpose'] = 'Lighting only; no typography transfer'
            with self.assertRaisesRegex(ValueError, 'no longer matches'):
                validate_compiled_visual_design_kit(compiled, source_manifest=[source], design_references=changed_refs)
            validate_compiled_visual_design_kit(compiled, source_manifest=[source], design_references=refs)
            changed_refs = deepcopy(refs)
            changed_refs[0]['visual_review']['transfer_scope'] = 'Color only'
            with self.assertRaisesRegex(ValueError, 'no longer matches'):
                validate_compiled_visual_design_kit(compiled, source_manifest=[source], design_references=changed_refs)
            generation = _generation_references_for_task(source, brief, {"source_references": [source], "approved_design_references": refs}, job=job, child="B1")
            self.assertEqual(["edit_base", "design_reference"], [row["kind"] for row in generation])
            task = current_image_task("func")
            task["image_direction"]["design_transfer"] = deepcopy(direction["design_transfer"])
            task["generation_references"] = generation
            compiled_prompt = compile_task_prompt(task=task)
            self.assertEqual(1, compiled_prompt.count(direction["design_transfer"][0]["inherit"]))
            self.assertEqual(1, compiled_prompt.count(direction["design_transfer"][0]["adapt"]))
            self.assertIn(asset["purpose"], compiled_prompt)
            self.assertIn(asset['visual_review']['transfer_scope'], compiled_prompt)
            self.assertIn(task["display_copy_contract"]["title"], compiled_prompt)
            alternate = deepcopy(task)
            alternate["image_direction"]["design_transfer"][0]["inherit"] = "Keep reference contrast between the intact product and quiet margin"
            alternate_prompt = compile_task_prompt(task=alternate)
            self.assertNotEqual(compiled_prompt, alternate_prompt)
            self.assertEqual(task["product_boundary"], alternate["product_boundary"])
            self.assertEqual(task["family_art_direction"], alternate["family_art_direction"])
            self.assertEqual(task["renderable_text_contract"], alternate["renderable_text_contract"])
            repaired = compile_task_prompt(task=task, targeted_edit=True)
            self.assertIn(asset['purpose'], repaired)
            self.assertNotIn(direction["design_transfer"][0]["adapt"], repaired)
            self.assertIn("Style verification only", repaired)
            task["generation_references"] = generation[:1]
            with self.assertRaisesRegex(ValueError, "do not match"):
                compile_task_prompt(task=task)
            usage = design_reference_usage(job, refs, [brief])
            self.assertEqual("external_reference_selected", usage["roles"][0]["status"])
            self.assertEqual("not_evaluated", usage["visual_acceptance"])
            autonomous = {**brief, "image_direction": {**brief["image_direction"], "design_transfer": []}}
            self.assertEqual("available_not_selected", design_reference_usage(job, refs, [autonomous])["roles"][0]["status"])
            self.assertEqual("requested_no_matching_reference", design_reference_usage(job, [], [autonomous])["roles"][0]["status"])
            self.assertEqual("autonomous_no_external_standard", design_reference_usage(empty, [], [autonomous])["roles"][0]["status"])
            broken = deepcopy(raw)
            broken["source_briefs"][0]["image_direction"]["design_transfer"][0]["inherit"] = "Use #123456 for all titles"
            self.assertEqual("pending", compile_visual_design_kit_response(broken, source_manifest=[source], design_references=refs)["source_briefs"][0]["status"])
            broken["source_briefs"][0]["image_direction"]["design_transfer"][0]["inherit"] = "Add drawers to the product"
            self.assertEqual("pending", compile_visual_design_kit_response(broken, source_manifest=[source], design_references=refs)["source_briefs"][0]["status"])
            source["role"] = "scene"
            self.assertEqual("pending", compile_visual_design_kit_response(raw, source_manifest=[source], design_references=refs)["source_briefs"][0]["status"])
            direction["design_transfer"] = []
            self.assertEqual("ready", compile_visual_design_kit_response(raw, source_manifest=[source], design_references=refs)["source_briefs"][0]["status"])
            for changed in ({"production_ready": False}, {"compatibility": {"categories": ["artificial_tree"]}}, {"schema_version": "design-pack-v2"}):
                write_json(root / "pack.json", {**pack, **changed})
                with self.assertRaises(ValueError):
                    create_job(**kwargs, design_pack_path=str(root / "pack.json"))
            write_json(root / "pack.json", {**pack, "compatibility": {"categories": ["*"]}})
            cross = create_job(**{**kwargs, "plugin": load_plugin("bathroom_cabinet")}, design_pack_path=str(root / "pack.json"))
            self.assertEqual(1, len(approved_design_references(cross, "B1")))
            evaluation = {**deepcopy(pack), 'approval_scope': 'evaluation', 'production_ready': False}
            write_json(root / 'pack.json', evaluation)
            limited = create_job(**kwargs, design_pack_path=str(root / 'pack.json'))
            self.assertEqual('evaluation', approved_design_references(limited, 'B1')[0]['approval_scope'])
            self.assertFalse(load_job(limited)['design_inputs']['pack']['production_ready'])
            evaluation['assets'][0]['children'] = ['*']
            write_json(root / 'pack.json', evaluation)
            with self.assertRaisesRegex(ValueError, 'explicit child scope'):
                create_job(**kwargs, design_pack_path=str(root / 'pack.json'))
            invalid = deepcopy(pack)
            invalid["assets"][0]["reference_region"] = [0, 0, 2, 1]
            write_json(root / "pack.json", invalid)
            with self.assertRaisesRegex(ValueError, "reference region"):
                create_job(**kwargs, design_pack_path=str(root / "pack.json"))
            invalid = deepcopy(pack)
            del invalid["assets"][0]["visual_review"]["evidence_fit"]
            write_json(root / "pack.json", invalid)
            with self.assertRaisesRegex(ValueError, "Visual approval"):
                create_job(**kwargs, design_pack_path=str(root / "pack.json"))
            invalid = deepcopy(pack)
            invalid["assets"][0]["rights_review"]["status"] = "pending"
            write_json(root / "pack.json", invalid)
            with self.assertRaises(ValueError):
                create_job(**kwargs, design_pack_path=str(root / "pack.json"))
            (job / refs[0]["path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                approved_design_references(job, "B1")

    def test_vision_admission_precedes_encoding_and_observation_failure_is_local(self):
        import time
        from contextlib import contextmanager
        from copy import deepcopy
        from core import vision_gemini_client as client
        from core.image_provider_common import ProviderQueueUnavailable
        from core.visual_semantics import observe_child_sources
        endpoint = {"name": "primary", "base_url": "https://fixture.invalid/v1", "api_key": "fixture"}
        events = []
        @contextmanager
        def slot(*args, **kwargs):
            events.append("admitted")
            yield
        def payload():
            events.append("encoded")
            return {"text": "fixture"}
        with patch.object(client, "provider_concurrency_slot", side_effect=slot), patch.object(client, "_post_json_preserve_redirects", return_value="ok"):
            self.assertEqual("ok", client._post_vision_request(endpoint, "https://fixture.invalid", payload,
                headers={}, timeout_seconds=5, deadline=time.monotonic() + 10))
        self.assertEqual(["admitted", "encoded"], events)
        with patch.object(client, "provider_concurrency_slot", side_effect=ProviderQueueUnavailable("fixture", "busy")), patch.object(
                client, "_post_json_preserve_redirects") as network:
            with self.assertRaises(ProviderQueueUnavailable):
                client._post_vision_request(endpoint, "https://fixture.invalid", payload, headers={}, timeout_seconds=5, deadline=time.monotonic() + 1)
            network.assert_not_called()
        self.assertEqual(2, len(events))
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        from http.client import IncompleteRead
        class ResponseHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                if self.path == '/redirect':
                    self.send_response(307)
                    self.send_header('Location', '/slow')
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Length', '2' if self.path == '/ok' else '100')
                self.end_headers()
                try:
                    if self.path in {'/ok', '/truncated'}:
                        self.wfile.write(b'{}')
                    else:
                        for _ in range(20):
                            self.wfile.write(b'x')
                            self.wfile.flush()
                            time.sleep(.04)
                except ConnectionError:
                    pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), ResponseHandler)
        thread = Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
        thread.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            self.assertEqual('{}', client._post_json_preserve_redirects(url+'/ok', {}, {}, timeout_seconds=2))
            with self.assertRaises(IncompleteRead):
                client._post_json_preserve_redirects(url+'/truncated', {}, {}, timeout_seconds=2)
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                client._post_json_preserve_redirects(url+'/redirect', {}, {}, timeout_seconds=2, deadline=started+.15)
            self.assertLess(time.monotonic()-started, .6)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)
        alias = {**endpoint, "name": "alias", "model": "different-model"}
        other = {**endpoint, "name": "other", "base_url": "https://other.invalid/v1"}
        with patch.object(client, "gemini_clients", return_value=[endpoint, alias, other]), patch.object(client, "provider_concurrency_limit", return_value=1):
            self.assertEqual(2, client.vision_scope_capacity("vision_qa"))
            self.assertEqual(client._vision_resource(endpoint)[1], client._vision_resource(alias)[1])
        valid = {"source_id": "source_00", "role_guess": "scene", "view_coverage": "complete", "has_dimension_lines": False,
                 "has_callouts_or_panels": False, "visible_numbers_or_units": [], "confidence": .95, "evidence": [],
                 "measurements": [], "objects": [{'object_id': 'frame', 'kind': 'frame', 'state': 'visible frame', 'sale_membership': 'unknown', 'visibility': 'visible', 'relations': []}], "text_observations": [], "physical_views": [current_physical_view('v1', [0, 0, 1, 1])],
                 "variant_identity": {"status": "unknown", "observed_color": "", "reason": "Occluded", "conflicts": []}}
        bad = {**deepcopy(valid), "source_id": "source_01", "physical_views": []}
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            sources = [{"source_id": f"source_0{i}", "sha256": str(i) * 64, "ocr": [], "path": job / f"source{i}.png"} for i in range(2)]
            with patch("core.visual_semantics.gemini_stream_generate", return_value=json.dumps({"schema": {"sources": [valid, bad]}})):
                with self.assertRaisesRegex(ValueError, "top-level sources"):
                    observe_child_sources(job, {"asin": "B1"}, sources)
            with patch("core.visual_semantics.gemini_stream_generate", side_effect=[json.dumps({"sources": [valid, bad]}), TimeoutError('fixture timeout')]) as partial:
                result = observe_child_sources(job, {"asin": "B1"}, sources)
            self.assertEqual(2, partial.call_count)
            self.assertEqual([sources[1]['path']], partial.call_args.args[1])
            self.assertEqual(["success", "failed"], [result[row["source_id"]]["status"] for row in sources])
            with patch("core.visual_semantics.gemini_stream_generate", side_effect=TimeoutError("fixture timeout")) as retry:
                result = observe_child_sources(job, {"asin": "B1"}, sources)
            self.assertEqual([sources[1]["path"]], retry.call_args.args[1])
            self.assertEqual("success", result["source_00"]["status"])
            self.assertEqual("failed", result["source_01"]["status"])
            malformed = deepcopy(bad)
            malformed['physical_views'] = [current_physical_view('v1', [0.034, .86, .463, .507])]
            bad["physical_views"] = valid["physical_views"]
            with patch("core.visual_semantics.gemini_stream_generate", side_effect=[json.dumps({"sources": [malformed]}), json.dumps({"sources": [bad]})]) as repaired:
                result = observe_child_sources(job, {"asin": "B2"}, sources[1:])
            self.assertEqual(2, repaired.call_count)
            self.assertIn('"left"', repaired.call_args.args[0])
            self.assertNotIn('"region": [', repaired.call_args.args[0])
            self.assertTrue(all(row["status"] == "success" for row in result.values()))


if __name__ == "__main__":
    unittest.main()
