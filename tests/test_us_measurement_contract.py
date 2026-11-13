from __future__ import annotations

import unittest
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.text_evidence import extract_measurements, us_measurement_text, measurement_values_match
from tests.current_image_contract_fixture import current_product_feature
from core.template_field_values import template_dimensions_from_facts
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
        for source, target in [('½ in', '0.5 in'), ('¼ in', '0.25 in'), ('¾ in', '0.75 in'), ('3½ in', '3.5 in'), ('-3½ in', '-3.5 in'), ('½ x 3½ in', '0.5 x 3.5 in')]:
            self.assertTrue(measurement_values_match(source, target), source)
        self.assertTrue(measurement_values_match('5 ft 6 in', '66 in'))
        self.assertTrue(measurement_values_match('20 ft', '240 in'))
        self.assertFalse(measurement_values_match('-1.2 kg', '1.2 kg'))
        self.assertTrue(measurement_values_match('2-4 cm', '0.79-1.57 in'))
        self.assertEqual('39.37 L x 19.69 W x 15.75 H in', us_measurement_text('100 L x 50 W x 40 H cm'))
        for source, candidate, matches in [('\u2264 6"', '6 in', False), ('\u2264 6"', 'up to 6 in', True),
                                            ('>= 6 in', 'at least 6 in', True), ('no more than 6 in', '<=6 in', True),
                                            ('6-8 in', '6 x 8 in', False), ('<6 in', '\u2264 6"', False),
                                            ('Under Bed 6 in', 'Under-bed 6 in', True)]:
            with self.subTest(source=source, candidate=candidate):
                self.assertEqual(matches, measurement_values_match(source, candidate))
        for invalid in ('1/0 in', '1//2 in', '1/2/3 in'):
            with self.assertRaises(ValueError):
                extract_measurements(invalid)
        self.assertEqual([], extract_measurements('100/150/350/500/750/1000 LEDs; 300/600/900 tips'))
        self.assertTrue(measurement_values_match('100/150/350 LEDs, height 7 ft', '84 in'))

    def test_template_accepts_inline_and_separate_units(self):
        from tests.four_stage_fixture import verify_selected_measurements
        verify_selected_measurements(self)
        from tests.statement_measurement_fixture import verify_statement_measurements
        for annotation_mode in ('text_only','declared_diagram'):
            with self.subTest(annotation_mode=annotation_mode):verify_statement_measurements(self,annotation_mode=annotation_mode)
        from products.generic_extractors import extract_specs_by_fields
        from tests.four_category_fixture import verify_dimension_axes
        verify_dimension_axes(self)
        facts = extract_specs_by_fields({'productDetails': {'Item Dimensions L x W x H': '100 x 50 x 40 cm'}}, {'dimensions': ('Item Dimensions L x W x H',)})
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

    def test_equal_values_keep_their_source_properties(self):
        claims = compact_product_claims({'specs': {'number_of_doors': 2, 'number_of_drawers': 2}, 'description': 'Two separate storage sections.'})
        self.assertEqual(3, len(claims))
        self.assertEqual(3, len({r['field_path'] for r in claims}))
        height = compact_product_claims({'specs': {'height': '100', 'height_unit': 'cm'}})
        self.assertEqual(1, len(height))
        self.assertEqual('height: 39.37 in', height[0]['text'])
        from core.product_family import fact_statement_issues, whole_part_counts
        counts = {'number_of_shelves': {'status': 'confirmed', 'value': 10}}
        local = 'The interior holds four shelves, and the side adds six shelves.'
        self.assertEqual([], whole_part_counts(local, r'shel(?:f|ves)'))
        self.assertEqual([], fact_statement_issues('Ten shelves: ' + local, counts))
        self.assertEqual([], fact_statement_issues('The interior holds four shelves; the sides add six shelves.', counts))
        self.assertEqual([], fact_statement_issues('Side: six shelves.', counts))
        actual_description = ('The single mirrored door provides a clear reflection for grooming, while '
                              'the interior holds four shelves and the sides add six open shelves, for ten shelves in total.')
        self.assertEqual(['10'], whole_part_counts(actual_description, r'shel(?:f|ves)'))
        self.assertEqual([], fact_statement_issues(actual_description, counts))
        for verb in ('holds', 'contains', 'includes', 'has', 'adds', 'features'):
            with self.subTest(local_verb=verb):
                self.assertEqual([], fact_statement_issues(f'The left compartment {verb} four shelves.', counts))
        for text in ('Four shelves.', 'The cabinet has four shelves.',
                     'The interior is spacious. The cabinet contains four shelves.',
                     'The sides add storage. The cabinet contains six shelves.',
                     'Ten shelves; the cabinet holds four shelves.'):
            with self.subTest(whole_count=text):
                self.assertEqual(['number_of_shelves'], fact_statement_issues(text, counts))
        self.assertEqual(['number_of_shelves'], fact_statement_issues('Ten shelves.', {
            'number_of_shelves': {'status': 'conflicted', 'value': None}}))

    def test_layout_language_does_not_authorize_literal_copy(self):
        _reject_renderable_copy_instruction('Place the title above the product with generous spacing.', 'direction')
        with self.assertRaises(VisualDesignKitCompileError):
            _reject_renderable_copy_instruction('Write the title: Best Product', 'direction')

    def test_local_failure_is_current_evidence_without_remote_observation(self):
        from core.image_qa import _evaluate
        from core.qa_evidence import evidence_is_current
        from tests.test_qa_lite_v1 import _task
        task, candidate = _task('main'), {'candidate_path': 'image.png', 'candidate_sha256': 'c' * 64}
        with tempfile.TemporaryDirectory() as tmp, patch('core.image_qa._local_gates', return_value=[{'gate': 'image_integrity', 'status': 'fail', 'evidence': 'Broken image'}]), patch('core.vision_gemini_client.gemini_stream_generate', side_effect=AssertionError('Broken images must stop before paid QA')) as remote:
            evidence = _evaluate(Path(tmp), object(), task, candidate)
            self.assertTrue(evidence_is_current(evidence, task, candidate))
            self.assertEqual('fail', evidence['automatic_decision'])
            remote.assert_not_called()

    def test_source_disposition_is_explicit_and_sha_bound(self):
        from tests.recovery_contract_fixture import verify_observation_scope
        verify_observation_scope(self)
        from core.final_source_intents import record_source_intent_review, _current_source_intent_reviews
        downloads = [{'status': 'ok', 'child': 'B1', 'index': 1, 'source_sha256': 'a' * 64}]
        with tempfile.TemporaryDirectory() as tmp, patch('core.final_source_intents.ensure_run_scope'), patch('core.final_source_intents.row_in_scope', return_value=True), patch('core.final_source_intents.read_download_manifest', return_value={'rows': downloads}):
            record_source_intent_review(tmp, child='B1', source_index=1, role='excluded_wrong_variant', reason='Human confirmed natural wood in white child')
            self.assertEqual(1, len(_current_source_intent_reviews(Path(tmp), downloads)))
            record_source_intent_review(tmp, child='B1', source_index=1, role='reobserve', reason='Recheck drawn markings versus product finish')
            self.assertEqual('reobserve', next(iter(_current_source_intent_reviews(Path(tmp), downloads).values()))['role'])
            downloads[0]['source_sha256'] = 'b' * 64
            self.assertEqual({}, _current_source_intent_reviews(Path(tmp), downloads))

    def test_unsupported_included_accessory_is_isolated_to_affected_source(self):
        from core.visual_semantics import _validate_observations
        row = {'source_id': 'a', 'role_guess': 'scene', 'evidence_gaps': [], 'text_gaps': [],
               'reference_purposes': ['appearance'], 'has_dimension_lines': False, 'has_callouts_or_panels': False,
               'product_features': [current_product_feature(object_id='drawer')], 'product_extent': 'whole_view',
               'confidence': .9, 'visible_numbers_or_units': [], 'evidence': [], 'text_observations': [], 'measurements': [],
               'variant_identity': {'status': 'unknown', 'observed_color': '', 'reason': 'Occluded', 'conflicts': []},
               'objects': [{'object_id': 'drawer', 'kind': 'drawer', 'state': 'open', 'visibility': 'visible',
                            'sale_membership': 'product', 'membership_evidence': [{'fact_id': 'product.specs.drawers', 'quote': '2 drawers'}]}]}
        other, clear = copy.deepcopy(row), copy.deepcopy(row)
        other['source_id'], other['objects'][0]['sale_membership'] = 'b', 'included_accessory'
        other['objects'][0]['membership_evidence'] = []
        clear['source_id'], clear['objects'][0]['object_id'] = 'c', 'frame'
        clear['product_features'][0]['object_id'] = 'frame'
        rows = _validate_observations([row, other, clear], ['a', 'b', 'c'], {'product.specs.drawers': '2 drawers'})
        self.assertEqual('success', rows['a']['status'])
        self.assertEqual('failed', rows['b']['status'])
        self.assertIn('sales membership requires product evidence', rows['b']['error'])
        self.assertEqual('success', rows['c']['status'])


if __name__ == '__main__':
    unittest.main()
