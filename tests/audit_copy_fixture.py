"""Copy measurement facts are checked by the existing copy validator, not a second model."""
import json


def verify_copy_measurements(test):
    from core.copy_writer import _parse_copy_response,CopyWriterError
    def check(sentence,facts):
        data={'title':'Metal Platform Bed Frame for Bedrooms','item_highlights':['Metal Frame','Bedroom Use'],
            'bullets':[sentence,'Metal Frame: Metal construction supports a mattress.','Bedroom Use: Designed for bedroom placement.',
                       'Platform Support: A platform holds the mattress.','Simple Setup: Follow assembly instructions.'],
            'description':'A metal platform bed frame for bedroom use.'}
        return _parse_copy_response(json.dumps({'choices':[{'message':{'content':json.dumps(data)}}]}),category='Bed Frame',product_specific=facts)
    facts={'length':'80 inches','width':'60 inches','height':'14 inches','under_bed_clearance':'12 inches','material':'Metal'}
    for text in ('Size: The frame measures 80 inches in length.','Size: The frame measures 203.2 cm in length.',
                 'Size: The frame is 60 inches wide.','Size: The frame is 60 inches wide for maximum storage.',
                 'Storage: There is 12-inch under-bed clearance.',
                 'Size: Overall dimensions are 80 L x 60 W x 14 H inches.'):
        check(text,facts)
    for text in ('Size: The frame measures 999 inches in length.','Size: The frame is 80 inches wide.',
                 'Size: The frame is 12 inches tall.','Storage: There is 14-inch under-bed clearance.',
                 'Size: Overall dimensions are 60 L x 80 W x 14 H inches.',
                 'Size: Overall dimensions are 60 x 80 x 14 inches.'):
        with test.assertRaisesRegex(CopyWriterError,'measurement'):check(text,facts)
    with test.assertRaisesRegex(CopyWriterError,'measurement'):check('Size: The frame is 80 inches long.',{'material':'Metal'})
    check('Size: The shelf is 10-12 inches wide.',{'shelf_width':'10-12 inches'})
    with test.assertRaisesRegex(CopyWriterError,'measurement'):check('Size: The shelf is 12 inches wide.',{'shelf_width':'10-12 inches'})
    check('Use: Recommended mattress thickness is up to 10 inches.',{'recommended_mattress_thickness':'up to 10 inches'})
    with test.assertRaisesRegex(CopyWriterError,'measurement'):check('Size: Frame thickness is 10 inches.',{'recommended_mattress_thickness':'up to 10 inches'})
