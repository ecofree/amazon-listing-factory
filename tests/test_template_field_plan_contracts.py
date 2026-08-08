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
        workbook = Workbook()
        sheet = workbook.active
        sheet.cell(7, 1).value = "unknown row content"
        with self.assertRaises(template_engine.TemplateEngineError):
            template_engine._detect_template_data_start_row(sheet, 1)

    def test_template_defaults_include_safeplus_brand(self) -> None:
        resolved = template_job_with_defaults({}, env={})
        self.assertEqual("safeplus", resolved["brand"])
        self.assertEqual("New", resolved["condition"])
        self.assertEqual("200", resolved["quantity"])

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
        self.assertFalse(decisions[unknown_conditional]["active"])
        self.assertEqual("conditional_risk", decisions[unknown_conditional]["validation_status"])

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
        self.assertNotIn("length", cabinet)
        self.assertEqual(("7.5", "23.5"), (cabinet["item_depth"], cabinet["width"]))
        self.assertEqual("", template_engine.color_map_value("Begonia"))
        self.assertEqual("Multicolor", template_engine.color_map_value("Begonia", category_id="artificial_tree"))
        plugin = ProductPlugin(category_id="bed_frame", root=Path("."), manifest={})
        specific = template_engine._family_specific(
            {"normalized_facts": {"item_weight": "66", "item_weight_unit": "Pounds"}},
            plugin,
        )
        self.assertEqual("66", specific["item_weight"])
        self.assertEqual("Pounds", specific["item_weight_unit"])

    def test_tree_species_dropdown_does_not_use_artificiality_as_species(self) -> None:
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
        parent_facts = template_engine._parent_family_values(
            [
                {"specs": {"material": "Pine Wood"}},
                {"specs": {"material": "Engineered Wood, Pine Wood"}},
            ],
            plugin,
        )
        self.assertEqual("Wood", parent_facts["fabric_type"])

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
        from core.template_field_plan import compile_field_plan
        image_plan = compile_field_plan(
            fields={main_field: 1, other_field: 2}, labels={}, aliases={},
            semantic_values={}, images={"main": "", "other": ["https://example.com/source-scene.jpg"]},
            image_fields=IMAGE_FIELDS,
        )
        self.assertNotIn(main_field, image_plan["field_values"])
        self.assertEqual("https://example.com/source-scene.jpg", image_plan["field_values"][other_field])


if __name__ == "__main__":
    unittest.main()
