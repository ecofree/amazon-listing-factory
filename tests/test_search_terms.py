from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core import copy_writer
from core.search_terms import ingest_search_term_csvs, title_reference_context


class SearchTermDatabaseTests(unittest.TestCase):
    def test_ingests_csv_and_returns_top_clicked_title_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "US_Top_Search_Terms_Simple_Quarter_2026_03_31-cabinet.csv"
            csv_path.write_text(_sample_csv(), encoding="utf-8")
            db_path = root / "search_terms.sqlite"

            summary = ingest_search_term_csvs([csv_path], db_path=db_path)

            self.assertEqual(2, summary.rows_imported)
            self.assertEqual({"cabinet": 2}, summary.categories)
            context = title_reference_context(
                category="Bathroom Cabinet",
                source_title="Tall bathroom storage cabinet with adjustable shelves",
                product_specific={"height": "67 inch", "number_of_doors": 2, "shelves": "adjustable"},
                env={"AMAZON_FACTORY_SEARCH_TERMS_DB": str(db_path), "AMAZON_FACTORY_SEARCH_TERMS_LIMIT": "3"},
            )

            self.assertEqual("local_search_terms_db", context["source"])
            self.assertEqual(["cabinet"], context["search_categories"])
            self.assertIn("bathroom storage cabinet", [item["search_term"] for item in context["references"]])
            first = context["references"][0]["top_clicked_titles"][0]
            self.assertIn("Bathroom Storage Cabinet", first["reference_title"])
            self.assertEqual(8.5, first["conversion_share"])

    def test_copy_writer_injects_market_reference_into_deepseek_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "US_Top_Search_Terms_Simple_Quarter_2026_03_31-cabinet.csv"
            csv_path.write_text(_sample_csv(), encoding="utf-8")
            db_path = root / "search_terms.sqlite"
            ingest_search_term_csvs([csv_path], db_path=db_path)
            captured: list[dict] = []
            original_post = copy_writer._post_chat_completion
            copy_writer._CACHE.clear()

            def fake_post(config, payload):
                captured.append(payload)
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                             "title": "67 Inch Tall Bathroom Storage Cabinet with Adjustable Shelves",
                                             "item_highlights": ["Adjustable Shelves", "Double Doors", "Narrow Floor Storage"],
                                            "bullets": [
                                                "Adjustable Shelves: Interior shelves adjust to organize towels and daily toiletries in compact bathrooms",
                                                "Tall Storage: Vertical cabinet shape uses wall-side space while keeping bathroom essentials enclosed",
                                                "Double Doors: Two cabinet doors conceal bottles, towels, and cleaning supplies for a tidy room",
                                                "Wood Structure: Engineered wood panels create a freestanding floor cabinet for everyday home storage",
                                                "Room Placement: Fits bathrooms, laundry rooms, hallways, and apartments where narrow storage is needed",
                                            ],
                                            "description": "This tall bathroom storage cabinet organizes towels, toiletries, and daily supplies in a compact freestanding footprint for bathrooms, laundry rooms, hallways, and apartments. Adjustable shelves help separate bottles and folded items, while double doors keep essentials enclosed. The 67-inch engineered wood cabinet has two doors and adjustable shelves.",
                                        }
                                    )
                                }
                            }
                        ]
                    }
                )

            try:
                copy_writer._post_chat_completion = fake_post
                result = copy_writer.rewrite_listing_copy(
                    env={
                        "COPY_AI_ENABLED": "true",
                        "DEEPSEEK_API_KEY": "test-key",
                        "COPY_AI_BASE_URL": "https://api.deepseek.com",
                        "COPY_AI_MODEL": "deepseek-test",
                        "AMAZON_FACTORY_COPY_PROVIDER_ORDER": "openai",
                        "AMAZON_FACTORY_SEARCH_TERMS_DB": str(db_path),
                    },
                    category="Bathroom Cabinet",
                    brand="Safeplus",
                    row_type="Child",
                    source_title="Tall bathroom storage cabinet with adjustable shelves",
                    source_bullets=["Adjustable shelves for towels and toiletries"],
                    source_description="",
                    product_specific={"height": "67 inch", "number_of_doors": 2, "shelves": "adjustable"},
                )
            finally:
                copy_writer._post_chat_completion = original_post
                copy_writer._CACHE.clear()

            self.assertEqual("https://api.deepseek.com", result["_provider"])
            self.assertEqual(2, result["_market_search_reference"]["reference_count"])
            self.assertEqual({"type": "disabled"}, captured[0]["thinking"])
            user_payload = json.loads(captured[0]["messages"][1]["content"])
            market = user_payload["market_search_reference"]
            self.assertEqual("local_search_terms_db", market["source"])
            self.assertIn("bathroom storage cabinet", [item["search_term"] for item in market["references"]])
            self.assertNotIn("top_clicked_brands", market["references"][0])
            spec_facts = user_payload["concrete_facts_to_cover"]
            self.assertEqual("67 inch", spec_facts["Height"])
            self.assertEqual("2", spec_facts["Number Of Doors"])
            operator_strategy = " ".join(user_payload["constraints"]["title_operator_strategy"])
            self.assertIn("narrow competition", operator_strategy)
            self.assertIn("factual limiting words", operator_strategy)
            with self.assertRaisesRegex(copy_writer.CopyWriterError, "finish_reason=length.*reasoning_content_present=True"):
                copy_writer._copy_response_content_object(
                    json.dumps({"choices": [{"finish_reason": "length", "message": {"content": "", "reasoning_content": "hidden"}}]})
                )

    def test_copy_writer_rejects_reference_brand_in_generated_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            csv_path = root / "US_Top_Search_Terms_Simple_Quarter_2026_03_31-cabinet.csv"
            csv_path.write_text(_sample_csv(), encoding="utf-8")
            db_path = root / "search_terms.sqlite"
            ingest_search_term_csvs([csv_path], db_path=db_path)
            captured: list[dict] = []
            original_post = copy_writer._post_chat_completion
            copy_writer._CACHE.clear()

            def payload_with_title(title: str) -> str:
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                             "title": title,
                                             "item_highlights": ["Adjustable Shelves", "Double Doors", "Narrow Floor Storage"],
                                            "bullets": [
                                                "Adjustable Shelves: Interior shelves adjust to organize towels and daily toiletries in compact bathrooms",
                                                "Tall Storage: Vertical cabinet shape uses wall-side space while keeping bathroom essentials enclosed",
                                                "Double Doors: Two cabinet doors conceal bottles, towels, and cleaning supplies for a tidy room",
                                                "Wood Structure: Engineered wood panels create a freestanding floor cabinet for everyday home storage",
                                                "Room Placement: Fits bathrooms, laundry rooms, hallways, and apartments where narrow storage is needed",
                                            ],
                                            "description": "This 67-inch freestanding bathroom storage cabinet organizes towels, toiletries, and daily supplies in a compact footprint. Adjustable shelves separate bottles and folded items, while two doors keep essentials enclosed.",
                                        }
                                    )
                                }
                            }
                        ]
                    }
                )

            def fake_post(config, payload):
                captured.append(payload)
                if len(captured) == 1:
                    return payload_with_title("ReferenceBrand Tall Bathroom Storage Cabinet with Adjustable Shelves")
                return payload_with_title("67 Inch Tall Bathroom Storage Cabinet with Adjustable Shelves")

            try:
                copy_writer._post_chat_completion = fake_post
                result = copy_writer.rewrite_listing_copy(
                    env={
                        "COPY_AI_ENABLED": "true",
                        "DEEPSEEK_API_KEY": "test-key",
                        "COPY_AI_BASE_URL": "https://example.test/v1",
                        "COPY_AI_MODEL": "deepseek-test",
                        "AMAZON_FACTORY_COPY_PROVIDER_ORDER": "openai",
                        "AMAZON_FACTORY_SEARCH_TERMS_DB": str(db_path),
                    },
                    category="Bathroom Cabinet",
                    brand="Safeplus",
                    row_type="Child",
                    source_title="ReferenceBrand Tall bathroom storage cabinet with adjustable shelves",
                    source_bullets=["ReferenceBrand cabinet stores towels and toiletries"],
                    source_description="ReferenceBrand freestanding storage for bathrooms",
                    product_specific={"height": "67 inch", "number_of_doors": 2, "shelves": "adjustable"},
                )
            finally:
                copy_writer._post_chat_completion = original_post
                copy_writer._CACHE.clear()

            self.assertEqual("67 Inch Tall Bathroom Storage Cabinet with Adjustable Shelves", result["title"])
            self.assertGreaterEqual(len(captured), 1)
            self.assertLessEqual(len(captured), 2)
            first_user_payload = json.loads(captured[0]["messages"][1]["content"])
            self.assertNotIn("ReferenceBrand", json.dumps(first_user_payload["source"]))
            self.assertNotIn("RivalA", json.dumps(first_user_payload["market_search_reference"]))

def _sample_csv() -> str:
    return "\n".join(
        [
            'Reporting Range=["Quarterly"],Select year=["2026"],Select quarter=["1"],Search Term=["cabinet"]',
            '"Search Frequency Rank","Search Term","Top Clicked Brand #1","Top Clicked Brands #2","Top Clicked Brands #3","Top Clicked Category #1","Top Clicked Category #2","Top Clicked Category #3","Top Clicked Product #1: ASIN","Top Clicked Product #1: Product Title","Top Clicked Product #1: Click Share","Top Clicked Product #1: Conversion Share","Top Clicked Product #2: ASIN","Top Clicked Product #2: Product Title","Top Clicked Product #2: Click Share","Top Clicked Product #2: Conversion Share","Top Clicked Product #3: ASIN","Top Clicked Product #3: Product Title","Top Clicked Product #3: Click Share","Top Clicked Product #3: Conversion Share","Reporting Date"',
            '"100","bathroom storage cabinet","RivalA","RivalB","RivalC","Home","Furniture","Kitchen","B0A","RivalA Tall Bathroom Storage Cabinet with Adjustable Shelves, 2 Doors, White","4.5","8.5","B0B","RivalB Bathroom Floor Cabinet with Double Doors and Shelves","2.2","3.5","B0C","RivalC Narrow Storage Cabinet for Small Bathroom","1.8","2.9","2026-03-31"',
            '"180","storage cabinet","RivalD","RivalE","RivalF","Home","Furniture","Kitchen","B0D","RivalD Storage Cabinet with Doors and Adjustable Shelves for Living Room","3.5","5.1","B0E","RivalE Tall Storage Cabinet with 4 Drawers","2.0","2.5","B0F","RivalF Pantry Cabinet with Shelves","1.2","1.5","2026-03-31"',
        ]
    )


if __name__ == "__main__":
    unittest.main()
