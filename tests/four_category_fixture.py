"""Four-category reachable contract regressions; folded into existing test cases."""
from copy import deepcopy


def verify_identity_and_variants(test):
    from core.category_guard import guess_category_from_raw
    from core.plugin import load_plugin
    from core.template_engine import _build_listing_row_data,compile_template_field_plan,TemplateInfo,FIELD_ALIASES
    from pathlib import Path
    primary={'asin':'B000000001','title':'Twin Metal Bed Frame Platform Bed'}
    for unrelated in ('relatedProducts','reviews','aPlusContent','variants'):
        raw={**primary,unrelated:[{'title':'Wall Mounted Medicine Cabinet with Mirror'}]}
        test.assertEqual('bed_frame',guess_category_from_raw(raw).category_id)
    test.assertEqual('',guess_category_from_raw({'relatedProducts':[{'title':'Medicine Cabinet'}]}).category_id)
    test.assertEqual('',guess_category_from_raw({**primary,'category':'Medicine Cabinet'}).category_id)
    for category,label in [('artificial_tree','6 FT'),('artificial_tree','7.5 FT'),('bathroom_cabinet','24 inches'),('bed_frame','Queen')]:
        child={'asin':'B000000001','variation_values':{'Size':label},'normalized_facts':{'variation':{'Size':label}}}
        row=_build_listing_row_data(plugin=load_plugin(category),job={'brand':'Synthetic fixture'},child=child,
            specific={'size':label},row_type='Child',sku='TEST',asin=child['asin'],parent_sku='PARENT',theme='SIZE',env={},copy_v1=None)
        test.assertEqual(label,row['variation'].get('size'))
        test.assertEqual(label,row['attributes']['size'])
        field=FIELD_ALIASES['size'][0]
        template=TemplateInfo(path=Path('unused.xlsm'),sheet='Template',max_row=9,max_col=1,fields={field:1},labels={},required=[],existing_rows=[])
        result=compile_template_field_plan(template=template,plugin=load_plugin(category),row_data=row)
        test.assertEqual(label,result['field_values'].get(field))


def verify_policy_domains(test):
    from core.plugin import load_plugin,ProductPlugin
    from core.required_role_policy import compiled_image_policy
    from core.planning_identity import design_context
    for category in ('bed_frame','bathroom_cabinet','medicine_cabinet','artificial_tree'):
        plugin=load_plugin(category);original=compiled_image_policy(plugin)
        manifest=deepcopy(plugin.manifest)
        manifest['image_generation']['planning_guidance']=['Future-work advice only']
        changed=compiled_image_policy(ProductPlugin(category_id=category,root=plugin.root,manifest=manifest))
        test.assertEqual(original,changed)
        test.assertEqual(design_context(original,{}),design_context(changed,{}))
        manifest['image_generation']['structure_invariants'].append('Preserve an additional source-visible owned component')
        hard=compiled_image_policy(ProductPlugin(category_id=category,root=plugin.root,manifest=manifest))
        test.assertNotEqual(original['policy_id'],hard['policy_id'])


def verify_dimension_axes(test):
    from products.generic_extractors import extract_specs_by_fields
    from core.template_field_values import template_dimensions_from_facts
    for category in ('bed_frame','bathroom_cabinet','medicine_cabinet','artificial_tree'):
        for value in ('24 x 36 x 12 inches','24 * 36 * 12 inches','24 × 36 × 12 inches'):
            facts=extract_specs_by_fields({'attributes':{'Product Dimensions':value}},{'dimensions':('Product Dimensions',)})
            test.assertEqual(value,facts['dimensions'])
            test.assertEqual({},template_dimensions_from_facts(facts,category_id=category))
        for field,value,expected in [('Item Dimensions D x W x H','24 x 36 x 12 inches',{'item_depth':'24','width':'36','height':'12'}),
            ('Product Dimensions','24L x 36W x 12H inches',{'length':'24','width':'36','height':'12'}),
            ('Product Dimensions','24"W x 8"D x 30"H',{'width':'24','item_depth':'8','height':'30'}),
            ('Item Dimensions L x W x H','100 x 50 x 40 cm',{'length':'39.37','width':'19.69','height':'15.75'})]:
            facts=extract_specs_by_fields({'attributes':{field:value}},{'dimensions':(field,)})
            dimensions=template_dimensions_from_facts(facts,category_id=category)
            test.assertEqual(expected,{k:v for k,v in dimensions.items() if not k.endswith('_unit')})
            test.assertTrue(all(dimensions[k+'_unit']=='Inches' for k in expected))
    test.assertEqual({},template_dimensions_from_facts({'package_dimensions':'24L x 36W x 12H in'}))
