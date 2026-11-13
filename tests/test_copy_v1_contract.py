import json
import unittest
from unittest.mock import patch

from core.copy_writer import (
    CopyWriterConfig,
    CopyWriterError,
    _parse_copy_response,
    _rewrite_listing_copy_with_openai,
)
from core.copy_polish import _validate_artifact_provenance, CopyPolishError


def _body(payload: dict) -> str:
    return json.dumps({"choices": [{"message": {"content": json.dumps(payload)}}]})


class CopyV1ContractTests(unittest.TestCase):
    def test_parent_artifact_uses_optional_parent_highlight_contract(self) -> None:
        from core.copy_writer import _reference_brand_candidates
        brands = _reference_brand_candidates(target_brand='Shop', source_title='Example Brand Artificial Tree',
            source_bullets=['DECORATE YOUR WAY: trim the tree'], source_description='',
            product_specific={'manufacturer':'Example Brand'}, market_context={})
        self.assertIn('Example Brand', brands)
        self.assertNotIn('DECORATE', brands)
        from tests.continuity_contract_fixture import verify_copy_retry_owner
        verify_copy_retry_owner(self)
        from tests.unit_work_fixture import verify_copy_units
        verify_copy_units(self)
        from tests.feedback_fix_fixture import verify_parent_count
        verify_parent_count(self)
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
        artifact = {
            "rows": {"__parent__": row},
            "groups": [],
            "parent_model_request_fingerprint": "parent-fingerprint",
        }
        from core.copy_polish import _fingerprint, _child_copy_payload
        artifact['parent_child_copy_fingerprint'] = _fingerprint(_child_copy_payload(artifact['rows']))
        with self.assertRaises(CopyPolishError):
            _validate_artifact_provenance(artifact)
        from core.template_engine import _copy_v1_for_row, TemplateEngineError
        row["item_highlights"] = ["A" * 75 + " Storage", "B" * 75 + " Shelving"]
        with self.assertRaises(CopyPolishError):
            _validate_artifact_provenance(artifact)
        with self.assertRaises(TemplateEngineError):
            _copy_v1_for_row(artifact, row_type="Parent", sku="P", asin="B1")
        for highlights in ([], ["Wall Mounted Storage", "Adjustable Shelf"]):
            row["item_highlights"] = highlights
            _validate_artifact_provenance(artifact)
            self.assertEqual(highlights, _copy_v1_for_row(artifact, row_type="Parent", sku="P", asin="B1")[1])

        import tempfile
        from pathlib import Path
        from core.copy_polish import _write_fragment, _load_fragment, _copy_groups
        row['item_highlights'] = []
        with tempfile.TemporaryDirectory() as tmp:
            _write_fragment(Path(tmp), 'parent', row)
            self.assertEqual(row, _load_fragment(Path(tmp), 'parent', row_type='Parent'))
            self.assertIsNone(_load_fragment(Path(tmp), 'parent', row_type='Child'))
        children = [{'asin': 'B1', 'title': 'Storage Cabinet', 'specs': {'material': 'Wood', 'color': 'White'}},
                    {'asin': 'B2', 'title': 'Storage Cabinet', 'specs': {'material': 'Wood', 'color': 'Blue'}}]
        self.assertEqual(1, len(_copy_groups(children)))
        for field, value in (('material', 'Metal'), ('sold_unit_count', 2), ('number_of_doors', 3)):
            altered = {**children[1], 'specs': {**children[1]['specs'], field: value}}
            self.assertEqual(2, len(_copy_groups([children[0], altered])))

        from core import copy_polish
        from core.plugin import load_plugin
        from core.io import write_json, read_json
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / 'source' / 'product_family_v3.json', {'family': {'children': children}})
            child_copy = {**row, 'item_highlights': ['Wall Mounted Storage', 'Adjustable Shelf']}
            with patch.multiple(copy_polish,
                load_job=lambda _: {}, load_template_env=lambda *a: {},
                read_product_family=lambda _: {'family': {'children': children}},
                copy_request_fingerprint=lambda *a, **k: 'request',
                _model_request_fingerprint=lambda **k: k['row_type'],
                _group_request_fingerprint=lambda **k: k['row_type'],
                _current_artifact=lambda *a, **k: None,
            ), patch.object(copy_polish, '_rewrite_group', side_effect=[child_copy, row]) as rewrite:
                copy_polish.run_copy_polish(job_dir=root, plugin=load_plugin('medicine_cabinet'), limit=2)
                data = read_json(root / 'reports' / 'copy_v1.json')
                parent_input = rewrite.call_args_list[-1].kwargs['source']['description']
                self.assertIn(child_copy['description'], parent_input)
                self.assertEqual(_fingerprint(_child_copy_payload(data['rows'])), data['parent_child_copy_fingerprint'])
                self.assertEqual('B1', data['groups'][0]['source_asin'])
                self.assertTrue(all(value['copy_group_source_asin'] == 'B1' for key, value in data['rows'].items() if key != '__parent__'))
                copy_polish.run_copy_polish(job_dir=root, plugin=load_plugin('medicine_cabinet'), limit=2)
                self.assertEqual(2, rewrite.call_count)  # Both child and empty-highlight parent fragments reused.
                data['rows'][data['child_map']['B1']]['description'] += ' Revised child text.'
                with self.assertRaisesRegex(CopyPolishError, 'current child copy'):
                    _validate_artifact_provenance(data)
        from core.copy_writer import _validate_copy_compliance
        for negative in ('Unlit design for your own lights.', 'Lights are not included.', 'No lights or ornaments are included.'):
            with self.assertRaisesRegex(CopyWriterError, 'lighting inclusion'):
                _validate_copy_compliance({'title':'Cactus Christmas Tree','description':negative},category='Artificial Tree',
                    product_specific={'tree_type':'Cactus','_child_facts':[{'light_count':90},{'light_count':120}]})
        with self.assertRaisesRegex(CopyWriterError, 'subtype'):
            _validate_copy_compliance({'title':'Artificial Christmas Tree'},category='Artificial Tree',product_specific={'tree_type':'Cactus'})
        with self.assertRaisesRegex(CopyWriterError, 'lighting inclusion'):
            _validate_copy_compliance({'title':'Pre-lit Christmas Tree'},category='Artificial Tree',
                product_specific={'_child_facts':[{'light_count':90},{'light_count':0}]})

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
        result = _parse_copy_response(_body(payload), brand="safeplus", product_specific={'width':'24 inches'})
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
        result = _parse_copy_response(_body(separated), brand="safeplus", product_specific={'width':'24 inches'})
        self.assertEqual(
            ["Adjustable Shelf", "Mirrored Door", "Wall-Mounted Storage"],
            result["item_highlights"],
        )
        parent_payload = dict(separated)
        parent_payload["item_highlights"] = ["Green"]
        with self.assertRaises(CopyWriterError):
            _parse_copy_response(_body(parent_payload), brand="safeplus", row_type="parent", product_specific={'width':'24 inches'})
        parent_payload["item_highlights"] = []
        parent_payload['bullets'] = []
        parent_result = _parse_copy_response(_body(parent_payload), brand="safeplus", row_type="parent", product_specific={'width':'24 inches'})
        self.assertEqual([], parent_result["item_highlights"])
        self.assertEqual([], parent_result['bullets'])

    def test_forbidden_claim_is_not_laundered(self) -> None:
        from tests.audit_copy_fixture import verify_copy_measurements
        from tests.feedback_fix_fixture import verify_function_compound
        verify_function_compound(self)
        verify_copy_measurements(self)
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
        # Real canary: total and component capacities are distinct source-backed facts.
        facts = {'load_capacity': '120 lbs', 'item_weight': '22 lbs', 'source_description':
                 'Weight Capacity of Each Shelf: 22lbsWeight Capacity of Drawer: 11 lbs'
                 'Weight Capacity of Top: 66 lbsTotal Weight Capacity: 120 lbs'}
        payload['bullets'][0] = 'Load Capacity: Supports up to 120 lbs'
        payload['description'] = 'Total load capacity is 120 pounds, with 66 pounds for the top, 22 pounds per shelf, and 11 pounds for the drawer. The cabinet weighs 22 pounds.'
        _parse_copy_response(_body(payload), product_specific=facts)
        for wrong in ('Total load capacity is 66 pounds.', 'Load capacity is 120 pounds, with 11 pounds per shelf and 22 pounds for the drawer.'):
            with self.subTest(wrong=wrong), self.assertRaisesRegex(CopyWriterError, 'capacity value'):
                _parse_copy_response(_body({**payload, 'description': wrong}), product_specific=facts)

        from core.copy_writer import _validate_copy_compliance
        with self.assertRaisesRegex(CopyWriterError,'quantity scope'):
            _validate_copy_compliance({'description':'Three rattan-wrapped trunks each hold three square pruned boxwood sections.'},
                category='Artificial Tree',product_specific={'sold_unit_count':2,'material':'Polyethylene'})
        _validate_copy_compliance({'description':'Three trunks topped with three square boxwood forms.'},
            category='Artificial Tree',product_specific={'structure':'Three trunks topped with three square boxwood forms.'})
        _validate_copy_compliance({'description':'Each tree measures 13.5 inch depth by 13.5 inch width by 36 inch height.'},
            category='Artificial Tree',product_specific={'item_depth':'13.5 inches','width':'13.5 inches','height':'36 inches'})
        _validate_copy_compliance({'description':'Three trunks, each wrapped in rattan, topped with three square forms.'},
            category='Artificial Tree',product_specific={'structure':'Three trunks, each wrapped in rattan, topped with three square forms.'})
        for value in ('Not specified', False, 0, -1000, '-1000 lbs', '1000', 'not rated for 1000 lbs', float('inf')):
            with self.subTest(capacity=value), self.assertRaises(CopyWriterError):
                _validate_copy_compliance({'title': 'Storage Cabinet', 'description': 'Supports up to 1000 lbs'},
                    category='bathroom_cabinet', product_specific={'weight_capacity': value})
        _validate_copy_compliance({'title': 'Storage Cabinet', 'description': 'Weight capacity: 22.04 lbs'},
                    category='bathroom_cabinet', product_specific={'weight_capacity': '10 kg'})

        for claim, facts, accepted in (
            ('waterproof', {'waterproof': False, 'source_description': 'Waterproof cabinet'}, False),
            ('waterproof', {'waterproof': True}, True),
            ('waterproof', {'description': 'This cabinet is not waterproof'}, False),
            ('waterproof', {'waterproof': 'unknown'}, False),
            ('waterproof', {'waterproof': 'water-resistant'}, False),
            ('recyclable packaging', {'packaging': {'recyclable': True}}, True),
            ('shatterproof', {'glass': 'tempered'}, False),
            ('shatterproof', {'shatterproof': True}, True),
            ('biodegradable', {'eco': True}, False),
            ('recyclable', {'packaging': {'recyclable': True}}, False),
            ('recyclable', {'recyclable': True}, True),
            ('rust-proof', {'rust': 'resistant'}, False),
        ):
            with self.subTest(claim=claim, facts=facts):
                output = {'title': 'Bathroom Cabinet with Door', 'bullets': ['Adjustable Shelf'], 'description': claim}
                if accepted:
                    _validate_copy_compliance(output, category='bathroom_cabinet', product_specific=facts)
                else:
                    with self.assertRaises(CopyWriterError):
                        _validate_copy_compliance(output, category='bathroom_cabinet', product_specific=facts)

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
        import tempfile
        from pathlib import Path
        from dataclasses import replace
        from core.copy_writer import _post_chat_completion
        with tempfile.TemporaryDirectory() as tmp, patch('core.copy_writer.urllib.request.urlopen') as transport, \
             patch('core.batch_ledger.admit_paid_request',return_value='mock-network-admission'):
            transport.return_value.__enter__.return_value.read.return_value = _body(invalid).encode()
            traced = replace(config, trace_dir=Path(tmp), api_key='secret-not-in-diagnostics')
            request = post.call_args_list[0].args[1]
            self.assertEqual(_body(invalid), _post_chat_completion(traced, request))
            recorded = list(Path(tmp).glob('*.response.txt'))
            self.assertEqual(1, len(recorded))
            self.assertEqual(_body(invalid), recorded[0].read_text(encoding='utf-8'))
            self.assertNotIn(traced.api_key, ''.join(p.read_text(encoding='utf-8') for p in Path(tmp).rglob('*') if p.is_file()))
            with patch.object(Path, 'write_text', side_effect=OSError('disk error')), self.assertLogs('core.copy_writer', level='WARNING'):
                self.assertEqual(_body(invalid), _post_chat_completion(traced, request))
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
        self.assertIn(title_only_invalid["title"], title_repair["invalid_copy_to_repair"])
        self.assertIn("title exceeds", title_repair["validation_error"])
        self.assertEqual(['title'],title_repair['failed_fields'])
        self.assertIn("Preserve exact product structure nouns", title_post.call_args_list[1].args[1]["messages"][0]["content"])
        for invalid_parent, repair in (
            ({**title_only_invalid, "item_highlights": []}, {"title": valid["title"]}),
            ({**valid, "item_highlights": ["Green"]}, {"item_highlights": []}),
        ):
            with self.subTest(parent_repair=repair), patch(
                "core.copy_writer._post_chat_completion", side_effect=[_body(invalid_parent), _body(repair)]
            ) as parent_post:
                parent = _rewrite_listing_copy_with_openai(
                    config=config, category="medicine_cabinet", brand="safeplus", row_type="parent",
                    source_title="Wall Mount Medicine Cabinet", source_bullets=[], source_description="",
                    product_specific={"mounting_type": "wall mount", "shelf": "adjustable"},
                )
                self.assertEqual([], parent["item_highlights"])
                self.assertEqual(2, parent_post.call_count)

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
                row_type="parent",
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
        self.assertEqual(['bullets[3]'],bullet_repair['failed_fields'])
        # A mixed length + fact failure repairs both failed fields in one call,
        # while an endpoint's unsolicited edits to good copy are ignored.
        mixed={**valid,'item_highlights':over_budget,'bullets':list(valid['bullets'])}
        mixed['bullets'][2]='Pot Size: The planter stands 31.5 inches tall. '+('Daily storage ' * 10)
        unrequested={**valid,'title':'Unsolicited Changed Title','description':'Unsolicited description'}
        with patch('core.copy_writer._post_chat_completion',side_effect=[_body(mixed),_body(unrequested)]) as repair_post:
            repaired=_rewrite_listing_copy_with_openai(config=config,category='medicine_cabinet',brand='safeplus',row_type='child',
                source_title='Wall Mount Medicine Cabinet',source_bullets=['Adjustable shelf storage'],source_description='',
                product_specific={'mounting_type':'wall mount','shelf':'adjustable'})
        self.assertEqual(valid['title'],repaired['title']);self.assertEqual(valid['description'],repaired['description'])
        self.assertEqual(valid['bullets'],repaired['bullets']);self.assertEqual(2,repair_post.call_count)
        repair_request=json.loads(repair_post.call_args_list[1].args[1]['messages'][1]['content'])
        self.assertEqual(['bullets[2]','item_highlights'],repair_request['failed_fields'])
        with patch(
            "core.copy_writer._post_chat_completion",
            side_effect=[
                _body(highlight_only_invalid),
                _body({"item_highlights": ["Adjustable Shelf"]}),
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
