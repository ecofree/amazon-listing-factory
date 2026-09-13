from __future__ import annotations

import unittest
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.text_evidence import extract_measurements, us_measurement_text, measurement_values_match
from tests.current_image_contract_fixture import current_physical_view
from core.template_field_values import template_dimensions_from_facts
from core.image_qa import _line_matches_any, _unsupported_contract_lines
from core.visual_design_kit import compact_product_claims
from core.visual_design_kit_compiler import _reject_renderable_copy_instruction, VisualDesignKitCompileError


class UsMeasurementContractTests(unittest.TestCase):
    def test_metric_display_and_rounding_are_bound_to_physical_values(self):
        for raw, expected in [('100 cm', '39.37 in'), ('2.54 cm', '1 in'),
                              ('10 kg', '22.05 lb'), ('Capacity: 10 kg', 'Capacity: 22.04 lb'),
                              ('100 x 50 x 40 cm', '39.37 x 19.69 x 15.75 in')]:
            with self.subTest(raw=raw):
                self.assertEqual(expected, us_measurement_text(raw))
                self.assertTrue(measurement_values_match(raw, expected))
        self.assertFalse(measurement_values_match('1.2 kg', '12 kg'))
        self.assertFalse(measurement_values_match('100 cm', '39.38 in'))
        self.assertEqual('393.7 in', us_measurement_text('1,000 cm'))

    def test_fraction_and_compound_length_preserve_the_whole_quantity(self):
        self.assertEqual('38.1', extract_measurements('1 1/2 in')[0]['canonical_value'])
        self.assertTrue(measurement_values_match('5 ft 6 in', '66 in'))
        self.assertTrue(measurement_values_match('20 ft', '240 in'))
        self.assertFalse(measurement_values_match('-1.2 kg', '1.2 kg'))
        self.assertTrue(measurement_values_match('2-4 cm', '0.79-1.57 in'))
        self.assertEqual('39.37 L x 19.69 W x 15.75 H in', us_measurement_text('100 L x 50 W x 40 H cm'))

    def test_template_accepts_inline_and_separate_units(self):
        from products.generic_extractors import extract_specs_by_fields
        facts = extract_specs_by_fields({'productDetails': {'Product Dimensions': '100 x 50 x 40 cm'}}, {'dimensions': ('Product Dimensions',)})
        projected = template_dimensions_from_facts(facts)
        self.assertEqual('39.37', projected['length'])
        self.assertEqual('15.75', projected['height'])
        self.assertEqual('Inches', projected['height_unit'])
        for facts in [{'height': '100 cm'}, {'height': '100', 'height_unit': 'cm'}]:
            self.assertEqual({'height': '39.37', 'height_unit': 'Inches'}, template_dimensions_from_facts(facts))
        for facts in [{'item_weight': '10 kg'}, {'item_weight': '10', 'item_weight_unit': 'Kilograms'}]:
            self.assertEqual({'item_weight': '22.05', 'item_weight_unit': 'Pounds'}, template_dimensions_from_facts(facts))
        self.assertEqual('60', template_dimensions_from_facts({'height': '5', 'height_unit': 'Feet'})['height'])
        with self.assertRaisesRegex(ValueError, 'Conflicting explicit units'):
            template_dimensions_from_facts({'height': '100 cm', 'height_unit': 'in'})

    def test_text_matching_never_erases_numeric_punctuation(self):
        self.assertFalse(_line_matches_any('Load Capacity: 12 kg', ['Load Capacity: 1.2 kg']))
        self.assertFalse(_line_matches_any('1/2 in', ['12 in']))
        self.assertEqual([], _unsupported_contract_lines(['Heavy Duty', 'Support'], ['Heavy Duty Support']))

    def test_equal_values_keep_their_source_properties(self):
        claims = compact_product_claims({'specs': {'number_of_doors': 2, 'number_of_drawers': 2}, 'description': 'Two separate storage sections.'})
        self.assertEqual(3, len(claims))
        self.assertEqual(3, len({r['field_path'] for r in claims}))
        height = compact_product_claims({'specs': {'height': '100', 'height_unit': 'cm'}})
        self.assertEqual(1, len(height))
        self.assertEqual('height: 39.37 in', height[0]['text'])

    def test_layout_language_does_not_authorize_literal_copy(self):
        _reject_renderable_copy_instruction('Place the title above the product with generous spacing.', 'direction')
        with self.assertRaises(VisualDesignKitCompileError):
            _reject_renderable_copy_instruction('Write the title: Best Product', 'direction')

    def test_observer_cache_changes_with_model_without_image_generation(self):
        from core.visual_semantics import observe_candidate
        from tests.test_qa_lite_v1 import _task, _observed
        task = {**_task('main'), 'product_facts': {}}
        task['generation_references'][0].update(kind='edit_base', path='source.png', sha256='a' * 64, purpose='Original view')
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps(_observed(task))) as request:
            candidate = {'candidate_path': 'image.png', 'candidate_sha256': 'c' * 64}
            with patch('core.vision_gemini_client.gemini_scope_execution_revision', return_value='model1'):
                observe_candidate(Path(tmp), task, candidate)
                observe_candidate(Path(tmp), task, candidate)
            with patch('core.vision_gemini_client.gemini_scope_execution_revision', return_value='model2'):
                observe_candidate(Path(tmp), task, candidate)
            self.assertEqual(2, request.call_count)
            prompt = request.call_args.args[0]
            output = json.loads(prompt.split('OUTPUT OBJECT (these fields are top-level):\n', 1)[1])
            self.assertIn('text_coverage', output)
            self.assertNotIn('schema', output)
            self.assertIn('named {left,top,right,bottom}', prompt)
        from core.io import file_sha256
        from core.image_qa import _semantic_gates
        with tempfile.TemporaryDirectory() as tmp:
            parent_path, prompt_path = Path(tmp) / 'parent.png', Path(tmp) / 'edit.txt'
            parent_path.write_bytes(b'parent test bytes')
            prompt_path.write_text('# Revision request\nFix title spacing only', encoding='utf-8')
            candidate.update(revision_mode='targeted_edit', edit_parent_candidate_sha256=file_sha256(parent_path),
                             prompt_path='edit.txt', request_prompt_fingerprint=file_sha256(prompt_path))
            response = _observed(task)
            response['edit_comparison'] = {**response['product_comparisons'][0], 'status': 'contradiction', 'evidence': 'Unrequested drawer removed'}
            with patch('core.candidate_state.candidate_by_sha', return_value={'candidate_path': 'parent.png'}), patch('core.visual_semantics.gemini_stream_generate', return_value=json.dumps(response)) as request:
                observed = observe_candidate(Path(tmp), task, candidate)
                self.assertIn('Fix title spacing only', request.call_args.args[0])
                self.assertEqual(parent_path, request.call_args.args[1][-1])
                self.assertEqual('fail', _semantic_gates(task, observed)[-1]['status'])

    def test_local_failure_is_current_evidence_without_remote_observation(self):
        from core.image_qa import _evaluate
        from core.qa_evidence import evidence_is_current
        from tests.test_qa_lite_v1 import _task
        task, candidate = _task('main'), {'candidate_path': 'image.png', 'candidate_sha256': 'c' * 64}
        with tempfile.TemporaryDirectory() as tmp, patch('core.image_qa._local_gates', return_value=[{'gate': 'image_integrity', 'status': 'fail', 'evidence': 'Broken image'}]), patch('core.image_qa.observe_candidate') as remote:
            evidence = _evaluate(Path(tmp), object(), task, candidate)
            self.assertTrue(evidence_is_current(evidence, task, candidate))
            self.assertEqual('fail', evidence['automatic_decision'])
            remote.assert_not_called()

    def test_source_disposition_is_explicit_and_sha_bound(self):
        from core.final_source_intents import record_source_intent_review, _current_source_intent_reviews
        downloads = [{'status': 'ok', 'child': 'B1', 'index': 1, 'source_sha256': 'a' * 64}]
        with tempfile.TemporaryDirectory() as tmp, patch('core.final_source_intents.ensure_run_scope'), patch('core.final_source_intents.row_in_scope', return_value=True), patch('core.final_source_intents.read_download_manifest', return_value={'rows': downloads}):
            record_source_intent_review(tmp, child='B1', source_index=1, role='excluded_wrong_variant', reason='Human confirmed natural wood in white child')
            self.assertEqual(1, len(_current_source_intent_reviews(Path(tmp), downloads)))
            downloads[0]['source_sha256'] = 'b' * 64
            self.assertEqual({}, _current_source_intent_reviews(Path(tmp), downloads))

    def test_object_membership_conflict_is_isolated_to_affected_sources(self):
        from core.visual_semantics import _validate_observations
        row = {'source_id': 'a', 'role_guess': 'scene', 'view_coverage': 'complete', 'has_dimension_lines': False, 'has_callouts_or_panels': False,
               'physical_views': [current_physical_view(region=[.1, .1, .9, .9], object_id='drawer')],
               'confidence': .9, 'visible_numbers_or_units': [], 'evidence': [], 'text_observations': [], 'measurements': [],
               'variant_identity': {'status': 'unknown', 'observed_color': '', 'reason': 'Occluded', 'conflicts': []},
               'objects': [{'object_id': 'drawer', 'kind': 'drawer', 'state': 'open', 'visibility': 'visible',
                            'sale_membership': 'product', 'membership_evidence': [{'fact_id': 'product.specs.drawers', 'quote': '2 drawers'}], 'relations': []}]}
        other, clear = copy.deepcopy(row), copy.deepcopy(row)
        other['source_id'], other['objects'][0]['sale_membership'] = 'b', 'staging'
        clear['source_id'], clear['objects'][0]['object_id'] = 'c', 'frame'
        clear['physical_views'][0]['evidence'][0]['object_id'] = 'frame'
        rows = _validate_observations([row, other, clear], ['a', 'b', 'c'], {'product.specs.drawers': '2 drawers'})
        self.assertEqual(['drawer'], rows['a']['object_identity_conflicts'])
        self.assertEqual(['drawer'], rows['b']['object_identity_conflicts'])
        self.assertEqual([], rows['c']['object_identity_conflicts'])


if __name__ == '__main__':
    unittest.main()
