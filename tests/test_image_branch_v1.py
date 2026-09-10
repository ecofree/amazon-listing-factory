from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.final_source_intents import (
    _authored_claims,
    build_final_source_intents,
    read_final_source_intents,
)
from core.image_prompt_compiler import (
    PROMPT_HARD_LIMIT_CHARS,
    _measurement_content,
    build_image_prompts,
    compile_task_prompt,
    read_image_prompts,
)
from core.image_task_inputs import (
    build_func_story_contract,
    measurement_contract,
    visual_product_color,
    visual_variation_values,
)
from core.image_tasks import (
    _generation_references_for_task,
    _task_specs,
    build_image_tasks,
    read_image_tasks,
)
from core.io import file_sha256
from core.run_scope import row_in_scope
from core.visual_design_kit import (
    build_visual_design_kits,
    compact_product_claims,
    read_visual_design_kits,
)
from core.visual_design_kit_compiler import (
    VisualDesignKitCompileError,
    compile_visual_design_kit_response,
)
from tests.current_image_contract_fixture import (
    current_art_direction,
    current_image_task,
)


class _Plugin:
    category_id = "bathroom_cabinet"
    display_name = "Bathroom Cabinet"
    product_type = "BATHROOM_CABINET"
    root = Path("products/bathroom_cabinet")

    @staticmethod
    def merged_config() -> dict:
        return {
            "product_type": "BATHROOM_CABINET",
            "display_name": "Bathroom Cabinet",
            "required_role_policy": {
                "counts": {"main": 1, "scene": 1, "func": 1, "size": 1}
            },
            "image_generation": {
                "main_image_policy": "white_background",
                "structure_invariants": ["cabinet body", "door count", "drawer count", "hinges", "shelves"],
                "allowed_internal_props": ["small toiletries on intended storage surfaces"],
                "replaceable_staging": ["loose toiletries, towels, flowers, and wall decor"],
                "forbidden_additions": [{"part": "new handles", "unless_source_visible": True}],
                "role_specific_rules": {
                    "main": ["keep the external canvas pure white"], "scene": ["show realistic bathroom use"],
                    "func": ["show only source-demonstrated functions"], "size": ["preserve the complete source measurement diagram"],
                },
                "template_image_role_order": ["main", "scene", "func", "size"],
            },
        }


def _child() -> dict:
    return {
        "asin": "B000000001",
        "title": "White Bathroom Storage Cabinet with Adjustable Shelf",
        "bullets": ["Adjustable interior shelf organizes tall and short toiletries.", "Wall-mounted storage keeps bathroom essentials within reach.", "Painted engineered wood surface wipes clean."],
        "description": "A compact white cabinet for organized bathroom storage.",
        "specs": {"Material": "Painted engineered wood", "Product Dimensions": "24 W x 8 D x 30 H in", "Mounting Type": "Wall Mount"},
        "normalized_facts": {"color": "white", "style": "shaker", "variation": {"Color": "White"}, "sold_unit_count": 1},
        "sold_unit_count": 1,
        "reference_images": [
            {"url": f"https://example.com/source_{index:02d}.png", "source": "test"}
            for index in range(4)
        ],
    }


def _family() -> dict:
    return {
        "family": {
            "parent_asin": "B000000001",
            "product_type": "BATHROOM_CABINET",
            "children": [_child()],
        }
    }


def _scope() -> dict:
    return {"selected_children": ["B000000001"], "selected_sources": {"B000000001": [0, 1, 2, 3]}}


def _evidence(role: str) -> dict:
    base = {
        "ocr_evidence": {"available": True, "lines": []},
        "trusted_text": [],
        "measurements": [],
        "claims": [],
        "pixel_evidence": {"scene_pixels": False, "product_view_pixels": True},
        "visual_evidence": {},
    }
    if role == "scene":
        base["pixel_evidence"] = {
            "scene_pixels": True,
            "product_view_pixels": False,
        }
    elif role == "func":
        base.update({
            "trusted_text": ["Adjustable shelf provides 3positions for different object heights."],
            "claims": _authored_claims(["Adjustable shelf provides 3positions for different object heights."]),
            "visual_evidence": {
                "status": "success",
                "role_guess": "func",
                "confidence": 0.92,
                "has_callouts_or_panels": True,
                "evidence": ["Adjustable Shelf", "Open Storage Access"],
            },
        })
    elif role == "size":
        base.update({
            "trusted_text": ["Width 24 in", "Height 30 in"],
            "measurements": [
                {
                    "text": "24 in",
                    "raw_text": "24 in",
                    "canonical_pair": "24:in",
                },
                {
                    "text": "30 in",
                    "raw_text": "30 in",
                    "canonical_pair": "30:in",
                },
            ],
        })
    from core.visual_semantics import OBSERVATION_POLICY, source_fact_records
    from core.status import input_revision_id
    base["visual_evidence"] = {
        **base["visual_evidence"], "status": "success", "policy_version": OBSERVATION_POLICY,
        "child_facts_revision_id": input_revision_id(source_fact_records(_child())),
        "variant_identity": {"status": "unknown", "observed_color": "", "conflicts": [], "reason": "Fixture cropped view"},
        "text_observations": [{"text": text, "kind": "marketing" if role == "func" else "measurement"} for text in base["trusted_text"]],
    }
    return base


def _planner_payload(intents: list[dict]) -> dict:
    by_role = {row["role"]: row for row in intents}
    claims = compact_product_claims(_child())
    func = by_role["func"]
    source_id = func["claims"][0]["evidence_id"]
    return {
        "family_art_direction": current_art_direction(),
        "source_briefs": [
            {"source_id": "source_00", "shopping_purpose": "Identify the exact sold cabinet.", "image_direction": "Show the cabinet on white with carefully designed product lighting."},
            {
                "source_id": "source_01",
                "shopping_purpose": "Show realistic bathroom placement, storage access, and product scale.",
                "image_direction": (
                    "Show a believable bathroom use moment with newly selected towels and containers around the unchanged cabinet, using "
                    "realistic wall contact, residential depth, quiet negative space, coordinated surfaces, and enough environmental context "
                    "to explain placement and scale while keeping every source-visible sold-product relationship intact and immediately legible."
                ),
            },
            {
                "source_id": "source_02",
                "shopping_purpose": "Explain how the cabinet adapts storage for everyday bathroom essentials.",
                "image_direction": "Use an editorial asymmetric feature layout with a dominant cabinet view, restrained detail inset, and the shared child typography, icon, line, and color system.",
                "func_story": {
                    "title": {
                        "evidence_ids": [source_id],
                        "text": "Adjustable Shelf",
                    },
                    "labels": [
                        {"evidence_ids": [source_id], "text": "Different Object Heights"},
                        {"evidence_ids": [claims[1]["evidence_id"]], "text": "Wall-Mounted Organization"},
                    ],
                },
            },
            {
                "source_id": "source_03",
                "shopping_purpose": "Present the complete source measurement diagram.",
                "image_direction": "Use generous technical spacing, an ordered measurement hierarchy, and the shared child typography, line, badge, and color system without moving diagram endpoints.",
            },
        ],
    }

def _fixture_observation(_job, _child, sources, **kwargs):
    return {row["source_id"]: {**_evidence(("main", "scene", "func", "size")[int(row["source_id"].split("_")[1])])["visual_evidence"], "source_id": row["source_id"],
        "variant_identity": {"status": "consistent", "observed_color": "White", "reason": "Observed white finish", "conflicts": []}} for row in sources}


def _fixture_reviews(claims, **kwargs):
    from core.visual_semantics import CLAIM_REVIEW_POLICY
    records = [{"key": row["key"], "status": "supported", "reason": "fixture verified property"} for row in claims]
    path = kwargs["trace_dir"] / "claim_review_response.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"reviews": records}), encoding="utf-8")
    return {row["key"]: {**row, "policy": CLAIM_REVIEW_POLICY, "response_path": str(path.resolve()),
                         "response_sha256": file_sha256(path)} for row in records}


class ImageBranchCurrentBehaviorTests(unittest.TestCase):
    def setUp(self):
        observation = patch("core.final_source_intents.observe_child_sources", side_effect=_fixture_observation)
        reviews = patch("core.visual_design_kit.review_claims", side_effect=_fixture_reviews)
        observation.start()
        reviews.start()
        self.addCleanup(observation.stop)
        self.addCleanup(reviews.stop)

    def test_task_specs_and_size_prompt_cover_required_sources(self) -> None:
        from core.plugin import discover_plugins
        from core.required_role_policy import compiled_image_policy
        from core.image_tasks import _edit_contract
        plugins = discover_plugins()
        for category in ("bed_frame", "bathroom_cabinet", "medicine_cabinet", "artificial_tree"):
            plugin = plugins[category]
            policy = compiled_image_policy(plugin)
            styles = {}
            for role in ("main", "scene", "func", "size"):
                task = current_image_task(role, category_id=category)
                task.update(category_image_policy=policy, family_art_direction=current_art_direction())
                task["edit_contract"] = _edit_contract(role, task["measurement_authority"], policy, {}, product_type=plugin.product_type)
                prompt = compile_task_prompt(task=task)
                styles[role] = prompt.split("[STYLE]\n")[1].split("\n\n[TEXT]")[0]
                self.assertIn("do not reconstruct the product", prompt)
                self.assertEqual(1, prompt.count("Preserve: Keep the protected source content unchanged"))
                self.assertNotIn("or readable text", prompt)
                if category != "bed_frame":
                    self.assertNotIn("mattress", prompt.casefold())
                elif role in {"main", "scene"}:
                    self.assertIn("source-visible mattress", prompt)
            func_palette = next(row for row in styles["func"].splitlines() if row.startswith("Child palette:"))
            size_palette = next(row for row in styles["size"].splitlines() if row.startswith("Child palette:"))
            self.assertEqual(func_palette, size_palette)
            if category != "bed_frame":
                self.assertNotIn("Photography intent", styles["main"])
                self.assertNotIn("room tokens:", styles["main"])
            self.assertIn("Typography system: Confident contemporary sans-serif", styles["func"])
            self.assertIn("Graphic system: Restrained technical lines", styles["size"])
        sources = [
            {"source_index": 0, "role": "main"},
            {"source_index": 1, "role": "scene"},
            {"source_index": 2, "role": "scene"},
            {"source_index": 3, "role": "func"},
            {"source_index": 4, "role": "func"},
            {"source_index": 5, "role": "size"},
        ]
        specs = _task_specs({"asin": "B1"}, sources)
        complete = _task_specs({"asin": "B1"}, sources, include_optional=True)
        self.assertEqual(["main", "scene", "scene_02", "func", "func_02", "size"], [row["role"] for row in complete])
        self.assertEqual(
            ["main", "scene", "func", "size"],
            [row["role"] for row in specs],
        )
        missing = {row["role"]: row for row in _task_specs({}, [{"source_index": 0, "role": "main"}])}
        self.assertTrue(missing["scene"]["evidence_pending"])
        self.assertTrue(missing["func"]["evidence_pending"])
        self.assertTrue(missing["size"]["evidence_pending"])
        content = _measurement_content({
            "mode": "source_image",
            "measurement_groups": [
                {"render_text": '28"'},
                {"render_text": '23.5"'},
                {"render_text": "44 lbs"},
            ],
        })
        self.assertIn("44 lbs", content)
        self.assertIn("Render canonical display copy with readable spacing", content)
        from core.image_tasks import _measurement_authority
        mixed = _measurement_authority("func", {}, {"role": "func", "source_sha256": "a" * 64, "input_revision_id": "source",
            "measurements": [{"text": "12 in", "source_label": "Underbed clearance", "canonical_pair": "length_mm:304.8"}]})
        self.assertEqual("source_image", mixed["mode"])
        self.assertIn("Underbed clearance: 12 in", _measurement_content(mixed))
        with patch("core.run_scope.read_run_scope", return_value={"selected_children": ["B1"], "selected_sources": {"B1": []}}):
            self.assertFalse(row_in_scope("unused", {"child": "B1", "index": 0}))

    def _source_fixture(
        self,
        job: Path,
    ) -> tuple[list[dict], dict[str, dict]]:
        rows: list[dict] = []
        evidence: dict[str, dict] = {}
        for index, role in enumerate(("main", "scene", "func", "size")):
            relative = Path("images") / "source" / f"source_{index:02d}.png"
            path = job / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new(
                "RGB",
                (320, 320),
                (248 - index * 12, 246 - index * 10, 242 - index * 8),
            ).save(path)
            sha = file_sha256(path)
            rows.append({
                "child": "B000000001",
                "index": index,
                "url": f"https://example.com/source_{index:02d}.png",
                "status": "ok",
                "raw_path": relative.as_posix(),
                "source_sha256": sha,
            })
            evidence[sha] = _evidence(role)
        return rows, evidence

    def test_current_artifact_chain_has_one_fact_authority_and_typed_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "reports").mkdir(parents=True)
            visual_child = {
                "variation_values": {"color": "Grey Full Over Full with Trundle"},
                "normalized_facts": {
                    "color": "Grey Full Over Full with Trundle",
                    "variation": {"color": "Grey Full Over Full with Trundle"},
                },
                "specs": {"color": "Grey"},
            }
            self.assertEqual("Grey", visual_product_color(visual_child))
            self.assertEqual({"color": "Grey"}, visual_variation_values(visual_child))
            self.assertEqual("Grey Full Over Full with Trundle", visual_child["variation_values"]["color"])
            rows, evidence = self._source_fixture(job)
            family, scope = _family(), _scope()
            with (
                patch("core.final_source_intents.ensure_run_scope"),
                patch(
                    "core.final_source_intents.download_artifacts_current",
                    return_value=(True, []),
                ),
                patch(
                    "core.final_source_intents.read_download_manifest",
                    return_value={"schema_version": "download-manifest-v2", "rows": rows},
                ),
                patch("core.final_source_intents.read_product_family", return_value=family),
                patch("core.final_source_intents.row_in_scope", return_value=True),
                patch(
                    "core.final_source_intents._collect_evidence_by_sha",
                    return_value=evidence,
                ),
            ):
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                intents = read_final_source_intents(job, plugin=_Plugin())
                observed = _fixture_observation(job, _child(), [{"source_id": f"source_{i:02d}"} for i in range(4)])
                observed["source_01"]["variant_identity"] = {
                    "status": "contradiction", "observed_color": "natural wood", "reason": "Natural frame in a white child gallery",
                    "conflicts": [{"fact_id": "product.normalized_facts.color", "observed": "natural wood"}],
                }
                with patch("core.final_source_intents.observe_child_sources", return_value=observed):
                    build_final_source_intents(job_dir=job, plugin=_Plugin())
                    rejected = read_final_source_intents(job, plugin=_Plugin())
                    self.assertEqual(["main", "review_required", "func", "size"], [row["role"] for row in rejected])
                    self.assertEqual(rows[1]["source_sha256"], rejected[1]["source_sha256"])
                    self.assertIn("source_variant_conflict", rejected[1]["classification_reason"])
                    from core.final_source_intents import planning_source_intents
                    self.assertEqual([0, 2, 3], [row["source_index"] for row in planning_source_intents(job, plugin=_Plugin())])
                from core.image_task_inputs import product_boundary
                boundary = product_boundary({}, _child(), product_type="BATHROOM_CABINET", observations=[observed["source_01"]])
                self.assertEqual([{"name": "natural wood", "source": "source_01"}], boundary["observed_product_colors"])
                self.assertEqual([], product_boundary({}, _child(), product_type="BATHROOM_CABINET")["observed_product_colors"])
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                from core.final_source_intents import FinalSourceIntentError
                import copy
                changed = copy.deepcopy(family)
                changed["family"]["children"][0]["normalized_facts"]["color"] = "black"
                with patch("core.final_source_intents.read_product_family", return_value=changed), self.assertRaisesRegex(FinalSourceIntentError, "stale child facts"):
                    read_final_source_intents(job, plugin=_Plugin())
            self.assertEqual(
                ["main", "scene", "func", "size"],
                [row["role"] for row in intents],
            )
            self.assertGreater(len(intents[2]["claims"][0]["text"].split()), 6)

            payload = _planner_payload(intents)

            def fake_planner(_prompt: str, _paths: list[Path], **kwargs: object) -> str:
                self.assertIn("You are the sole visual designer", _prompt)
                self.assertIn("COLOR ANALYSIS AID (NOT DESIGN AUTHORITY)", _prompt)
                self.assertIn("palette_direction is the sole final child palette", _prompt)
                self.assertIn("Product identity:", _prompt)
                self.assertNotIn("Known product facts:", _prompt)
                self.assertIn("Bind every exact display string", _prompt)
                self.assertLessEqual(len(_prompt), 8000)
                observer = kwargs.get("attempt_observer")
                if callable(observer):
                    observer({
                        "provider": "ccsub",
                        "model": "gemini-3.5-flash",
                        "attempt": 1,
                        "status": "success",
                        "elapsed_ms": 10,
                    })
                return json.dumps(payload)

            with (
                patch("core.visual_design_kit.read_product_family", return_value=family),
                patch("core.visual_design_kit.read_run_scope", return_value=scope),
                patch("core.visual_design_kit.selected_task_source_intents", return_value=intents),
                patch("core.visual_design_kit.load_job", return_value={}),
                patch("core.visual_design_kit.load_env", return_value={}),
                patch(
                    "core.visual_design_kit.gemini_scope_identity",
                    return_value=[{
                        "provider": "ccsub",
                        "model": "gemini-3.5-flash",
                    }],
                ),
                patch(
                    "core.visual_design_kit.gemini_stream_generate",
                    side_effect=fake_planner,
                ),
            ):
                result = build_visual_design_kits(
                    job_dir=job,
                    plugin=_Plugin(),
                    workers=1,
                )
            self.assertFalse(result["failures"])
            kit = read_visual_design_kits(job, plugin=_Plugin())["tasks"][0]
            self.assertIn("family_art_direction", kit)
            self.assertNotIn("product_visual_read", kit)
            self.assertNotIn("family_visual_signature", kit)
            self.assertEqual(payload["family_art_direction"]["environment_and_staging"], kit["family_art_direction"]["environment_and_staging"])
            self.assertEqual(payload["family_art_direction"]["photography_direction"], kit["family_art_direction"]["photography_direction"])
            self.assertNotIn("open storage", json.dumps(kit["source_briefs"]).casefold())
            self.assertGreaterEqual(len(Path(kit["planner"]["prompt_path"]).parts), 6)
            scene_brief = next(row for row in kit["source_briefs"] if row["role"] == "scene")
            scene_intent = next(row for row in intents if row["role"] == "scene")
            self.assertEqual(payload["source_briefs"][1]["shopping_purpose"], scene_brief["shopping_purpose"])

            with (
                patch("core.image_tasks.read_product_family", return_value=family),
                patch("core.image_tasks.read_run_scope", return_value=scope),
                patch("core.image_tasks.selected_task_source_intents", return_value=intents),
                patch("core.image_tasks.planning_source_intents", return_value=intents),
            ):
                task_result = build_image_tasks(job_dir=job, plugin=_Plugin())
            self.assertFalse(task_result["failures"])
            tasks = read_image_tasks(job, category_id=_Plugin.category_id)["tasks"]
            self.assertEqual(4, len(tasks))
            for task in tasks:
                references = task["generation_references"]
                self.assertEqual(1, len(references))
                self.assertEqual("edit_base", references[0].get("kind"))
                self.assertEqual([{"name": "White", "source": references[0]["source_id"]}], task["product_boundary"]["observed_product_colors"])
            func_source = next(row for row in intents if row["role"] == "func")
            func_brief = next(row for row in kit["source_briefs"] if row["role"] == "func")
            selection = {"source_id": "source_00", "purpose": "Verify the complete cabinet structure", "evidence_ids": []}
            typed_refs = _generation_references_for_task(
                func_source, {**func_brief, "supporting_sources": [selection]}, kit, child=kit["child"],
            )
            self.assertEqual(["edit_base", "product_evidence"], [ref["kind"] for ref in typed_refs])
            self.assertEqual("source_00", typed_refs[1]["source_id"])
            with self.assertRaises(ValueError):
                _generation_references_for_task(func_source, {**func_brief, "supporting_sources": [
                    {**selection, "source_id": "another-child-source"}]}, kit, child=kit["child"])
            self.assertTrue(all(task["product_facts"]["product_type"] == "BATHROOM_CABINET" for task in tasks))
            self.assertTrue(all("mirror" not in json.dumps(task["product_boundary"]).casefold() for task in tasks))

            prompt_result = build_image_prompts(job_dir=job, plugin=_Plugin())
            self.assertFalse(prompt_result["failures"])
            prompts = read_image_prompts(
                job,
                category_id=_Plugin.category_id,
            )["prompts"]
            for row in prompts:
                self.assertLessEqual(len(row["prompt"]), PROMPT_HARD_LIMIT_CHARS)
                self.assertIn("[STYLE]", row["prompt"])
                self.assertNotIn("[FAMILY ART DIRECTION]", row["prompt"])
                self.assertNotIn("Product Visual Read", row["prompt"])
                self.assertNotIn("Family Visual Signature", row["prompt"])
                self.assertTrue((job / row["prompt_path"]).is_file())
            func_prompt = next(row["prompt"] for row in prompts if row["role"] == "func")
            self.assertIn("composition prose and source marketing supply no additional display text", func_prompt)
            self.assertIn("Ordinary unbranded prop text is allowed", func_prompt)
            self.assertNotIn("no readable text anywhere", func_prompt)
            self.assertNotIn("layout archetype", func_prompt.casefold())
            self.assertIn("Use an editorial asymmetric feature layout", func_prompt)
            self.assertIn("including colored highlights drawn over the product", func_prompt)
            self.assertIn("Adjustable Shelf", func_prompt)
            self.assertIn("Different Object Heights", func_prompt)
            self.assertIn("Wall-Mounted Organization", func_prompt)
            self.assertIn("do not infer hidden regions", func_prompt)
            self.assertIn("preserve the evidence, not the source graphic framing", func_prompt)
            self.assertIn("Keep the protected source content unchanged", func_prompt)
            self.assertIn("Graphic system: Restrained technical lines", func_prompt)
            self.assertIn("Typography system: Confident contemporary sans-serif", func_prompt)
            self.assertNotIn("Derive the new palette from sold-product body color", func_prompt)
            self.assertNotIn("Rebuild all non-sold props, background, graphic layout", func_prompt)
            self.assertIn("Remove or replace source people, hands, faces, and reflected people", func_prompt)
            self.assertNotIn("Edit the role source in place", func_prompt)
            self.assertIn("Child palette:", func_prompt)
            self.assertIn("do not recolor the sold product or add a room to a technical diagram", func_prompt)
            self.assertNotIn("when it improves hierarchy", func_prompt)
            self.assertIn("highly legible", func_prompt)
            self.assertNotIn("Cohesion Rule:", func_prompt)
            size_prompt = next(row["prompt"] for row in prompts if row["role"] == "size")
            self.assertIn("with readable spacing", size_prompt)
            self.assertIn("Use generous technical spacing", size_prompt)
            self.assertIn("no extra feature cards or duplicate measurement labels", size_prompt)
            self.assertIn("Typography system: Confident contemporary sans-serif", size_prompt)
            self.assertNotIn("when it improves hierarchy", size_prompt)
            self.assertNotIn("Audience And Market:", size_prompt)
            self.assertNotIn("Environment And Staging:", size_prompt)
            main_prompt = next(row["prompt"] for row in prompts if row["role"] == "main")
            self.assertIn("uniform pure-white canvas", main_prompt)
            self.assertNotIn("Market context:", main_prompt)
            self.assertNotIn("Use the room tokens", main_prompt)
            self.assertNotIn("Child palette:", main_prompt)

    def test_environment_text_does_not_promote_a_scene_to_func(self) -> None:
        from core.visual_semantics import _validate_observations, OBSERVATION_POLICY
        observed = {"source_id": "source_00", "role_guess": "scene", "has_dimension_lines": False,
                    "has_callouts_or_panels": False, "confidence": .9, "visible_numbers_or_units": [], "evidence": [],
                    "objects": [{"object_id": "cloth", "kind": "cloth", "sale_membership": "unknown",
                                 "visibility": "occluded", "state": "folded", "membership_evidence": [], "relations": []}],
                    "text_observations": [{"text": "Goodnight", "kind": "prop"}],
                    "variant_identity": {"status": "unknown", "observed_color": "", "reason": "Occluded view", "conflicts": []}}
        self.assertEqual("unknown", _validate_observations([observed], ["source_00"], {})["source_00"]["objects"][0]["sale_membership"])
        from core.visual_semantics import observe_child_sources
        with tempfile.TemporaryDirectory() as tmp, patch("core.visual_semantics.gemini_stream_generate", return_value=json.dumps({"sources": [observed]})) as request:
            sources = [{"source_id": "source_00", "sha256": "a" * 64, "ocr": [], "path": Path(tmp) / "source.png"}]
            self.assertEqual(observe_child_sources(Path(tmp), {"asin": "B1"}, sources), observe_child_sources(Path(tmp), {"asin": "B1"}, sources))
            self.assertEqual(1, request.call_count)
        with self.assertRaisesRegex(ValueError, "omitted"):
            _validate_observations([observed], ["source_00", "source_01"], {})
        observed["objects"][0]["sale_membership"] = "included_accessory"
        with self.assertRaisesRegex(ValueError, "requires product evidence"):
            _validate_observations([observed], ["source_00"], {})
        observed["objects"][0]["sale_membership"] = "unknown"
        observed["objects"][0]["relations"] = [{"predicate": "contained_in", "target_id": "unobserved_drawer"}]
        with self.assertRaisesRegex(ValueError, "unobserved identity"):
            _validate_observations([observed], ["source_00"], {})
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "reports").mkdir(parents=True)
            rows, evidence = self._source_fixture(job)
            rows = rows[:2]
            source = evidence[rows[1]["source_sha256"]]
            source.update({
                "ocr_evidence": {
                    "available": True,
                    "raw_text": "Multi-scene Application Pathway Wedding Living Room",
                    "lines": [
                        {"text": "Multi-scene Application", "confidence": 0.95},
                        {"text": "Pathway", "confidence": 0.92},
                    ],
                },
                "trusted_text": ["Multi-scene Application", "Pathway"],
                "claims": [],
                "pixel_evidence": {
                    "scene_pixels": True,
                    "product_view_pixels": False,
                },
                "visual_evidence": {
                    "status": "failed",
                    "role_guess": "unknown",
                    "confidence": 0.0,
                    "error": "visual provider unavailable",
                },
            })
            with (
                patch("core.final_source_intents.ensure_run_scope"),
                patch(
                    "core.final_source_intents.download_artifacts_current",
                    return_value=(True, []),
                ),
                patch(
                    "core.final_source_intents.read_download_manifest",
                    return_value={"schema_version": "download-manifest-v2", "rows": rows},
                ),
                patch("core.final_source_intents.read_product_family", return_value=_family()),
                patch("core.final_source_intents.row_in_scope", return_value=True),
                patch(
                    "core.final_source_intents._collect_evidence_by_sha",
                    return_value={
                        row["source_sha256"]: evidence[row["source_sha256"]]
                        for row in rows
                    },
                ),
                patch("core.final_source_intents.observe_child_sources", return_value={
                    f"source_{index:02d}": evidence[row["source_sha256"]]["visual_evidence"] for index, row in enumerate(rows)
                }),
            ):
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                classified = read_final_source_intents(job, plugin=_Plugin())
            recovered = classified[1]
            self.assertEqual("review_required", recovered["role"])
            self.assertEqual([], recovered["claims"])
            self.assertIn("source_identity_unverified", recovered["classification_reason"])
            source["visual_evidence"] = {
                "status": "success",
                "policy_version": OBSERVATION_POLICY,
                "child_facts_revision_id": _evidence("scene")["visual_evidence"]["child_facts_revision_id"],
                "variant_identity": observed["variant_identity"],
                "role_guess": "func",
                "confidence": 0.9,
                "has_callouts_or_panels": True,
                "evidence": ["A labeled multi-scene panel"],
            }
            with (
                patch("core.final_source_intents.ensure_run_scope"),
                patch("core.final_source_intents.download_artifacts_current", return_value=(True, [])),
                patch("core.final_source_intents.read_download_manifest", return_value={"schema_version": "download-manifest-v2", "rows": rows}),
                patch("core.final_source_intents.read_product_family", return_value=_family()),
                patch("core.final_source_intents.row_in_scope", return_value=True),
                patch(
                    "core.final_source_intents._collect_evidence_by_sha",
                    return_value={row["source_sha256"]: evidence[row["source_sha256"]] for row in rows},
                ),
                patch("core.final_source_intents.observe_child_sources", return_value={
                    f"source_{index:02d}": evidence[row["source_sha256"]]["visual_evidence"] for index, row in enumerate(rows)
                }),
            ):
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                classified = read_final_source_intents(job, plugin=_Plugin())
            recovered = classified[1]
            self.assertEqual("func", recovered["role"])
            self.assertEqual([], recovered["claims"])

    def test_measurements_merge_equivalent_units_and_reject_zero_weight(self) -> None:
        from core.final_source_intents import _independent_measurements, _measurement_rows
        from core.image_tasks import _measurement_authority
        from core.text_evidence import extract_measurements
        observed = []
        for line_index, line in enumerate(["Overall Width 36 in", "Drawer Width 36 in", "24 W x 24 D x 30 H in"]):
            observed.extend({**row, "source_label": line, "source_occurrence": f"{line_index}:{index}"}
                            for index, row in enumerate(extract_measurements(line)))
        self.assertEqual(5, len(_independent_measurements(observed)))
        source = {"role": "size", "measurements": _measurement_rows(observed, {})}
        authority = _measurement_authority("size", {}, source)
        self.assertEqual(["w", "d", "h"], [r["axis"] for r in authority["measurement_groups"][-3:]])
        content = _measurement_content(authority)
        self.assertIn("Overall Width 36 in", content)
        self.assertIn("Drawer Width 36 in", content)
        self.assertEqual(1, content.count("24 W x 24 D x 30 H in"))
        content = _measurement_content({
            "mode": "source_image",
            "measurement_groups": [{"measured_part": "Overall Height", "render_text": "3 ft"},
                                   {"measured_part": "Drawer Height", "render_text": "36 in"}],
            "source_visible_callouts": ["Weight Capacity: 440 lbs"],
            "source_visible_text_artifacts": [
                {"kind": "measurement", "display_text": "Overall Height: 36 in"},
                {"kind": "callout", "display_text": "Weight Capacity: 440 lbs"},
                {"kind": "measurement", "text": "440"},
            ],
        })
        self.assertEqual(1, content.count("Overall Height"))
        self.assertEqual(1, content.count("Drawer Height"))
        self.assertEqual(1, content.count("440"))
        equivalent = {
            "normalized_facts": {
                "spec_measurement_records": [
                    {"field": "Height", "text": "3 ft"},
                    {"field": "Height", "text": "36 in"},
                ]
            }
        }
        contract = measurement_contract(equivalent)
        self.assertEqual("confirmed", contract["status"])
        self.assertEqual(1, len(contract["render_text"]))
        zero = {
            "normalized_facts": {
                "spec_measurement_records": [
                    {"field": "Maximum Weight Recommendation", "text": "0 lbs"}
                ]
            }
        }
        self.assertEqual("conflicted", measurement_contract(zero)["status"])

    def test_planner_cannot_reintroduce_product_fact_authority(self) -> None:
        import random
        import sys
        try:
            import colour
        except ImportError:
            colour = None
        from core.palette_registry import _ciede2000, _delta_e, _srgb_lab, select_palette_route
        pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
                 ((50, 0, 0), (50, -1, 2), 2.3669)]
        for first, second, expected in pairs:
            self.assertAlmostEqual(expected, _ciede2000(first, second), places=4)
        randomizer = random.Random(64)
        colors = [(0., 0., 0.), (1., 1., 1.), (.5, .5, .5)] + [tuple(randomizer.random() for _ in range(3)) for _ in range(12)]
        for first in colors:
            for second in colors:
                expected = (float(colour.delta_E(_srgb_lab(first), _srgb_lab(second), method="CIE 2000"))
                            if colour is not None else _ciede2000(_srgb_lab(second), _srgb_lab(first)))
                self.assertAlmostEqual(expected, _ciede2000(_srgb_lab(first), _srgb_lab(second)), places=9)
        for color in ("White", "Natural", "Blue", "Espresso"):
            args = {"category_id": "bed_frame", "product_color": color, "route_key": "semantic-audit-child"}
            expected = select_palette_route(**args)
            with patch.dict(sys.modules, {"colour": None}):
                actual = select_palette_route(**args)
                self.assertEqual(0, _delta_e((.5, .5, .5), (.5, .5, .5))[0])
            for key in ("palette", "route_id", "selection_score", "selection_components", "recipe"):
                self.assertEqual(expected[key], actual[key], (color, key))
        sources = [{
            "source_id": "source_00",
            "source_index": 0,
            "role": "main",
            "source_path": "main.png",
            "source_sha256": "m",
            "input_revision_id": "mr",
            "shopping_intent": "",
            "claims": [],
            "product_claims": [],
            "measurements": [],
        }, {
            "source_id": "source_01",
            "source_index": 1,
            "role": "scene",
            "source_path": "scene.png",
            "source_sha256": "s",
            "input_revision_id": "sr",
            "shopping_intent": "Show realistic room use and product scale.",
            "claims": [],
            "product_claims": [],
            "measurements": [],
        }]
        draft = {
            "family_art_direction": current_art_direction(),
            "source_briefs": [{
                "source_id": "source_01",
                "image_direction": "Show an authentic room use moment.",
                "shopping_purpose": "Show realistic room use and product scale.",
            }],
            "product_visual_read": {
                "sold_product_parts": ["invented mirror"],
            },
        }
        compiled = compile_visual_design_kit_response(
            draft,
            source_manifest=sources,
        )
        self.assertEqual(
            {"family_art_direction", "source_briefs"},
            set(compiled),
        )
        self.assertEqual(
            "Show an authentic room use moment.",
            compiled["source_briefs"][-1]["image_direction"],
        )
        open_feel = json.loads(json.dumps(draft))
        open_feel["family_art_direction"]["typography_direction"] = (
            "Use a geometric sans-serif with generous spacing to preserve the open feel of the room."
        )
        compiled_open_feel = compile_visual_design_kit_response(open_feel, source_manifest=sources)
        self.assertEqual(
            "Use a geometric sans-serif with generous spacing to preserve the open feel of the room.",
            compiled_open_feel["family_art_direction"]["typography_direction"],
        )
        visible_state = json.loads(json.dumps(draft))
        visible_state["family_art_direction"]["environment_and_staging"] = (
            "Keep the two open doors visible as shown in the editable reference."
        )
        compiled_state = compile_visual_design_kit_response(visible_state, source_manifest=sources)
        self.assertIn("two open doors", compiled_state["family_art_direction"]["environment_and_staging"])
        state_decision = json.loads(json.dumps(draft))
        state_decision["family_art_direction"]["environment_and_staging"] = (
            "Show two open doors in every role."
        )
        with self.assertRaisesRegex(VisualDesignKitCompileError, "changes a source-visible product state"):
            compile_visual_design_kit_response(state_decision, source_manifest=sources)
        overlong = json.loads(json.dumps(draft))
        overlong["family_art_direction"]["audience_and_market"] = "x" * 2201
        with self.assertRaisesRegex(VisualDesignKitCompileError, "exceeds 2200"):
            compile_visual_design_kit_response(overlong, source_manifest=sources)
        for field, instruction in (
            ("source_brief", "Title: Spacious Everyday Storage"),
            ("audience_and_market", "Set the headline to Modern Loft Bed in charcoal ink."),
            ("negative_visuals", "The visible label reads Premium Storage"),
        ):
            polluted = json.loads(json.dumps(draft))
            if field == "source_brief":
                polluted["source_briefs"][0]["image_direction"] = instruction
            elif field == "negative_visuals":
                polluted["family_art_direction"][field][0] = instruction
            else:
                polluted["family_art_direction"][field] = instruction
            if field == "source_brief":
                failed = compile_visual_design_kit_response(polluted, source_manifest=sources)
                self.assertEqual("pending", failed["source_briefs"][-1]["status"])
                self.assertIn("renderable-copy instruction", failed["source_briefs"][-1]["error"])
            else:
                with self.assertRaisesRegex(VisualDesignKitCompileError, "renderable-copy instruction"):
                    compile_visual_design_kit_response(polluted, source_manifest=sources)
        artificial_scene = json.loads(json.dumps(draft))
        artificial_scene["source_briefs"][0]["image_direction"] = (
            "Restyle the front door, wall siding, floor, and doormat while keeping the tree and pot unchanged."
        )
        compiled_tree = compile_visual_design_kit_response(
            artificial_scene, source_manifest=sources, category_id="artificial_tree",
        )
        self.assertIn("front door", compiled_tree["source_briefs"][-1]["image_direction"])
        sold_change = json.loads(json.dumps(artificial_scene))
        sold_change["source_briefs"][0]["image_direction"] = "Replace the tree and pot with a new container."
        failed = compile_visual_design_kit_response(sold_change, source_manifest=sources, category_id="artificial_tree")
        self.assertEqual("pending", failed["source_briefs"][-1]["status"])
        self.assertIn("source-visible product state", failed["source_briefs"][-1]["error"])

    def test_func_story_contract_is_single_evidence_bound_authority(self) -> None:
        from core.visual_design_kit_compiler import _bind_func_story_text, claim_review_requests
        from core.visual_semantics import claim_key, CLAIM_REVIEW_POLICY
        for evidence, proposed in (("Natural pine wood", "Waterproof Finish"), ("2 doors", "2 drawers")):
            with self.assertRaisesRegex(VisualDesignKitCompileError, "independent evidence review"):
                _bind_func_story_text({"evidence_ids": ["e1"], "text": proposed}, {"e1": evidence})
        source = {"source_id": "source_01", "source_index": 1, "role": "func",
                  "source_sha256": "f", "input_revision_id": "fr", "source_path": "func.png",
                  "shopping_intent": "show shelf", "measurements": [], "product_claims": [],
                  "claims": [{"evidence_id": "e1", "text": "Adjustable Shelf", "source_sha256": "f",
                              "type": "visible_function_text", "confidence": "source_visible"}]}
        draft = {"family_art_direction": current_art_direction(), "source_briefs": [{
            "source_id": "source_01", "shopping_purpose": "Explain adjustable storage.",
            "image_direction": "Use ivory towels, charcoal lettering and natural oak staging around the unchanged cabinet.",
            "func_story": {"title": {"evidence_ids": ["e1"], "text": "Adjust Shelf Height"}, "labels": []},
        }]}
        pending = compile_visual_design_kit_response(draft, source_manifest=[source])
        self.assertEqual("pending", pending["source_briefs"][0]["status"])
        key = claim_key("Adjust Shelf Height", {"e1": "Adjustable Shelf"})
        review = {key: {"key": key, "policy": CLAIM_REVIEW_POLICY, "status": "supported",
                        "reason": "The shelf height is adjustable.", "response_sha256": "a" * 64}}
        compiled = compile_visual_design_kit_response(draft, source_manifest=[source], claim_reviews=review)
        brief = compiled["source_briefs"][0]
        self.assertEqual("ready", brief["status"])
        self.assertEqual(draft["source_briefs"][0]["image_direction"], brief["image_direction"])
        self.assertEqual("Adjust Shelf Height", build_func_story_contract(source, brief)["title"])
        self.assertEqual(1, len(claim_review_requests(draft, [source])))
        draft["source_briefs"][0]["func_story"]["title"]["text"] = "Waterproof Finish"
        stale = compile_visual_design_kit_response(draft, source_manifest=[source], claim_reviews=review)
        self.assertEqual("pending", stale["source_briefs"][0]["status"])
        draft["source_briefs"][0]["func_story"]["title"] = {}
        empty = compile_visual_design_kit_response(draft, source_manifest=[source], claim_reviews=review)
        self.assertEqual("pending", empty["source_briefs"][0]["status"])
        self.assertNotIn("func_story_contract", empty["source_briefs"][0])
        draft["source_briefs"][0]["func_story"] = {"title": None, "labels": []}
        no_copy = compile_visual_design_kit_response(draft, source_manifest=[source])["source_briefs"][0]
        self.assertEqual("ready", no_copy["status"])
        self.assertEqual([], build_func_story_contract(source, no_copy)["bindings"])
        from core.image_task_inputs import task_facts, func_renderable_text_contract
        self.assertEqual([], func_renderable_text_contract(no_copy["func_story_contract"])["strings"])
        child = {"sold_unit_count": 1, "sold_unit_count_source": "amazon_single_unit_listing_policy"}
        self.assertIsNone(task_facts(child, product_type="BED_FRAME")["sold_unit_count"])
        child.update(sold_unit_count=2, sold_unit_count_source="apify_explicit_pack_count")
        self.assertEqual(2, task_facts(child, product_type="BED_FRAME")["sold_unit_count"])


if __name__ == "__main__":
    unittest.main()
