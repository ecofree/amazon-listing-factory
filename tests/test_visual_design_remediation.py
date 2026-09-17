from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.io import read_json
from tests.current_image_contract_fixture import current_physical_view, supported_design_reviews, supported_review_results
from core.visual_semantics import _attempt_trace
from core.visual_design_kit_compiler import cleaned_source_claims, _compile_display_copy
from core.vision_gemini_client import (
    _gemini_native_payload, _parse_sse_text_candidates, _parse_generate_content_candidates,
    _response_finish_reasons,
)


def _evidence_source(role='main', *, views=None, source_id='source_00'):
    views = [current_physical_view()] if views is None else views
    return dict(source_id=source_id, source_index=int(source_id.split('_')[-1]), role=role,
        source_sha256='a'*64, input_revision_id='r', claims=[], measurements=[],
        observation=dict(status='success', objects=[], physical_views=views,
            reference_views=[dict(view_id=view['view_id'], purposes=['appearance', 'feature']) for view in views],
            evidence_gaps=[], text_gaps=[]))


def _role_brief(compiled, role):
    return next(brief for brief in compiled['image_briefs'] if brief['role'] == role)


class VisualDesignRemediationTests(unittest.TestCase):
    def test_observed_bounds_preserve_pixels_and_feature_extent(self):
        from tests.remediation_recheck_fixture import verify_review_projection, verify_observation_feedback
        verify_review_projection(self)
        verify_observation_feedback(self)
        from PIL import Image, ImageChops
        from core.io import file_sha256
        from core.image_reference_context import (
            prepare_planning_views, planning_view_inputs, physical_views,
            view_reference, measurement_reference, measurement_attachment_location,
        )
        from core.final_source_intents import _semantic_revision
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            with Image.new("RGB", (200, 120), "magenta") as poster:
                poster.paste((180, 140, 80), (20, 30, 80, 60))
                poster.paste((20, 180, 90), (120, 75, 180, 105))
                poster.save(job / "source.png")
            views = [current_physical_view('upper', [.1, .25, .4, .5], feature='slats'),
                     current_physical_view('lower', [.6, .625, .9, .875], feature='edge_joint')]
            source = _evidence_source('scene', views=views, source_id='source_02')
            source.update(source_path='source.png', source_sha256=file_sha256(job / 'source.png'))
            source['observation']['reference_views'] = [{'view_id': 'upper', 'purposes': ['appearance']},
                                                       {'view_id': 'lower', 'purposes': ['feature']}]
            from core.visual_design_kit import _source_manifest, _validate_source_manifest, VisualDesignKitError
            manifest = _source_manifest([
                {**source, 'visual_evidence': source['observation'], 'role': 'reference_only'},
                {**source, 'visual_evidence': source['observation'], 'source_index': 3},
            ], job=job)
            self.assertTrue(all('product_claims' not in row for row in manifest))
            _validate_source_manifest(manifest)
            paths = prepare_planning_views(job, [source], job / "trace")
            self.assertEqual([dict(attachment_number=1, source_id='source_02', view_id='upper')], planning_view_inputs([source]))
            attachments = read_json(job / 'trace/manifest.json')['attachments']
            self.assertEqual(planning_view_inputs([source]), [{key: row[key] for key in ('attachment_number', 'source_id', 'view_id')} for row in attachments])
            self.assertEqual(paths, [job / row['derived_path'] for row in attachments])
            with Image.open(job / 'source.png') as original, Image.open(paths[0]) as crop, original.crop((20, 30, 80, 60)) as expected:
                self.assertIsNone(ImageChops.difference(crop, expected).getbbox())
                self.assertNotIn((255, 0, 255), set(crop.getdata()))
            detail = {**views[0], 'extent': 'detail', 'region': dict(left=0, top=0, right=.5, bottom=.6)}
            trimmed = view_reference(source, detail, job=job, child='B1', kind='edit_base')
            self.assertEqual(views[0]['region'], trimmed['original_region'])
            with Image.open(job / trimmed['path']) as crop:
                self.assertEqual((60, 30), crop.size)
                self.assertNotIn((255, 0, 255), set(crop.getdata()))
            from core.image_reference_context import resolve_edit_references, reference_semantics
            from core.visual_semantics import review_planning_bindings
            from core.visual_design_kit_compiler import design_binding_request, validate_image_brief_draft
            from tests.current_image_contract_fixture import current_art_direction, current_image_direction
            direction = current_image_direction(source_id='source_02')
            direction['evidence_usage'] = [dict(source_id='source_02', view_id=name, usage=usage, covered_by=[])
                                           for name, usage in (('upper', 'display'), ('lower', 'verification'))]
            draft = dict(role='scene', source_id='source_02', image_direction=direction)
            validate_image_brief_draft(draft, source, current_art_direction(), [source], 'bed_frame')
            refs = resolve_edit_references(draft, [source], job=job, child='B1')
            self.assertEqual(['upper', 'lower'], [row['view_id'] for row in refs])
            request = design_binding_request(draft, current_art_direction(), source=source)
            def inspect_review(prompt, images, **kwargs):
                payload = json.loads(prompt.split('\n', 1)[1])
                actual = payload['execution_inputs'][0]['attachments']
                self.assertEqual([reference_semantics(row) for row in refs],
                    [{key: value for key, value in row.items() if key not in {'review_attachment', 'generation_attachment'}} for row in actual])
                self.assertEqual([row['sha256'] for row in refs], [file_sha256(images[row['review_attachment']-1]) for row in actual])
                self.assertEqual(3, payload['source_views'][0]['attachment_number'])
                return json.dumps({'reviews': [{**value, 'reason': 'Offline test verdict'} for value in supported_review_results([request]).values()]})
            with patch('core.visual_semantics.gemini_stream_generate', side_effect=inspect_review):
                review_planning_bindings([request], job=job, child='B1', source_manifest=[source],
                    source_paths=[job/'source.png'], trace_dir=job/'execution_review')
            inside = dict(source_id='source_02', view_id='upper', source_region=dict(left=.15, top=.3, right=.3, bottom=.4), source_endpoints=None, evidence_type='text_spec')
            source['measurements'] = [inside]
            combined = resolve_edit_references({**draft, 'role': 'func'}, [source], job=job, child='B1')
            self.assertEqual(2, len(combined))
            self.assertEqual(1, measurement_attachment_location(inside, combined)['attachment'])
            located = dict(source_id='source_02', view_id='upper',
                           source_region=dict(left=.125, top=.0625, right=.375, bottom=.1875),
                           source_endpoints=None, evidence_type='text_spec')
            source['measurements'] = [located]
            source['observation']['reference_views'][0]['purposes'].append('measurement')
            appearance = view_reference(source, views[0], job=job, child='B1', kind='edit_base')
            measurement = measurement_reference(source, views[0], job=job, child='B1')
            self.assertEqual(views[0]['region'], appearance['original_region'])
            self.assertEqual(dict(left=.1, top=7/120, right=.4, bottom=.5), measurement['original_region'])
            with Image.open(job / appearance['path']) as clean, Image.open(job / measurement['path']) as annotated:
                self.assertEqual((60, 30), clean.size)
                self.assertEqual((60, 53), annotated.size)
            projected = measurement_attachment_location(located, [appearance, measurement])
            self.assertEqual(2, projected['attachment'])
            self.assertAlmostEqual(5/60, projected['label']['left'])
            self.assertAlmostEqual(.5/53, projected['label']['top'])
            self.assertIsNone(projected['endpoints'])
            located['source_endpoints'] = [dict(x=.1, y=.25), dict(x=.4, y=.5)]
            self.assertEqual(dict(x=1., y=1.), measurement_attachment_location(located, [appearance, measurement])['endpoints'][1])
            narrow = current_physical_view('drawer', [.29, .457, .299, .838], feature='drawer')
            narrow['evidence'][0]['region'] = dict(left=.04, top=.457, right=.299, bottom=.838)
            with self.assertRaisesRegex(ValueError, 'truncates observed feature'):
                physical_views([narrow])
            before = _semantic_revision({"visual_evidence": {"physical_views": views}})
            views[0]['region']['left'] = .09
            self.assertNotEqual(before, _semantic_revision({"visual_evidence": {"physical_views": views}}))
            for invalid in (None, [{"view_id": "x", "region": [0, 0, float('nan'), 1]}], [views[0], views[0]]):
                with self.assertRaises(ValueError):
                    physical_views(invalid)
            source['observation']['physical_views'] = []
            source['observation']['reference_views'] = []
            self.assertEqual([], prepare_planning_views(job, [source], job / 'empty'))
            source['observation']['physical_views'] = views
            source['observation']['reference_views'] = [dict(view_id='upper', purposes=['appearance'])]
            source['source_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, '[Ss]ource changed'):
                prepare_planning_views(job, [source], job / 'changed')

    def test_local_repair_preserves_facts_without_source_panel_obligations(self):
        from tests.remediation_recheck_fixture import verify_shared_repair, verify_partial_review_rows
        verify_shared_repair(self)
        verify_partial_review_rows(self)
        import time
        from copy import deepcopy
        from core.visual_design_kit import _finish_image_briefs, _planner_source_view
        from core.visual_design_kit_compiler import compile_visual_design_kit_response, design_binding_request
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction, supported_review_results
        from core.visual_semantics import CLAIM_REVIEW_POLICY
        views = [current_physical_view(), current_physical_view('view_02', feature='edge_joint')]
        source = _evidence_source('func', views=views)
        source['claims'] = [dict(evidence_id='drawer', text='Drawers on wheels')]
        draft = dict(role='func', source_id='source_00', image_direction=current_image_direction(),
                     display_copy=dict(title=None, labels=[dict(text='Drawers on wheels', evidence_ids=['drawer'])]))
        raw = dict(family_art_direction=current_art_direction(), image_briefs=[
            dict(role='main', source_id='source_00', image_direction=current_image_direction()), draft])
        request = design_binding_request(draft, raw['family_art_direction'], source=source)
        self.assertEqual([], request['physical_operations'])
        self.assertNotIn('unknown_product_objects', request['required_facts'])
        self.assertEqual(['view_01'], [row['view']['view_id'] for row in request['selected_evidence']])
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results) as reviewer, patch(
                'core.visual_design_kit.gemini_stream_generate') as remote:
            ready = _finish_image_briefs(raw, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[],
                source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
            self.assertEqual('ready', _role_brief(ready, 'func')['status'])
            reviewer.assert_not_called()
            remote.assert_not_called()
        for invalid_id in (None, 'bad_source_id'):
            broken = deepcopy(raw)
            broken['image_briefs'][1].pop('source_id')
            if invalid_id:
                broken['image_briefs'][1]['source_id'] = invalid_id
            def repair_anchor(prompt, attachments, **kwargs):
                payload = json.loads(prompt.split('\n', 1)[1])
                self.assertEqual('source_00', payload['pending'][0]['draft']['source_id'])
                self.assertEqual([], payload['design_review_findings'])
                return json.dumps(dict(image_briefs=[draft]))
            with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results) as reviewer, patch(
                    'core.visual_design_kit.gemini_stream_generate', side_effect=repair_anchor) as remote:
                repaired = _finish_image_briefs(broken, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[],
                    source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
                self.assertEqual('ready', _role_brief(repaired, 'func')['status'])
                self.assertEqual(_role_brief(ready, 'main'), _role_brief(repaired, 'main'))
                self.assertEqual(1, remote.call_count)
                reviewer.assert_not_called()
        draft['display_copy']['labels'] = [dict(text='Effortless pull-out', evidence_ids=['drawer'])]
        def review(requests, **kwargs):
            return {**supported_review_results(requests), **{row['key']: dict(key=row['key'], policy=CLAIM_REVIEW_POLICY, response_sha256='b'*64,
                    status='inconclusive', resolution='revise_plan', reason='Unsupported performance', findings=[]) for row in requests if row['kind'] == 'product_claim'}}
        def repair(prompt, attachments, **kwargs):
            self.assertIn('Effortless pull-out', prompt)
            self.assertEqual(1, kwargs['max_physical_requests'])
            fixed = deepcopy(draft)
            fixed['display_copy']['labels'] = [dict(text='Drawers on wheels', evidence_ids=['drawer'])]
            return json.dumps(dict(image_briefs=[fixed]))
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=review) as reviewer, patch(
                'core.visual_design_kit.gemini_stream_generate', side_effect=repair) as repair_call:
            fixed = _finish_image_briefs(raw, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[],
                source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
            self.assertEqual('ready', _role_brief(fixed, 'func')['status'])
            self.assertEqual(1, repair_call.call_count)
            self.assertEqual(1, reviewer.call_count)
            self.assertEqual(raw['family_art_direction'], fixed['family_art_direction'])
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings', side_effect=TimeoutError('review clock')), patch(
                'core.visual_design_kit.gemini_stream_generate') as unnecessary:
            unavailable = _finish_image_briefs(raw, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[],
                source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=None)
            self.assertEqual('review', _role_brief(unavailable, 'func')['failure_owner'])
            with patch('core.visual_design_kit.review_planning_bindings', side_effect=supported_review_results):
                recovered = _finish_image_briefs(raw, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame', source_paths=[],
                    source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+10, cached=unavailable)
            self.assertEqual('ready', _role_brief(recovered, 'func')['status'])
            unnecessary.assert_not_called()
        draft['display_copy']['labels'][0]['text'] = 'Drawers on wheels'
        draft['image_direction']['evidence_usage'].append(dict(source_id='source_00', view_id='view_02',
            usage='integrated', covered_by=['source_00/view_01']))
        from core.visual_semantics import candidate_view_targets
        self.assertEqual(draft['image_direction']['evidence_usage'], candidate_view_targets(draft))
        request = design_binding_request(draft, raw['family_art_direction'], source=source)
        self.assertEqual(['coverage_transfer:source_00/view_02'], request['physical_operations'])
        self.assertEqual('pending', _role_brief(compile_visual_design_kit_response(raw, source_manifest=[source]), 'func')['status'])
        reviews = supported_review_results([request])
        self.assertEqual('ready', _role_brief(compile_visual_design_kit_response(raw, source_manifest=[source], claim_reviews=reviews), 'func')['status'])
        reviews[request['key']]['findings'].append(dict(operation='source_product:source_00/view_01',
            status='contradiction', reason='Actual crop cuts the feet visible in original'))
        failed = _role_brief(compile_visual_design_kit_response(raw, source_manifest=[source], claim_reviews=reviews), 'func')
        self.assertEqual('observation', failed['failure_owner'])
        self.assertIn('cuts the feet', failed['error'])
        draft['image_direction']['evidence_usage'].pop()
        from core.visual_design_kit import compact_product_claims
        product_claims = compact_product_claims({'title': 'Frame with drawers'})
        disputed = dict(object_id='frame', kind='frame', sale_membership='unknown',
            membership_evidence=[dict(fact_id='product.title', quote='Frame with drawers')],
            visibility='visible', state='visible product')
        source['observation']['objects'] = [disputed, {**disputed, 'object_id': 'unselected'}]
        request = design_binding_request(draft, raw['family_art_direction'], source=source, product_claims=product_claims)
        self.assertEqual(['sold_membership:source_00/view_01'], request['physical_operations'])
        self.assertEqual([dict(source_id='source_00', **disputed)], request['required_facts']['unknown_product_objects'])
        self.assertEqual(product_claims, request['required_facts']['product_claims'])
        self.assertEqual('product.title', request['required_facts']['product_claims'][0]['field_path'])
        unchanged = deepcopy(raw)
        source['observation']['objects'] = [{**disputed, 'sale_membership': 'product', 'state': 'Assembled frame with mattress'}]
        unchanged['image_briefs'][1]['display_copy']['labels'] = [dict(text='Drawers on wheels', evidence_ids=['drawer'])]
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_design_kit.review_planning_bindings') as review, patch(
                'core.visual_design_kit.gemini_stream_generate') as redesign:
            ready = _finish_image_briefs(unchanged, job=Path(tmp), child='B1', source_manifest=[source], category_id='bed_frame',
                source_paths=[], source_originals=[], trace_dir=Path(tmp), deadline_monotonic=time.monotonic()+5, cached=None)
            self.assertTrue(all(row['status'] == 'ready' for row in ready['image_briefs'] if row['role'] in {'main', 'func'}),
                            [(row['role'], row.get('error')) for row in ready['image_briefs']])
            review.assert_not_called()
            redesign.assert_not_called()
        source['observation']['objects'] = []
        source['observation']['reference_views'] = [dict(view_id='view_01', purposes=['appearance'])]
        projection = _planner_source_view(source)
        self.assertEqual(['view_01', 'view_02'], [view['view_id'] for view in projection['views']])
        self.assertNotIn('physical_evidence', projection)

    def test_independent_canvas_uses_one_design_contract_without_source_style(self):
        from core.visual_design_kit import visual_design_kit_prompt
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        from core.plugin import load_plugin
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction
        source = _evidence_source()
        source['shopping_intent'] = 'OLD_PURPOSE'
        source['observation'].update(layout_summary='OLD_CAPSULE_LAYOUT', text_observations=[dict(kind='prop', text='OLD_PROP_WORDS')])
        prompt = visual_design_kit_prompt(load_plugin("bed_frame"), {}, {}, [source])
        for old in ("OLD_PURPOSE", "OLD_CAPSULE_LAYOUT", "OLD_PROP_WORDS"):
            self.assertNotIn(old, prompt)
        raw = {"family_art_direction": current_art_direction(), "image_briefs": [{
            "role": "main", "source_id": "source_00", "image_direction": "obsolete unconstrained string"}]}
        rejected = compile_visual_design_kit_response(raw, source_manifest=[source])
        self.assertEqual("pending", rejected["image_briefs"][0]["status"])
        raw["image_briefs"][0]["image_direction"] = current_image_direction()
        self.assertEqual("ready", compile_visual_design_kit_response(raw, source_manifest=[source], claim_reviews=supported_design_reviews(raw, [source]))["image_briefs"][0]["status"])
        raw["image_briefs"][0]["image_direction"]["evidence_usage"][0]["view_id"] = "unobserved_view"
        self.assertEqual("pending", compile_visual_design_kit_response(raw, source_manifest=[source])["image_briefs"][0]["status"])
        raw["image_briefs"][0]["image_direction"] = current_image_direction()
        raw["image_briefs"][0]["image_direction"]["evidence_usage"][0]["covered_by"] = ['source_00/view_01']
        self.assertEqual("pending", compile_visual_design_kit_response(raw, source_manifest=[source])["image_briefs"][0]["status"])
        source["role"] = "size"
        raw['image_briefs'][0]['role'] = 'size'
        source['claims'] = [{'evidence_id': 'heading', 'text': 'Product Dimensions'}]
        raw['image_briefs'][0]['display_copy'] = {'title': {'evidence_ids': ['heading'], 'text': 'Product Dimensions'}, 'labels': []}
        raw["image_briefs"][0]["image_direction"] = current_image_direction(environment="graphic_canvas")
        size_brief = _role_brief(compile_visual_design_kit_response(raw, source_manifest=[source], claim_reviews=supported_design_reviews(raw, [source])), 'size')
        self.assertEqual("ready", size_brief["status"])
        self.assertEqual({'visual_goal', 'presentation', 'evidence_usage', 'design_transfer', 'environment_mode'}, set(size_brief['image_direction']))
        self.assertEqual(raw['image_briefs'][0]['image_direction'], size_brief['image_direction'])
        self.assertEqual('Product Dimensions', size_brief['display_copy_contract']['title'])
        from core.image_task_inputs import task_specs
        sources = [_evidence_source(role, source_id=f'source_{i:02d}') for i, role in enumerate(
            ('size', 'scene', 'scene', 'func', 'func', 'reference_only'))]
        sources[2]['observation'].update(physical_views=[], reference_views=[])
        specs = task_specs({}, sources, include_optional=True)
        self.assertEqual(['main', 'scene', 'scene_02', 'func', 'func_02', 'size'], [row['role'] for row in specs])
        self.assertIs(specs[0]['source'], specs[-1]['source'])
        self.assertEqual(['main', 'scene', 'func', 'size'], [row['role'] for row in task_specs({}, sources)])
        briefs = []
        for spec in specs:
            brief = dict(role=spec['role'], source_id=spec['source']['source_id'], image_direction=current_image_direction())
            if spec['role'].split('_', 1)[0] in {'func', 'size'}:
                brief['display_copy'] = dict(title=None, labels=[])
            briefs.append(brief)
        raw = dict(family_art_direction=current_art_direction(), image_briefs=briefs)
        self.assertTrue(all(row['status'] == 'ready' for row in compile_visual_design_kit_response(raw, source_manifest=sources, claim_reviews=supported_design_reviews(raw, sources))['image_briefs']))
        sources[0]['observation']['text_gaps'] = ['Required width is unreadable']
        affected = compile_visual_design_kit_response(raw, source_manifest=sources, claim_reviews=supported_design_reviews(raw, sources))
        self.assertEqual(['size'], [row['role'] for row in affected['image_briefs'] if row['status'] != 'ready'])
        from core.image_generation import _compose_revision_prompt
        base = 'x' * 7394
        revised = _compose_revision_prompt(base_prompt=base, request_heading='full redraw', request_intro='Redraw the same task.', reason='Preserve the original joint.')
        self.assertTrue(revised.startswith(base))
        self.assertLessEqual(len(revised), 8000)
        with self.assertRaisesRegex(RuntimeError, 'maximum executable length'):
            _compose_revision_prompt(base_prompt=base, request_heading='full redraw', request_intro='Same task.', reason='x'*1000)

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
        source = {"source_id": "source_00", "role": "size", "visual_evidence": visual,
                  "ocr_evidence": {"lines": [{"text": "17'", "confidence": .93, "box": [0, 0, 1, 1]}]},
                  "measurements": _measurement_rows(_observed_measurements(visual), {})}
        authority = _measurement_authority("size", source, [(source, current_physical_view())])
        self.assertEqual(2, len(authority["measurement_groups"]))
        self.assertEqual(['17 in', '300 lbs'], authority['render_text'])
        self.assertEqual('load_capacity', authority['measurement_groups'][1]['measurement_role'])
        self.assertNotIn('source_visible_callouts', authority)
        values = _observed_measurements(visual)
        self.assertEqual(2, len(values))
        self.assertNotIn('17 ft', [r['text'] for r in values])
        from core.visual_semantics import _validate_source_measurements, _validate_candidate_observation
        from copy import deepcopy
        repeated = deepcopy(visual['measurements'])
        from core.image_prompt_compiler import _measurement_content
        from core.image_reference_context import measurement_attachment_location
        before = deepcopy(authority)
        refs = [{'kind': 'measurement_evidence', 'source_id': 'source_00', 'view_id': 'view_01', 'original_region': current_physical_view()['region']}]
        content = _measurement_content(authority, refs)
        self.assertEqual(before, authority)
        self.assertEqual(1, content.count('17 in'))
        for encoded, measurement in zip(content.split(' @ ')[1:], authority['measurement_groups']):
            location = json.loads(encoded.split('; ', 1)[0])
            precise = measurement_attachment_location(measurement, refs)
            for axis, value in location['label'].items():
                self.assertLessEqual(abs(value - precise['label'][axis]), .000000500001)
            if precise['endpoints'] is None:
                self.assertIsNone(location['endpoints'])
            else:
                for point, exact in zip(location['endpoints'], precise['endpoints']):
                    for axis in ('x', 'y'):
                        self.assertLessEqual(abs(point[axis] - exact[axis]), .000000500001)
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
        for text in ('\u2264 6"', '6-8 in', '6 in to 8 in'):
            with self.subTest(complete_measurement=text):
                visual['measurements'] = [current_observed_measurement(text, 'Recommended mattress thickness', key='mattress')]
                _validate_source_measurements(visual['measurements'], [current_physical_view()])
                source['measurements'] = _measurement_rows(_observed_measurements(visual), {})
                authority = _measurement_authority('func', source, [(source, current_physical_view())])
                self.assertEqual(text, authority['measurement_groups'][0]['source_text'])
                self.assertEqual(text, authority['render_text'][0])
                self.assertIn('Recommended mattress thickness', _measurement_content(authority, refs))
                self.assertIn(text, _measurement_content(authority, refs))
                task['measurement_authority'] = authority
                obs['measurements'] = [dict(measurement_id=authority['measurement_groups'][0]['id'],
                    source_text=text, candidate_text='6 in', relationship='same', confidence=.99)]
                self.assertEqual('fail', _semantic_gates(task, obs)[1]['status'])

    def test_complete_single_word_claims_remain_bindable(self):
        source = _evidence_source('func')
        source['claims'] = [{"evidence_id": str(i), "text": word}
                            for i, word in enumerate(("Pathway", "Wedding", "Q", "T o", "\ufffd"))]
        self.assertEqual(["Pathway", "Wedding"], [row["text"] for row in cleaned_source_claims(source)])
        result = _compile_display_copy([source], {"title": None, "labels": [
            {"text": "Pathway", "evidence_ids": ["0"]}, {"text": "Wedding", "evidence_ids": ["1"]}]})
        self.assertEqual(["Pathway", "Wedding"], result["labels"])
        from core.visual_design_kit_compiler import claim_review_requests
        from core.visual_semantics import CLAIM_REVIEW_POLICY
        physical_id = 'physical:source_00:view_01:frame_support:0'
        copy = {'title': None, 'labels': [{'text': 'Visible frame support and its joints', 'evidence_ids': [physical_id]}]}
        requests = claim_review_requests({'image_briefs': [{'role': 'func', 'source_id': 'source_00', 'display_copy': copy}]}, [source])
        self.assertEqual(1, len(requests))  # Visual descriptions never bypass independent claim verification.
        self.assertEqual({physical_id: copy['labels'][0]['text']}, requests[0]['evidence'])
        with self.assertRaisesRegex(ValueError, 'independent evidence review'):
            _compile_display_copy([source], copy)
        reviewed = {requests[0]['key']: {'key': requests[0]['key'], 'status': 'supported',
                                       'policy': CLAIM_REVIEW_POLICY, 'response_sha256': 'a' * 64}}
        self.assertEqual([copy['labels'][0]['text']], _compile_display_copy([source], copy, claim_reviews=reviewed)['labels'])
        from core.image_task_inputs import build_display_copy_contract
        from core.visual_design_kit_compiler import validate_image_brief_draft
        from tests.current_image_contract_fixture import current_art_direction, current_image_direction
        from copy import deepcopy
        other = deepcopy(source)
        other['source_id'] = 'source_06'
        other['claims'] = [dict(evidence_id='8347dde92d972874b0a8', text='Open Shelf'),
                           dict(evidence_id='c87e2308a69a60c4c00d', text='2-Door Lower Cabinet'),
                           dict(evidence_id='a8bcffa59a926b4a01bc', text='Sliding Barn Door Cabinet')]
        cross_copy = dict(title=None, labels=[dict(evidence_ids=[row['evidence_id']], text=row['text']) for row in other['claims']])
        draft = dict(role='func', source_id=source['source_id'], image_direction=current_image_direction(), display_copy=cross_copy)
        sources = [source, other]
        validate_image_brief_draft(draft, source, current_art_direction(), sources, 'bathroom_cabinet')
        contract = _compile_display_copy(sources, cross_copy)
        self.assertEqual(contract, build_display_copy_contract(sources, dict(source_id=source['source_id'], display_copy_contract=contract)))
        with self.assertRaisesRegex(ValueError, 'evidence scope'):
            _compile_display_copy([source], cross_copy)
        with self.assertRaisesRegex(ValueError, 'independent evidence review'):
            _compile_display_copy(sources, dict(title=None, labels=[dict(evidence_ids=[physical_id], text='Solid pine supports 440 lb')]))
        source['measurements'] = [dict(source_label='recommended mattress thickness', text='\u2264 6"')]
        stale = dict(title=None, labels=[dict(evidence_ids=['measurement:source_00:0'], text='Recommended mattress thickness: 6 in')])
        with self.assertRaisesRegex(ValueError, 'headings only'):
            _compile_display_copy(sources, stale)
        stale_contract = dict(mode='source_claims', title='', labels=[stale['labels'][0]['text']], bindings=stale['labels'])
        with self.assertRaisesRegex(ValueError, 'headings only'):
            build_display_copy_contract(sources, dict(source_id='source_00', display_copy_contract=stale_contract))
        stale['labels'][0]['text'] = 'recommended mattress thickness'
        self.assertEqual(['recommended mattress thickness'], _compile_display_copy(sources, stale)['labels'])
        import time
        from core.visual_semantics import review_planning_bindings
        from tests.current_image_contract_fixture import current_art_direction
        deadline = time.monotonic() + 80
        response = json.dumps({'reviews': [{'key': requests[0]['key'], 'status': 'supported', 'reason': 'Visible local structure',
            'findings': [{'operation': 'source_00', 'status': 'supported', 'reason': 'Visible frame joints'}]}]})
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_semantics.gemini_stream_generate', return_value=response) as remote:
            review_planning_bindings(requests, job=Path(tmp), child='B1', trace_dir=Path(tmp), deadline_monotonic=deadline)
        self.assertEqual(deadline, remote.call_args.kwargs['deadline_monotonic'])
        self.assertEqual(1, remote.call_args.kwargs['max_physical_requests'])
        self.assertNotIn('total_timeout_seconds', remote.call_args.kwargs)
        review_payload = json.loads(remote.call_args.args[0].split('\n', 1)[1])
        self.assertEqual({}, review_payload['shared_design'])
        self.assertNotIn('shared_design_paths', review_payload['bindings'][0])
        from core.visual_design_kit import _planner_evidence
        source['claims'] = [{'evidence_id': 'source_00:wheel', 'text': 'Drawers on wheels'}]
        product_claims = [{'evidence_id': 'product:wheel', 'text': 'Drawers on wheels'}]
        second = {**source, 'source_id': 'source_01', 'claims': [
            {'evidence_id': 'source_01:wheel', 'text': 'Drawers on wheels'},
            {'evidence_id': 'source_01:placement', 'text': 'Drawers can be placed on either side of the bed'}]}
        views, texts = _planner_evidence([source, second], product_claims)
        self.assertTrue(all('source_supported_claims' not in view for view in views))
        wheel = [row for row in texts if row['text'] == 'Drawers on wheels']
        self.assertEqual(1, len(wheel))
        self.assertEqual({'product:wheel', 'source_00:wheel', 'source_01:wheel'}, set(wheel[0]['evidence_ids']))
        self.assertIn('source_01:placement', views[1]['source_supported_claim_ids'])
        self.assertIn('Drawers can be placed on either side of the bed', [row['text'] for row in texts])

    def test_native_json_ignores_thoughts_and_keeps_failed_response_evidence(self):
        from tests.remediation_recheck_fixture import verify_output_capacity_and_raw_trace
        verify_output_capacity_and_raw_trace(self)
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
        from core.vision_gemini_client import _select_response_candidate, _response_failure_kind, _response_retry_prompt, _response_usage
        limited = json.dumps({'candidates': [{'finishReason': 'MAX_TOKENS'}], 'usageMetadata': {'candidatesTokenCount': 8192}})
        self.assertIsNone(_select_response_candidate(['{}'], lambda text: True, response_body=limited)[1])
        self.assertEqual('output_limit', _response_failure_kind(limited, 'JSONDecodeError'))
        self.assertEqual('json_syntax', _response_failure_kind(body, 'JSONDecodeError: bad JSON at char 18'))
        client = {'max_output_tokens': 8192}
        self.assertEqual('original', _response_retry_prompt(client, 'original', 'cut', 'partial', 'output_limit'))
        self.assertEqual(16384, client['max_output_tokens'])
        self.assertEqual({'candidatesTokenCount': 8192}, _response_usage(limited))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attempts.json"
            _, record = _attempt_trace(path)
            record({"status": "validation_failure", "response_text": '{"sources": [',
                    "response_candidates": [{"validation_error": "incomplete object"}]})
            event = read_json(path)[0]
            self.assertEqual('{"sources": [', (path.parent / event["response_path"]).read_text())
            self.assertEqual(["incomplete object"], event["validation_errors"])
            _, next_record = _attempt_trace(path)
            next_record({'status': 'success', 'response_text': '{}'})
            self.assertEqual(2, len(read_json(path)))
            self.assertNotEqual(read_json(path)[0]['response_path'], read_json(path)[1]['response_path'])

    def test_color_tools_measure_gemini_choices_without_selecting_or_mutating(self):
        from tests.child_palette_regression_fixture import check_child_components
        check_child_components(self)
        from copy import deepcopy
        from core.palette_registry import planned_palette_diagnostics
        from tests.current_image_contract_fixture import current_art_direction
        direction = current_art_direction()
        before = deepcopy(direction)
        report = planned_palette_diagnostics(direction)
        self.assertEqual(before, direction)
        self.assertIn("palette_direction.room.wall", report["colors"])
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
        from core.image_reference_context import resolve_edit_references
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
            source = _evidence_source('func', views=[current_physical_view(region=[0, 0, 1, 1])])
            source['observation']['reference_views'][0]['purposes'] = ['feature']
            source['source_path'] = 'source.png'
            from core.image_reference_context import prepare_planning_views
            Image.new('RGB', (100, 100), 'white').save(job / 'source.png')
            source['source_sha256'] = file_sha256(job / 'source.png')
            self.assertEqual([], prepare_planning_views(job, [source], job / 'trace'))
            self.assertEqual([], read_json(job / 'trace/manifest.json')['attachments'])
            prompt = visual_design_kit_prompt(plugin, {}, {}, [source], refs, brand_design_brief(job))
            self.assertIn("quiet modern residential", prompt)
            self.assertIn('"attachment_number": 1', prompt)
            self.assertNotIn('"attachment_number": 2', prompt)
            self.assertNotIn("license_evidence", prompt)
            direction = current_image_direction()
            direction["design_transfer"] = [{"reference_id": asset["asset_id"],
                "inherit": "Keep the reference detail-to-product hierarchy with shared typography",
                "adapt": "Use the available frontal view for this product instead of an unseen angle"}]
            raw = {"family_art_direction": current_art_direction(), "image_briefs": [{
                "role": "func", "source_id": "source_00", "image_direction": direction,
                "display_copy": {"title": None, "labels": []}}]}
            compiled = compile_visual_design_kit_response(raw, source_manifest=[source], design_references=refs, claim_reviews=supported_design_reviews(raw, [source], refs))
            brief = _role_brief(compiled, 'func')
            self.assertEqual("ready", brief["status"])
            self.assertEqual({}, brief['design_review'])
            from core.visual_design_kit_compiler import design_binding_request, validate_compiled_visual_design_kit
            from core.visual_semantics import CLAIM_REVIEW_POLICY
            request = design_binding_request(raw['image_briefs'][0], compiled['family_art_direction'], source=source, design_references=refs)
            self.assertEqual(refs[0]['purpose'], request['reference_scopes'][0]['purpose'])
            self.assertEqual(refs[0]['visual_review']['transfer_scope'], request['reference_scopes'][0]['approval_boundary'])
            changed_refs = deepcopy(refs)
            changed_refs[0]['roles'] = ['scene']
            with self.assertRaisesRegex(ValueError, 'not approved'):
                validate_compiled_visual_design_kit(compiled, source_manifest=[source], design_references=changed_refs)
            validate_compiled_visual_design_kit(compiled, source_manifest=[source], design_references=refs)
            generation = resolve_edit_references(brief, [source], design_references=refs, job=job, child="B1")
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
            self.assertEqual(task["product_facts"], alternate["product_facts"])
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
            broken["image_briefs"][0]["image_direction"]["design_transfer"][0]["inherit"] = "Use #123456 for all titles"
            self.assertEqual("pending", _role_brief(compile_visual_design_kit_response(broken, source_manifest=[source], design_references=refs), 'func')["status"])
            source["role"] = "scene"
            raw['image_briefs'][0]['role'] = 'scene'
            raw['image_briefs'][0].pop('display_copy')
            self.assertEqual("pending", _role_brief(compile_visual_design_kit_response(raw, source_manifest=[source], design_references=refs), 'scene')["status"])
            direction["design_transfer"] = []
            self.assertEqual("ready", _role_brief(compile_visual_design_kit_response(raw, source_manifest=[source], design_references=refs, claim_reviews=supported_design_reviews(raw, [source], refs)), 'scene')["status"])
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
            from core.design_reference_library import production_reference_error
            from core.image_tasks import _task_fingerprint
            limited_task = current_image_task('func')
            limited_task['image_direction']['design_transfer'] = deepcopy(task['image_direction']['design_transfer'])
            limited_task['generation_references'] = [generation[0], *approved_design_references(limited, 'B1')]
            self.assertIn('production usage approval', production_reference_error(limited, limited_task))
            self.assertEqual('', production_reference_error(limited, {**limited_task, 'generation_references': []}))
            before = _task_fingerprint(limited_task)
            updated = load_job(limited)
            updated['design_inputs']['pack'].update(approval_scope='production', production_ready=True)
            for ref in updated['design_inputs']['references']:
                ref.update(approval_scope='production', approved_at='new authorized review date')
            write_json(limited / 'job.json', updated)
            self.assertEqual('', production_reference_error(limited, limited_task))
            limited_task['generation_references'] = [generation[0], *approved_design_references(limited, 'B1')]
            self.assertEqual(before, _task_fingerprint(limited_task))
            from core.image_tasks import image_tasks_current
            refreshed = deepcopy(limited_task)
            refreshed['generation_references'][1]['approved_at'] = 'latest authorized review'
            self.assertEqual(_task_fingerprint(limited_task), _task_fingerprint(refreshed))
            with patch('core.image_tasks.read_image_tasks', return_value=dict(tasks=[limited_task])), patch(
                    'core.image_tasks._expected_rows', return_value=[refreshed]):
                self.assertFalse(image_tasks_current(limited, plugin))
            limited_task['generation_references'][1]['visual_review']['transfer_scope'] += ' Changed design scope'
            self.assertNotEqual(before, _task_fingerprint(limited_task))
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
        valid = {"source_id": "source_00", "role_guess": "scene", "evidence_gaps": [], "text_gaps": [], "has_dimension_lines": False,
                 "has_callouts_or_panels": False, "visible_numbers_or_units": [], "confidence": .95, "evidence": [],
                 "measurements": [], "objects": [{'object_id': 'frame', 'kind': 'frame', 'state': 'visible frame', 'sale_membership': 'unknown', 'visibility': 'visible', 'membership_evidence': []}],
                 "text_observations": [], "physical_views": [current_physical_view('v1', [0, 0, 1, 1])],
                 'reference_views': [dict(view_id='v1', purposes=['appearance'])],
                 "variant_identity": {"status": "unknown", "observed_color": "", "reason": "Occluded", "conflicts": []}}
        from core.visual_semantics import _validate_observations
        mixed = {**deepcopy(valid), 'evidence_gaps': 'wrong list type',
                 'visible_numbers_or_units': [{'raw_text': '34.5 inches'}]}
        rejected = _validate_observations([mixed], ['source_00'], {})['source_00']['error']
        self.assertIn('evidence_gaps', rejected)
        self.assertIn('visible_numbers_or_units', rejected)
        for fields, value in (
            (('objects', 0, 'membership_evidence'), [{'fact_id': 'product.title', 'quote': 17}]),
            (('objects', 0, 'membership_evidence'), [{'fact_id': [], 'quote': 'Wood frame'}]),
            (('objects', 0, 'membership_evidence'), {}),
            (('objects', 0, 'sale_membership'), []), (('role_guess',), []),
            (('variant_identity', 'status'), []), (('text_observations',), 17),
            (('physical_views', 0, 'extent'), []), (('reference_views', 0, 'view_id'), []),
            (('reference_views', 0, 'purposes'), [[]]),
        ):
            malformed = {**deepcopy(valid), 'source_id': 'source_01'}
            target = malformed
            for field in fields[:-1]:
                target = target[field]
            target[fields[-1]] = value
            result = _validate_observations([valid, malformed], ['source_00', 'source_01'], {'product.title': 'Wood frame'})
            self.assertEqual(['success', 'failed'], [result[key]['status'] for key in ('source_00', 'source_01')])
        malformed = {**deepcopy(valid), 'source_id': 'source_01'}
        malformed['objects'][0]['membership_evidence'] = [{'fact_id': 'product.title', 'quote': 17}]
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_semantics.gemini_stream_generate', side_effect=[
                json.dumps({'sources': [valid, malformed]}), json.dumps({'sources': [{**valid, 'source_id': 'source_01'}]})]) as remote:
            sources = [dict(source_id=f'source_0{i}', sha256=str(i)*64, ocr=[], path=Path(tmp)/f'{i}.png') for i in range(2)]
            result = observe_child_sources(Path(tmp), {'asin': 'TYPES', 'title': 'Wood frame'}, sources)
            self.assertTrue(all(row['status'] == 'success' for row in result.values()))
            self.assertEqual([sources[1]['path']], remote.call_args.args[1])
        bad = {**deepcopy(valid), "source_id": "source_01", "physical_views": []}
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            sources = [{"source_id": f"source_0{i}", "sha256": str(i) * 64, "ocr": [], "path": job / f"source{i}.png"} for i in range(2)]
            with patch("core.visual_semantics.gemini_stream_generate", return_value=json.dumps({"schema": {"sources": [valid, bad]}})):
                invalid = observe_child_sources(job, {"asin": "INVALID"}, sources)
                self.assertIn('top-level sources', invalid['source_00']['error'])
            with patch("core.visual_semantics.gemini_stream_generate", side_effect=[json.dumps({"sources": [valid, bad]}), TimeoutError('fixture timeout')]) as partial:
                result = observe_child_sources(job, {"asin": "B1"}, sources)
            self.assertEqual(2, partial.call_count)
            self.assertEqual([sources[1]['path']], partial.call_args.args[1])
            self.assertEqual(["success", "failed"], [result[row["source_id"]]["status"] for row in sources])
            bad['physical_views'] = valid['physical_views']
            with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [bad]})) as retry:
                result = observe_child_sources(job, {'asin': 'B1'}, sources)
            self.assertEqual([sources[1]['path']], retry.call_args.args[1])
            self.assertTrue(all(row['status'] == 'success' for row in result.values()))
            correction = {'source_00': {'revision': 'operator-correction-1', 'reason': 'Source annotation is not a product finish'}}
            corrected = deepcopy(valid)
            corrected['physical_views'][0]['evidence'][0]['physical_facts'] = ['Visible frame without a colored outline']
            with patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps({'sources': [corrected]})) as reread:
                result = observe_child_sources(job, {'asin': 'B1'}, sources, corrections=correction)
                self.assertEqual([sources[0]['path']], reread.call_args.args[1])
                self.assertEqual('operator-correction-1', result['source_00']['correction_revision'])
                self.assertEqual('success', result['source_01']['status'])
                observe_child_sources(job, {'asin': 'B1'}, sources, corrections=correction)
                self.assertEqual(1, reread.call_count)
            malformed = deepcopy(bad)
            malformed['physical_views'] = [current_physical_view('v1', [0.034, .86, .463, .507])]
            bad["physical_views"] = valid["physical_views"]
            with patch("core.visual_semantics.gemini_stream_generate", side_effect=[json.dumps({"sources": [malformed]}), json.dumps({"sources": [bad]})]) as repaired:
                result = observe_child_sources(job, {"asin": "B2"}, sources[1:])
            self.assertEqual(2, repaired.call_count)
            self.assertIn('"left"', repaired.call_args.args[0])
            self.assertIn('"reference_views"', repaired.call_args.args[0])
            self.assertIn('"endpoints": null', repaired.call_args.args[0])
            self.assertNotIn('complete|partial;', repaired.call_args.args[0])
            self.assertNotIn('"region": [', repaired.call_args.args[0])
            self.assertTrue(all(row["status"] == "success" for row in result.values()))


if __name__ == "__main__":
    unittest.main()
