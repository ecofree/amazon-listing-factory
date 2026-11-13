from __future__ import annotations

import unittest
from pathlib import Path

from openpyxl import Workbook

from core import listing_data, template_engine
from core.plugin import ProductPlugin
from core.template_field_plan import compile_field_coverage, compile_field_decisions
from core.template_engine import FIELD_ALIASES, IMAGE_FIELDS, compile_template_field_plan
from core.template_runtime import template_job_with_defaults


class TemplateFieldPlanContractsTests(unittest.TestCase):
    def test_unknown_template_data_start_row_fails_closed(self) -> None:
        from core.template_field_plan import _conditional_activation
        from core.template_conditions import row_applicability
        columns = {'product_type':'B', 'parentage':'D', 'fulfillment':'EJ'}
        condition = 'AND(Template!$D1="Child",COUNTIF(CONDITION_LIST_1, Template!$EJ1)>0)'
        rules = (columns, {'CONDITION_LIST_1':('fbm',)}, {'shipping':[(True, condition)],
                                                        'unknown':[(True, 'UNSUPPORTED(1)')]}, 'artificial_tree')
        for parentage, channel, needed in [('Parent','FBM',False),('Child','FBM',True),('Child','FBA',False)]:
            with self.subTest(parentage=parentage, channel=channel):
                self.assertEqual({'shipping':needed}, row_applicability(rules, {
                    'product_type':'ARTIFICIAL_TREE','parentage':parentage,'fulfillment':channel}))
        shipping = FIELD_ALIASES['shipping_template'][0]
        self.assertEqual((False,'new_sku_uses_account_shipping_default'),_conditional_activation(shipping,
            values={'::record_action':'Create or Replace (Full Update)'},fields={shipping:1},labels={},aliases=FIELD_ALIASES,
            row_context={'use_default_shipping':True, 'workbook_applies':{shipping:True}}))
        self.assertEqual((True,'template_row_condition'),_conditional_activation(shipping,
            values={'::record_action':'Edit (Partial Update)'},fields={shipping:1},labels={},aliases=FIELD_ALIASES,
            row_context={'use_default_shipping':True, 'workbook_applies':{shipping:True}}))
        args = dict(values={}, fields={}, labels={}, aliases={})
        for value, active in (("No", False), ("Yes", True), (False, False), (True, True), ("", None), (None, None)):
            with self.subTest(battery=value):
                self.assertIs(active, _conditional_activation("num_batteries#1.value", row_context={"contains_battery": value}, **args)[0])
        self.assertIsNone(_conditional_activation("dangerous_goods#1.value", row_context={}, **args)[0])
        self.assertIs(False, _conditional_activation("dangerous_goods#1.value", row_context={"dangerous_goods": "Not Applicable"}, **args)[0])
        for level, active in (('',None),('unknown',None),('unit',False),('case',True)):
            self.assertIs(active,_conditional_activation('package_contains_sku#1.value',row_context={'package_level':level},**args)[0])
        workbook = Workbook()
        sheet = workbook.active
        sheet.cell(7, 1).value = "unknown row content"
        with self.assertRaises(template_engine.TemplateEngineError):
            template_engine._detect_template_data_start_row(sheet, 1)

    def test_template_business_fields_require_explicit_values(self) -> None:
        from tests.continuity_contract_fixture import verify_sku_identifiers
        verify_sku_identifiers(self)
        resolved = template_job_with_defaults({}, env={})
        self.assertIsNone(resolved.get('gtin_exempt'))
        self.assertFalse(resolved.get('dangerous_goods'))
        self.assertFalse(resolved.get('product_id_type'))
        for field in ('brand','manufacturer','country','condition','quantity','fulfillment','inventory_available'):
            self.assertEqual('',resolved[field],field)
        confirmed=template_job_with_defaults({'brand':'safeplus','quantity':200,'gtin_exempt':True},env={})
        self.assertEqual(('safeplus','200',True),(confirmed['brand'],confirmed['quantity'],confirmed['gtin_exempt']))

        for quantity, available in ((0, False), ('0', 'false')):
            values = template_job_with_defaults({'quantity': quantity, 'inventory_available': available}, env={})
            self.assertEqual(('0', 'false'), (values['quantity'], values['inventory_available']))
        self.assertEqual('', template_job_with_defaults({'quantity': '  '}, env={})['quantity'])
        from core.template_field_plan import looks_numeric
        for value in ('NaN', 'inf', '-inf'):
            self.assertFalse(looks_numeric(value))
        quantity_field = FIELD_ALIASES['quantity'][0]
        for value, expected in (('0', 'pass'), ('2', 'pass'), ('1.5', 'invalid_numeric'), ('-1', 'invalid_numeric'), ('NaN', 'invalid_numeric')):
            decisions = compile_field_decisions(fields={quantity_field: 1}, labels={}, aliases=FIELD_ALIASES,
                allowed_values={}, values={quantity_field: value}, sources={}, requirements=[], row_context={}, invalid_candidates={})
            self.assertEqual(expected, decisions[0]['validation_status'])
        self.assertTrue(looks_numeric('1.5', field='item_dimensions.length.value'))
        for alias, invalid, valid in [('item_weight', 'NaN', '22.5'), ('number_of_doors', 'many', '2'),
                                     ('number_of_shelves', '-2.5', '0'), ('max_weight', 'inf', '300'),
                                     ('number_of_items', '0', '1')]:
            field = FIELD_ALIASES[alias][0]
            for value, expected in ((invalid, 'invalid_numeric'), (valid, 'pass')):
                decisions = compile_field_decisions(fields={field: 1}, labels={}, aliases=FIELD_ALIASES,
                    allowed_values={}, values={field: value}, sources={}, requirements=[], row_context={}, invalid_candidates={})
                self.assertEqual(expected, decisions[0]['validation_status'], (alias, value))

        from core.template_field_plan import _known_enum_value,_conditional_activation
        self.assertEqual('Fulfillment by Merchant (Default)',_known_enum_value('fulfillment','FBM',['Fulfillment by Merchant (Default)']))
        self.assertEqual('No',_known_enum_value('batteries_included',False,['Yes','No']))
        inventory=FIELD_ALIASES['inventory_available'][0]
        self.assertIs(False,_conditional_activation(inventory,values={quantity_field:'200'},
            fields={quantity_field:1,inventory:2},labels={},aliases=FIELD_ALIASES,row_context={})[0])
        contract = template_engine._assert_submit_ready_job_contract
        for exempt, count in ((True, 2), (False, 1)):
            contract({'gtin_exempt': exempt, 'product_id': '123456789012', 'product_id_type': 'UPC'}, mode='submit_ready', child_count=count)
        with self.assertRaisesRegex(template_engine.TemplateEngineError, 'multi-child'):
            contract({'gtin_exempt': False, 'product_id': '123456789012', 'product_id_type': 'UPC'}, mode='submit_ready', child_count=2)
        contract({'gtin_exempt': False}, mode='draft', child_count=2)
        from tempfile import TemporaryDirectory
        from core.job import create_job,update_business_inputs,load_job,JobError,business_for_sku
        from core.plugin import load_plugin
        from core.io import write_json,file_sha256
        from scripts.factory import build_parser
        with TemporaryDirectory() as tmp:
            root=Path(tmp);profile=root/'business.json'
            data={'schema':'business-input-v2','scope':{'brand':'safeplus','marketplace':'US','seller_id':'fixture',
                'category_id':'artificial_tree','seed_asin':'B000000001'},'source':'Synthetic operator evidence',
                'valid_until':'2099-01-01T00:00:00+00:00','values':{'contains_battery':False,'gtin_exempt':True},
                'sku_values':{'T-B000000001':{'quantity':0,'inventory_available':False}}}
            write_json(profile,data)
            job=create_job(plugin=load_plugin('artificial_tree'),seed_asin='B000000001',brand='safeplus',sku_prefix='T',
                out_root=root/'new',business_input_path=str(profile),seller_id='fixture')
            self.assertEqual(0,business_for_sku(load_job(job),'T-B000000001',submit_ready=True)['quantity'])
            self.assertEqual('',business_for_sku(load_job(job),'T-B000000002',submit_ready=True)['quantity'])
            self.assertIs(False,load_job(job)['contains_battery'])
            expired=load_job(job);expired['business_input']['valid_until']='2000-01-01T00:00:00+00:00'
            with self.assertRaises(JobError):template_job_with_defaults(expired,env={})
            before=file_sha256(job/'job.json')
            update_business_inputs(job,profile,expected_job_sha256=before,decision_id='one',reason='Verified exact input')
            after=file_sha256(job/'job.json')
            self.assertEqual('already_applied',update_business_inputs(job,profile,expected_job_sha256=before,
                decision_id='one',reason='Verified exact input')['status'])
            self.assertEqual(after,file_sha256(job/'job.json'))
            with self.assertRaises(JobError):update_business_inputs(job,profile,expected_job_sha256=before,decision_id='two',reason='Stale')
            args=build_parser().parse_args(['update-business-inputs','--job',str(job),'--input',str(profile),
                '--expected-job-sha256',after,'--decision-id','two','--reason','Checked'])
            self.assertEqual('two',args.decision_id)
            data['scope'].pop('seed_asin');write_json(profile,data)
            with self.assertRaisesRegex(JobError,'Inventory evidence'):
                create_job(plugin=load_plugin('artificial_tree'),seed_asin='B000000001',brand='safeplus',sku_prefix='T',
                    out_root=root/'bad',business_input_path=str(profile),seller_id='fixture')
            self.assertFalse((root/'bad').exists())
            from core.job import read_business_input
            from core.paths import FACTORY_ROOT
            target={**load_job(job),'seller_id':'safeplus'}
            approved=read_business_input(FACTORY_ROOT/'configs/business_profiles/safeplus_us_artificial_tree.json',target)
            target['business_input']=approved
            self.assertEqual(200,business_for_sku(target,'T-B000000001',submit_ready=True)['quantity'])
            self.assertEqual('same_as_list_price',business_for_sku(target,'T-B000000002',submit_ready=True)['price_policy'])
            self.assertIs(approved['values']['batteries_required'], False)
            from core.template_field_values import sourced_template_attributes
            child = {'asin': target['seed_asin']}
            raw = Path(job)/'source/apify_raw/US'/(child['asin']+'.json')
            for values, expected in [([], {}), (['False','No'], {'batteries_required':'No'}),
                                     (['Yes','No'], {'_source_field_conflicts':{'batteries_required':['Yes','No']}})]:
                write_json(raw, {'asin':child['asin'],'attributes':[{'key':'Batteries Required','value':v} for v in values]})
                family = {'source':{'raw_sha256':{child['asin']:file_sha256(raw)}},'family':{'marketplace':'US'}}
                self.assertEqual(expected, sourced_template_attributes(job,family,child))
            from core.job import default_business_input
            for category in ('bed_frame','bathroom_cabinet','medicine_cabinet','future_category_fixture'):
                scope={**target,'category_id':category}
                policy=read_business_input(default_business_input(scope),scope)
                self.assertEqual({'batteries_required':False},policy['values'])
                self.assertEqual(category,policy['scope']['category_id'])
            with self.assertRaises(JobError):read_business_input(FACTORY_ROOT/'configs/business_profiles/safeplus_us_artificial_tree.json',{**target,'seller_id':'other'})
            approved['scope']['seed_asin']=target['seed_asin']
            approved['sku_values']={'T-B000000002':{'quantity':0}}
            self.assertEqual(0,business_for_sku(target,'T-B000000002',submit_ready=True)['quantity'])

    def test_item_highlights_require_first_class_copy_list(self) -> None:
        self.assertEqual("", template_engine.item_highlights_text({"bullets": ["Sturdy Steel Frame: Built for stable everyday use in a family bedroom"]}))
        highlights = ["Sturdy Steel Frame", "Built-In Guardrails", "Under-Bed Space"]
        self.assertEqual("Sturdy Steel Frame, Built-In Guardrails, Under-Bed Space", template_engine.item_highlights_text({"item_highlights": highlights}))
        packaged = listing_data.row(
            row_type="Child", sku="B1", asin="B1",
            copy={"title": "Twin Metal Loft Bed", "item_highlights": highlights, "bullets": ["x"] * 5, "description": "d" * 700},
        )
        self.assertEqual(highlights, packaged["copy"]["item_highlights"])
        field = FIELD_ALIASES["item_highlight"][0]
        template = template_engine.TemplateInfo(
            path=Path("template.xlsm"), sheet="Template", max_row=20, max_col=1,
            fields={field: 1}, labels={field: "Item Highlight"}, required=[], existing_rows=[],
        )
        from core.template_field_plan import compile_field_requirements
        for mode in ("draft", "submit_ready"):
            requirements = compile_field_requirements(fields=template.fields, labels=template.labels, aliases=FIELD_ALIASES,
                template_requirements=[{"field": field, "required": "Required"}], template_mode=mode)
            for row_type, expected in (("Parent", "pass"), ("Child", "missing_required")):
                decisions = compile_field_decisions(fields=template.fields, labels=template.labels, aliases=FIELD_ALIASES,
                    allowed_values={}, values={}, sources={}, requirements=requirements,
                    row_context={"row_type": row_type}, invalid_candidates={})
                self.assertEqual(expected, decisions[0]["validation_status"])
        coverage = compile_field_coverage(
            fields=template.fields,
            labels=template.labels,
            rows=[{
                "row_type": "Child",
                "sku": "B1",
                "field_values": {},
                "field_decisions": [{
                    "field": field,
                    "validation_status": "missing_required",
                    "requirement_source": "factory",
                    "requirement": "Required",
                    "active": True,
                }],
            }],
            reference={},
        )
        self.assertEqual(1, coverage["business_required_missing_count"])

    def test_field_plan_splits_weight_value_and_unit(self) -> None:
        from tests.audit_delivery_fixture import verify_zero_and_template_validation
        verify_zero_and_template_validation(self)
        from core.template_field_plan import field_expects_number, compile_field_requirements
        actual_type='unit_count[marketplace_id=ATVPDKIKX0DER]#1.type[language_tag=en_US].value'
        self.assertFalse(field_expects_number(actual_type))
        self.assertTrue(field_expects_number('unit_count[marketplace_id=ATVPDKIKX0DER]#1.value'))
        decision=compile_field_decisions(fields={actual_type:1},labels={},aliases={},allowed_values={actual_type:['Count']},
            values={actual_type:'Count'},sources={},requirements=[],row_context={},invalid_candidates={})
        self.assertEqual('pass',decision[0]['validation_status'])
        price=FIELD_ALIASES['list_price'][0]
        for required in ('Required','Optional'):
            requirements=compile_field_requirements(fields={price:1},labels={},aliases=FIELD_ALIASES,
                template_requirements=[{'field':price,'required':required}],template_mode='submit_ready')
            self.assertEqual(required,requirements[0]['required'])
        value_field = FIELD_ALIASES["max_weight"][0]
        unit_field = FIELD_ALIASES["max_weight_unit"][0]
        product_id_field = FIELD_ALIASES["product_id"][0]
        unknown_conditional = "occasion_type[marketplace_id=ATVPDKIKX0DER][language_tag=en_US]#1.value"
        template = template_engine.TemplateInfo(
            path=Path("template.xlsm"),
            sheet="Template",
            max_row=20,
            max_col=6,
            fields={
                FIELD_ALIASES["sku"][0]: 1,
                value_field: 2,
                unit_field: 3,
                product_id_field: 4,
                unknown_conditional: 5,
            },
            labels={},
            required=[
                {"field": unit_field, "label": "Weight Unit", "required": "Conditionally Required"},
                {"field": product_id_field, "label": "Product ID", "required": "Conditionally Required"},
                {"field": unknown_conditional, "label": "Occasion", "required": "Conditionally Required"},
            ],
            existing_rows=[],
        )
        plugin = ProductPlugin(category_id="bed_frame", root=Path("."), manifest={})
        row = {
            "sku": "B000000001",
            "row_type": "Child",
            "parent_sku": "PARENT",
            "copy": {"title": "Metal Loft Bed", "bullets": [], "description": ""},
            "attributes": {
                "item_count": "1",
                "package_quantity": "1",
                "max_weight": "330 Pounds",
            },
            "compliance": {"gtin_exempt": True},
            "offer": {},
        }
        plan = compile_template_field_plan(template=template, plugin=plugin, row_data=row)
        values = plan["field_values"]
        self.assertEqual("330", values[value_field])
        self.assertEqual("Pounds", values[unit_field])
        decisions = {item["field"]: item for item in plan["field_decisions"]}
        self.assertTrue(decisions[unit_field]["active"])
        self.assertEqual("paired_value_present", decisions[unit_field]["activation_reason"])
        self.assertFalse(decisions[product_id_field]["active"])
        self.assertIsNone(decisions[unknown_conditional]["active"])
        self.assertEqual("conditional_risk", decisions[unknown_conditional]["validation_status"])
        coverage = compile_field_coverage(fields=template.fields, labels={}, rows=[{'sku':row['sku'],**plan}],reference={})
        self.assertEqual('warning',template_engine._template_coverage_audit(coverage,mode='draft')[0]['severity'])
        self.assertEqual('error',template_engine._template_coverage_audit(coverage,mode='submit_ready')[0]['severity'])
        missing_exemption = compile_template_field_plan(template=template,plugin=plugin,row_data={**row,'compliance':{}})
        missing_id = next(d for d in missing_exemption['field_decisions'] if d['field']==product_id_field)
        self.assertIsNone(missing_id['active']);self.assertEqual('gtin_exemption_unknown',missing_id['activation_reason'])
        import tempfile
        from core.io import file_sha256
        with tempfile.TemporaryDirectory() as tmp:
            from dataclasses import replace
            path=Path(tmp)/'template.xlsm';path.write_bytes(b'current template identity');template=replace(template,path=path)
            record={'template_sha256':file_sha256(path),'sku':row['sku'],'product_type':plugin.product_type,
                'facts_revision':'a'*64,'field':unknown_conditional,'applicable':False,'reason':'This SKU has no occasion restriction',
                'source':'merchant product specification'}
            explicit=compile_template_field_plan(template=template,plugin=plugin,row_data=row,
                conditional_dispositions=[record],facts_revision='a'*64)
            resolved=next(d for d in explicit['field_decisions'] if d['field']==unknown_conditional)
            self.assertIs(False,resolved['active']);self.assertEqual('pass',resolved['validation_status'])
            for changed in ('facts','template'):
                if changed=='template':path.write_bytes(b'new template identity')
                with self.assertRaisesRegex(ValueError,'stale'):
                    compile_template_field_plan(template=template,plugin=plugin,row_data=row,
                        conditional_dispositions=[record],facts_revision='b'*64 if changed=='facts' else 'a'*64)
            path.write_bytes(b'current template identity')
            active=compile_template_field_plan(template=template,plugin=plugin,row_data=row,
                conditional_dispositions=[{**record,'applicable':True}],facts_revision='a'*64)
            self.assertEqual('missing_required',next(d for d in active['field_decisions'] if d['field']==unknown_conditional)['validation_status'])

        color_field = FIELD_ALIASES["color"][0]
        hardware_color_field = FIELD_ALIASES["hardware_color"][0]
        parent_decisions = compile_field_decisions(
            fields={color_field: 1, hardware_color_field: 2},
            labels={},
            aliases=FIELD_ALIASES,
            allowed_values={},
            values={},
            sources={},
            requirements=[
                {"field": color_field, "required": "Conditionally Required"},
                {"field": hardware_color_field, "required": "Conditionally Required"},
            ],
            row_context={"row_type": "Parent", "variation_theme": "Color"},
            invalid_candidates={},
        )
        parent_by_field = {item["field"]: item for item in parent_decisions}
        self.assertFalse(parent_by_field[color_field]["active"])
        self.assertFalse(parent_by_field[hardware_color_field]["active"])
        self.assertEqual("pass", parent_by_field[color_field]["validation_status"])
        hardware=compile_field_decisions(fields={hardware_color_field:1},labels={},aliases=FIELD_ALIASES,allowed_values={},
            values={},sources={},requirements=[{'field':hardware_color_field,'required':'Conditionally Required'}],
            row_context={'row_type':'Child'},invalid_candidates={})
        self.assertIsNone(hardware[0]['active']);self.assertEqual('conditional_risk',hardware[0]['validation_status'])
        legal_over_invalid_alias = compile_field_decisions(
            fields={color_field: 1},
            labels={},
            aliases=FIELD_ALIASES,
            allowed_values={color_field: ["White", "Black"]},
            values={color_field: "White"},
            sources={color_field: "variation"},
            requirements=[],
            row_context={"row_type": "Child"},
            invalid_candidates={color_field: "Ivory-ish"},
        )
        self.assertEqual("pass", legal_over_invalid_alias[0]["validation_status"])

    def test_parent_offer_stays_empty_and_pounds_unit_is_preserved(self) -> None:
        self.assertEqual("", template_engine._inventory_available_candidate(""))
        dimensions = template_engine.template_dimensions_from_facts({"item_weight": "330 Pounds"})
        self.assertEqual("330", dimensions["item_weight"])
        self.assertEqual("Pounds", dimensions["item_weight_unit"])
        cabinet = template_engine.template_dimensions_from_facts(
            {"length": "7.5", "width": "23.5", "height": "28", "product_dimensions": "7.5 x 23.5 x 28 in"},
            category_id="medicine_cabinet",
        )
        self.assertNotIn('item_depth',cabinet,'A cabinet category cannot rename an explicit length axis to depth')
        self.assertEqual(('7.5','23.5'),(cabinet['length'],cabinet['width']))
        self.assertNotIn('length_unit',cabinet,'An unlabeled tuple cannot supply a unit for an assumed axis')
        self.assertEqual("", template_engine.color_map_value("Begonia"))
        self.assertEqual('', template_engine.color_map_value('Begonia', category_id='artificial_tree'))
        self.assertEqual('Multicolor', template_engine.color_map_value('Green and Brown', category_id='artificial_tree'))
        plugin = ProductPlugin(category_id="bed_frame", root=Path("."), manifest={})
        specific = template_engine._family_specific(
            {"normalized_facts": {"item_weight": "66", "item_weight_unit": "Pounds"}},
            plugin,
        )
        self.assertEqual("66", specific["item_weight"])
        self.assertEqual("Pounds", specific["item_weight_unit"])

    def test_tree_species_dropdown_does_not_use_artificiality_as_species(self) -> None:
        from core.template_field_values import color_map_value,light_color_value
        self.assertEqual('',color_map_value('Unknown species',category_id='artificial_tree'))
        self.assertEqual('',light_color_value('artificial_tree',{}))
        tree = ProductPlugin(category_id='artificial_tree', root=Path('.'), manifest={})
        unlit = {'title':'Unlit Christmas Tree','specs':{'light_color':'Warm white'}}
        self.assertNotIn('light_color', template_engine._family_specific(unlit,tree))
        self.assertEqual('No', template_engine._family_specific(unlit,tree)['has_lights'])
        lit = {**unlit, 'variation_values':{'style':'Pre-lit'}, 'specs':{'light_color':'Warm white','light_count':'200'}}
        self.assertEqual('Warm white', template_engine._family_specific(lit,tree)['light_color'])
        plant_field = FIELD_ALIASES["plant_or_animal_product_type"][0]
        template = template_engine.TemplateInfo(
            path=Path("template.xlsm"),
            sheet="Template",
            max_row=20,
            max_col=2,
            fields={FIELD_ALIASES["sku"][0]: 1, plant_field: 2},
            labels={plant_field: "Plant or Animal Product Type"},
            required=[],
            existing_rows=[],
            allowed_values={plant_field: ["Boxwood", "Cedar", "Ficus", "Palm"]},
        )
        plugin = ProductPlugin(category_id="artificial_tree", root=Path("."), manifest={})
        row = {
            "sku": "B000000001",
            "row_type": "Child",
            "parent_sku": "PARENT",
            "copy": {"title": "Artificial Sesame Leaf Topiary", "bullets": [], "description": ""},
            "attributes": {
                "item_count": "1",
                "package_quantity": "1",
                "plant_or_animal_product_type": "synthetic",
                "tree_type": "synthetic",
                "source_title": "Artificial Sesame Leaf Topiary Tree",
            },
            "compliance": {},
            "offer": {},
        }

        plan = compile_template_field_plan(template=template, plugin=plugin, row_data=row)
        decisions = {item["field"]: item for item in plan["field_decisions"]}

        self.assertNotIn(plant_field, plan["field_values"])
        self.assertNotEqual("invalid_allowed_value", decisions.get(plant_field, {}).get("validation_status"))

    def test_bed_size_dropdown_uses_bed_size_not_physical_dimensions(self) -> None:
        from unittest.mock import patch
        from core.plugin import load_plugin
        for status, corrected in [('confirmed', 'Black'), ('conflicted', None), ('unconfirmed', None)]:
            subject = {'variation_values': {'Colour': 'White', 'size_name': 'Full', 'style_name': 'Old'},
                'specs': {'color_name': 'White', 'size_class': 'Full', 'style_name': 'Old'},
                'normalized_facts': {'resolved_facts': {
                    'color': {'status': status, 'value': corrected},
                    'size': {'status': status, 'value': 'Twin'},
                    'style': {'status': status, 'value': 'Modern'}}}}
            plugin = load_plugin('bed_frame')
            facts = template_engine._family_specific(subject, plugin)
            with patch.object(template_engine, '_copy_v1_for_row', return_value=('Storage Bed', [], [], '')):
                data = template_engine._build_listing_row_data(plugin=plugin, job={}, child=subject, specific=facts,
                    row_type='Child', sku='B000000001', parent_sku='P', theme='ColorSize', env={}, copy_v1={})
            fields = {FIELD_ALIASES[name][0]: i+1 for i, name in enumerate(('color', 'size', 'style'))}
            template = template_engine.TemplateInfo(path=Path('template.xlsm'), sheet='Template', max_row=20,
                max_col=3, fields=fields, labels={}, required=[], existing_rows=[])
            values = compile_template_field_plan(template=template, plugin=plugin, row_data=data)['field_values']
            for name, value in [('color', corrected), ('size', 'Twin'), ('style', 'Modern')]:
                self.assertEqual(value if status == 'confirmed' else '', values.get(FIELD_ALIASES[name][0], ''))
        size_field = FIELD_ALIASES["size"][0]
        style_field = FIELD_ALIASES["style"][0]
        child = {
            "variation_values": {"color": "Silver"},
            "normalized_facts": {
                "variation": {"color": "Silver"},
                "size": '78"L x 41"W x 43"H',
                "style": "Platform",
            },
            "specs": {
                "size": "Twin",
                "dimensions": '78"L x 41"W x 43"H',
                "style": "Platform",
                "source_title": "Modern Twin Loft Platform Bed",
            },
        }
        variation = template_engine._normalized_variation_values_for_template(
            child,
            {"size": "Twin", "dimensions": '78"L x 41"W x 43"H', "style": "Platform", "source_title": "Modern Twin Loft Platform Bed"},
            child["variation_values"],
        )
        self.assertEqual("Twin", variation["size"])

        template = template_engine.TemplateInfo(
            path=Path("template.xlsm"),
            sheet="Template",
            max_row=20,
            max_col=2,
            fields={FIELD_ALIASES["sku"][0]: 1, size_field: 2, style_field: 3},
            labels={size_field: "Size"},
            required=[],
            existing_rows=[],
            allowed_values={size_field: ["Twin", "Full", "Queen"], style_field: ["Contemporary", "Modern", "Rustic"]},
        )
        plugin = ProductPlugin(category_id="bed_frame", root=Path("."), manifest={})
        row = {
            "sku": "B000000001",
            "row_type": "Child",
            "parent_sku": "PARENT",
            "copy": {"title": "Twin Loft Bed", "bullets": [], "description": ""},
            "attributes": {
                "item_count": "1",
                "package_quantity": "1",
                **variation,
                "dimensions": '78"L x 41"W x 43"H',
                "source_title": "Modern Twin Loft Platform Bed",
            },
            "compliance": {},
            "offer": {},
        }

        values = compile_template_field_plan(template=template, plugin=plugin, row_data=row)["field_values"]

        self.assertEqual("Twin", values[size_field])
        self.assertEqual("Modern", values[style_field])
        parent_facts = template_engine._common_family_values([
            {"material":"Pine Wood"}, {"material":"Engineered Wood, Pine Wood"}])
        self.assertNotIn("material", parent_facts)
        self.assertNotIn("fabric_type", parent_facts)

    def test_dropdown_values_never_write_invalid_template_values(self) -> None:
        fields = {
            FIELD_ALIASES["sku"][0]: 1,
            FIELD_ALIASES["hardware_color"][0]: 2,
            FIELD_ALIASES["room_type"][0]: 3,
            FIELD_ALIASES["special_feature"][0]: 4,
            FIELD_ALIASES["size"][0]: 5,
            FIELD_ALIASES["country"][0]: 6,
            FIELD_ALIASES["inventory_available"][0]: 7,
        }
        allowed = {
            FIELD_ALIASES["hardware_color"][0]: ["Gold", "Silver"],
            FIELD_ALIASES["room_type"][0]: ["Bathroom"],
            FIELD_ALIASES["special_feature"][0]: ["Adjustable Shelf"],
            FIELD_ALIASES["size"][0]: ["Small", "Large"],
            FIELD_ALIASES["country"][0]: ["CN"],
            FIELD_ALIASES["inventory_available"][0]: ["Yes", "No"],
        }
        template = template_engine.TemplateInfo(
            path=Path("template.xlsm"),
            sheet="Template",
            max_row=20,
            max_col=8,
            fields=fields,
            labels={},
            required=[],
            existing_rows=[],
            allowed_values=allowed,
        )
        plugin = ProductPlugin(category_id="bathroom_cabinet", root=Path("."), manifest={})
        row = {
            "sku": "B000000001",
            "row_type": "Child",
            "parent_sku": "PARENT",
            "copy": {"title": "Bathroom Cabinet", "bullets": [], "description": ""},
            "attributes": {
                "item_count": "1",
                "package_quantity": "1",
                "hardware_color": "Brown",
                "room_type": "Powder Room",
                "special_feature": "Random marketing phrase",
                "size": "18m",
            },
            "compliance": {"country": "China"},
            "offer": {"inventory_available": True},
        }

        plan = compile_template_field_plan(template=template, plugin=plugin, row_data=row)
        values = plan["field_values"]

        for field, allowed_values in allowed.items():
            self.assertNotIn(values.get(field, ""), {"Brown", "Powder Room", "Random marketing phrase", "18m"})
            if values.get(field):
                self.assertIn(values[field], allowed_values)
        decisions = {item["field"]: item for item in plan["field_decisions"]}
        self.assertEqual("CN", values[FIELD_ALIASES["country"][0]])
        self.assertEqual("Yes", values[FIELD_ALIASES["inventory_available"][0]])
        self.assertEqual(
            "optional_invalid_allowed_value",
            decisions[FIELD_ALIASES["hardware_color"][0]]["validation_status"],
        )

    def test_field_plan_owns_mode_specific_main_image_readiness(self) -> None:
        main_field = IMAGE_FIELDS["main"]
        other_field = IMAGE_FIELDS["other1"]
        template = template_engine.TemplateInfo(
            path=Path("template.xlsm"), sheet="Template", max_row=20, max_col=2,
            fields={main_field: 1}, labels={}, required=[], existing_rows=[],
        )
        plugin = ProductPlugin(category_id="bed_frame", root=Path("."), manifest={})
        row = listing_data.row(
            row_type="Child", sku="B000000001", asin="B000000001",
            images={"main": "", "other": []},
            attributes={"item_count": "1", "package_quantity": "1"},
        )
        draft = compile_template_field_plan(template=template, plugin=plugin, row_data=row)
        submit = compile_template_field_plan(
            template=template, plugin=plugin, row_data=row, template_mode="submit_ready",
        )
        self.assertEqual("pass", {item["field"]: item for item in draft["field_decisions"]}[main_field]["validation_status"])
        self.assertEqual("missing_required", {item["field"]: item for item in submit["field_decisions"]}[main_field]["validation_status"])
        preview=compile_template_field_plan(template=template,plugin=plugin,row_data=row,
            template_mode='submit_ready',preflight=True)
        self.assertEqual('awaiting_upstream',preview['field_decisions'][0]['validation_status'])
        self.assertFalse(preview['field_values'].get(main_field),'Preflight must not fabricate a published URL')
        quantity=FIELD_ALIASES['quantity'][0]
        template.fields[quantity]=2
        preview=compile_template_field_plan(template=template,plugin=plugin,row_data=row,
            template_mode='submit_ready',preflight=True)
        decisions={d['field']:d['validation_status'] for d in preview['field_decisions']}
        self.assertEqual('missing_required',decisions[quantity],'Business facts cannot be deferred to generation')
        from core.template_field_plan import compile_field_plan
        image_plan = compile_field_plan(
            fields={main_field: 1, other_field: 2}, labels={}, aliases={},
            semantic_values={}, images={"main": "", "other": ["https://example.com/source-scene.jpg"]},
            image_fields=IMAGE_FIELDS,
        )
        self.assertNotIn(main_field, image_plan["field_values"])
        self.assertEqual("https://example.com/source-scene.jpg", image_plan["field_values"][other_field])

        from core.template_field_plan import fit_template_image_slots
        from core.required_role_policy import required_role_policy
        from core.plugin import load_plugin
        rows = [{'role': 'scene'}] + [{'role': f'func_{i:02d}'} for i in range(7)] + [{'role': 'size'}]
        for category in ('bathroom_cabinet', 'medicine_cabinet', 'artificial_tree', 'bed_frame'):
            counts = required_role_policy(load_plugin(category)).counts
            kept, omitted = fit_template_image_slots(rows, required_counts=counts)
            self.assertEqual(8, len(kept))
            self.assertTrue({'scene', 'size'} <= {row['role'] for row in kept})
            self.assertTrue(omitted[0]['role'].startswith('func'))
            self.assertEqual((kept, []), fit_template_image_slots(kept, required_counts=counts))
        with self.assertRaisesRegex(ValueError, 'capacity'):
            fit_template_image_slots(rows, required_counts={'scene': 4, 'func': 4, 'size': 1})


if __name__ == "__main__":
    unittest.main()
