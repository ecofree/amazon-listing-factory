from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from tests.current_image_contract_fixture import current_physical_view

from core.final_source_intents import (
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
from core.image_reference_context import resolve_edit_references
from core.image_task_inputs import (
    build_display_copy_contract,
    measurement_contract,
    task_specs,
    visual_product_color,
    visual_variation_values,
)
from core.image_tasks import (
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
                    "func": ["show only source-demonstrated functions"], "size": ["preserve measured objects, quantities and endpoint associations"],
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
    from core.visual_semantics import OBSERVATION_POLICY, source_fact_records
    from tests.current_image_contract_fixture import current_observed_measurement
    from core.status import input_revision_id
    text = (["Adjustable shelf provides 3positions for different object heights."] if role == 'func'
            else ["Width 24 in", "Height 30 in"] if role == 'size' else [])
    return {"visual_evidence": {
        "status": "success", "policy_version": OBSERVATION_POLICY,
        "role_guess": "scene" if role == "main" else role, "confidence": .92,
        "has_callouts_or_panels": role == 'func', "has_dimension_lines": role == 'size',
        "visible_numbers_or_units": ['24 in', '30 in'] if role == 'size' else [],
        "evidence": [], "evidence_gaps": [], "text_gaps": [],
        "child_facts_revision_id": input_revision_id(source_fact_records(_child())),
        "variant_identity": {"status": "unknown", "observed_color": "", "conflicts": [], "reason": "Fixture cropped view"},
        "objects": [{"object_id": "frame", "kind": "cabinet", "sale_membership": "product",
                     "membership_evidence": [{"fact_id": "product.title", "quote": _child()['title']}],
                     "visibility": "visible", "state": "intact"}],
        "physical_views": [current_physical_view()],
        "reference_views": [{"view_id": "view_01", "purposes": ['feature', 'measurement'] if role == 'size' else ['appearance'] if role == 'main' else ['feature']}],
        "measurements": [current_observed_measurement('24 in', axis='width', key='width'),
                         {**current_observed_measurement('30 in', axis='height', key='height'), 'region': dict(left=.4, top=.25, right=.5, bottom=.3)}] if role == 'size' else [],
        "text_observations": [{"text": value, "kind": "product_fact" if role == "func" else "measurement"} for value in text],
    }}


from tests.current_image_contract_fixture import current_image_direction


def _planner_payload(intents: list[dict]) -> dict:
    claims = compact_product_claims(_child())
    wall_mount_claim = next(row for row in claims if row['field_path'] == 'product.bullets.1')
    briefs = []
    for spec in task_specs(_child(), intents, include_optional=True):
        source = spec['source']
        if source is None:
            continue
        family = spec['role'].split('_', 1)[0]
        source_id = f"source_{source['source_index']:02d}"
        brief = {'role': spec['role'], 'source_id': source_id, 'image_direction': current_image_direction(
            source_id=source_id, environment='graphic_canvas' if family == 'size' else 'designed_environment')}
        if family == 'func':
            evidence_id = source['claims'][0]['evidence_id']
            brief['display_copy'] = {
                'title': {'evidence_ids': [evidence_id], 'text': 'Adjustable Shelf'},
                'labels': [{'evidence_ids': [evidence_id], 'text': 'Different Object Heights'},
                           {'evidence_ids': [wall_mount_claim['evidence_id']], 'text': 'Wall-Mounted Organization'}]}
        elif family == 'size':
            brief['display_copy'] = {'title': None, 'labels': []}
        briefs.append(brief)
    return {'family_art_direction': current_art_direction(), 'image_briefs': briefs}

def _fixture_observation(_job, _child, sources, **kwargs):
    return {row["source_id"]: {**_evidence(("main", "scene", "func", "size")[int(row["source_id"].split("_")[1])])["visual_evidence"], "source_id": row["source_id"],
        "variant_identity": {"status": "consistent", "observed_color": "White", "reason": "Observed white finish", "conflicts": []}} for row in sources}


def _fixture_reviews(claims, **kwargs):
    from core.visual_semantics import CLAIM_REVIEW_POLICY
    records = [{"key": row["key"], "status": "supported", "reason": "fixture verified property",
                'findings': [{'operation': op, 'status': 'supported',
                              'reason': 'Fixture original/crop pixels retain the measured body'} for op in row.get('physical_operations', [])]} for row in claims]
    path = kwargs["trace_dir"] / "claim_review_response.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"reviews": records}), encoding="utf-8")
    return {row["key"]: {**row, "policy": CLAIM_REVIEW_POLICY, "response_path": str(path.resolve()),
                         "response_sha256": file_sha256(path)} for row in records}


class ImageBranchCurrentBehaviorTests(unittest.TestCase):
    def setUp(self):
        for target, response in (
            ("core.final_source_intents.observe_child_sources", _fixture_observation),
            ("core.visual_design_kit.review_planning_bindings", _fixture_reviews),
            ("core.visual_design_kit.gemini_stream_generate", AssertionError("Unexpected planner request")),
            ("core.final_source_intents.ocr_evidence_for_image", AssertionError("Unexpected OCR request")),
        ):
            patched = patch(target, side_effect=response)
            patched.start()
            self.addCleanup(patched.stop)

    def test_compiled_prompt_preserves_design_facts_and_units(self) -> None:
        from copy import deepcopy
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
                task["edit_contract"] = _edit_contract(role, task["measurement_authority"], policy)
                if role == "size":
                    task["image_direction"]["visual_goal"] = "Clarify overall product dimensions and drawer size."
                prompt = compile_task_prompt(task=task)
                for section in ("ROLE", "REFERENCE", "STYLE", "TEXT", "OUTPUT"):
                    self.assertEqual(1, prompt.count(f"[{section}]"))
                for owner, key, section in (("image_direction", "visual_goal", "ROLE"),
                                            ("family_art_direction", "audience_and_market", "ROLE")):
                    original = task[owner][key]
                    self.assertEqual(1, prompt.count(original))
                    self.assertIn(original, prompt.split(f"[{section}]\n")[1].split("\n\n[")[0])
                    changed = deepcopy(task)
                    changed[owner][key] = original + " Updated Gemini intent."
                    self.assertEqual(prompt.replace(original, changed[owner][key]), compile_task_prompt(task=changed))
                self.assertNotIn("Forbidden additions:", prompt)
                self.assertIn("Identity: type=BATHROOM_CABINET; color=soft white; sold quantity=1", prompt)
                for forbidden in task["edit_contract"]["forbid"]:
                    self.assertIn(forbidden.rstrip(" .;:"), prompt)
                if role == "size":
                    self.assertIn('retain its measured object and endpoints', prompt)
                styles[role] = prompt.split("[STYLE]\n")[1].split("\n\n[TEXT]")[0]
                self.assertNotIn("or readable text", prompt)
                if category != "bed_frame":
                    self.assertNotIn("mattress", prompt.casefold())
                elif role in {"main", "scene"}:
                    self.assertIn('mattress, bedding, pillows', prompt)
            self.assertIn("bath.towels = #8A999E", styles["func"])
            self.assertEqual(1, styles['func'].count('towels = #8A999E'))
            self.assertNotIn("bath.towels = #8A999E", styles["size"])
            self.assertNotIn("Staging intent", styles["size"])
            for prefix in ("Typography:", "Graphic roles:"):
                self.assertEqual(next(line for line in styles["func"].splitlines() if line.startswith(prefix)),
                                 next(line for line in styles["size"].splitlines() if line.startswith(prefix)))
            if category != "bed_frame":
                self.assertIn("Photography standard", styles["main"])
                self.assertIn("white external background", styles["main"])
                self.assertNotIn("room tokens:", styles["main"])
            self.assertIn("font_family = Inter", styles["func"])
            self.assertIn("text_color = #303634", styles["size"])
        task = current_image_task('func')
        task["image_direction"]["environment_mode"] = "graphic_canvas"
        task['image_direction']['presentation']['scope'] = 'detail_only'
        compiled = compile_task_prompt(task=task)
        self.assertIn('Depict only the selected product details', compiled)
        self.assertIn('not a reconstructed whole product', compiled)
        self.assertNotIn('Product presentation: detail_only', compiled)
        self.assertIn('not a reconstructed whole product or all units in the package', compiled)
        self.assertIn("Design hierarchy and line breaks freely", compiled)
        self.assertIn("only small local legibility backing is permitted", compiled)
        self.assertIn("not large pill titles or capsule label systems", compiled)
        self.assertNotIn(task['family_art_direction']['environment_and_staging'], compiled)
        self.assertNotIn('room.wall =', compiled)
        for system in ('typography_direction', 'graphic_direction'):
            for key, value in task['family_art_direction'][system].items():
                self.assertEqual(1, compiled.count(f'{key} = {value}'))
        self.assertEqual(task['renderable_text_contract']['strings'], compiled.split('<RENDERABLE_TEXT>\n')[1].split('\n</RENDERABLE_TEXT>')[0].splitlines())
        shared = compile_task_prompt(task=task)
        self.assertEqual(1, shared.count('#8A999E cotton'))
        self.assertEqual(1, shared.count('bath.towels ='))
        task['generation_references'][0]['visible_evidence'] = [dict(current_physical_view()['evidence'][0], physical_facts=['Platform frame without headboard'])]
        task['measurement_authority'] = {'mode': 'source_image', 'measurement_groups': [{
            'source_id': 'source_00', 'view_id': 'view_01', 'measured_part': 'Underbed clearance',
            'axis': 'height', 'render_text': '12 in', 'source_region': dict(left=.2, top=.25, right=.3, bottom=.3),
            'source_endpoints': [{'x': .2, 'y': .4}, {'x': .7, 'y': .4}]}]}
        task['generation_references'][0]['original_region'] = dict(left=.1, top=.2, right=.9, bottom=.8)
        self.assertIn('"attachment":1', compile_task_prompt(task=task))
        task['measurement_authority']['measurement_groups'][0]['source_region'] = dict(left=.02, top=.04, right=.07, bottom=.06)
        with self.assertRaisesRegex(ValueError, 'missing from its actual source/view attachments'):
            compile_task_prompt(task=task)
        support = deepcopy(task['generation_references'][0])
        support.update(kind='product_evidence', source_id='source_99')
        support['visible_evidence'][0]['physical_facts'] = ['OTHER_VIEW_STATE']
        task['generation_references'].append(support)
        measurement = deepcopy(task['generation_references'][0])
        measurement.update(kind='measurement_evidence', purpose='Verification only', original_region=dict(left=0, top=0, right=1, bottom=1))
        measurement['visible_evidence'][0]['physical_facts'] = ['MEASUREMENT_CROP_IS_NOT_APPEARANCE']
        task['generation_references'].append(measurement)
        scoped = compile_task_prompt(task=task)
        self.assertEqual(1, scoped.count('Platform frame without headboard'))
        self.assertEqual(1, scoped.count('Underbed clearance / height: 12 in'))
        self.assertIn('"attachment":3', scoped)
        for absent in ('OTHER_VIEW_STATE', 'MEASUREMENT_CROP_IS_NOT_APPEARANCE', 'cyan dashed outline', 'occludes'):
            self.assertNotIn(absent, scoped)
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
                patch("core.final_source_intents.ocr_evidence_for_image") as ocr,
            ):
                build_final_source_intents(job_dir=job, plugin=_Plugin())
                ocr.assert_not_called()
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
                alternate = _fixture_observation(job, _child(), [{'source_id': f'source_{i:02d}'} for i in range(4)])
                alternate['source_00']['variant_identity'] = observed['source_01']['variant_identity']
                alternate['source_01']['reference_views'][0]['purposes'] = ['appearance']
                with patch('core.final_source_intents.observe_child_sources', return_value=alternate):
                    build_final_source_intents(job_dir=job, plugin=_Plugin())
                    recovered = read_final_source_intents(job, plugin=_Plugin())
                    self.assertEqual(['review_required', 'main', 'func', 'size'], [row['role'] for row in recovered])
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
            claim_text = {row['evidence_id']: row['text'] for row in compact_product_claims(_child())}
            wall_copy = next(label for brief in payload['image_briefs'] if brief['role'] == 'func'
                             for label in brief['display_copy']['labels'] if label['text'] == 'Wall-Mounted Organization')
            self.assertEqual(['Wall-mounted storage keeps bathroom essentials within reach.'],
                             [claim_text[key] for key in wall_copy['evidence_ids']])

            def fake_planner(_prompt: str, _paths: list[Path], **kwargs: object) -> str:
                self.assertEqual(1, len(_paths))
                self.assertTrue(all(path.parent.name == "evidence_views" for path in _paths))
                self.assertTrue(all(file_sha256(path) != row["source_sha256"] for path, row in zip(_paths, intents)))
                self.assertIn('"view_id":"view_01"', _prompt)
                self.assertIn('physical:source_00:view_01:frame_support:0', _prompt)
                self.assertIn("you plan the child-wide visual direction", _prompt)
                self.assertNotIn("computed_starting_palette", _prompt)
                self.assertIn("GPT image model designs each composition", _prompt)
                self.assertIn("Product identity:", _prompt)
                self.assertNotIn("Known product facts:", _prompt)
                self.assertIn('"display_copy"', _prompt)
                self.assertEqual(len(intents), _prompt.count('"source_supported_claim_ids"'))
                self.assertNotIn('"physical_evidence"', _prompt)
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
            from core.visual_design_kit import _planner_trace_current
            import shutil
            for brief in kit['image_briefs']:
                self.assertEqual('supported', brief['design_review']['status'])
                for review in brief.get('claim_reviews', {}).values():
                    self.assertFalse(Path(review['response_path']).is_absolute())
            with tempfile.TemporaryDirectory() as moved:
                shutil.copytree(job, Path(moved) / 'copied')
                self.assertTrue(_planner_trace_current(Path(moved) / 'copied', kit))
            absolute = json.loads(json.dumps(kit))
            reviewed = next(review for brief in absolute['image_briefs'] for review in brief.get('claim_reviews', {}).values())
            reviewed['response_path'] = str(job / reviewed['response_path'])
            self.assertFalse(_planner_trace_current(job, absolute))
            self.assertIn("family_art_direction", kit)
            self.assertNotIn("product_visual_read", kit)
            self.assertNotIn("family_visual_signature", kit)
            self.assertEqual(payload["family_art_direction"]["environment_and_staging"], kit["family_art_direction"]["environment_and_staging"])
            self.assertEqual(payload["family_art_direction"]["photography_direction"], kit["family_art_direction"]["photography_direction"])
            self.assertNotIn("open storage", json.dumps(kit["image_briefs"]).casefold())
            self.assertGreaterEqual(len(Path(kit["planner"]["prompt_path"]).parts), 6)
            scene_brief = next(row for row in kit["image_briefs"] if row["role"] == "scene")
            scene_intent = next(row for row in intents if row["role"] == "scene")
            self.assertEqual(payload["image_briefs"][1]["image_direction"]["visual_goal"], scene_brief["image_direction"]["visual_goal"])

            with (
                patch("core.image_tasks.read_product_family", return_value=family),
                patch("core.image_tasks.read_run_scope", return_value=scope),
                patch("core.image_tasks.selected_task_source_intents", return_value=intents),
                patch("core.image_tasks.planning_source_intents", return_value=intents),
            ):
                task_result = build_image_tasks(job_dir=job, plugin=_Plugin())
            self.assertFalse(task_result["failures"])
            self.assertEqual([], task_result['source_selection_audit'])
            tasks = read_image_tasks(job, category_id=_Plugin.category_id)["tasks"]
            self.assertEqual(4, len(tasks))
            from core.release_manifest import source_inventory_coverage
            downloads = {'rows': [{'child': row['child'], 'index': row['source_index'], 'status': 'ok',
                                  'source_sha256': row['source_sha256']} for row in tasks]}
            with patch('core.release_manifest.read_download_manifest', return_value=downloads), patch(
                    'core.release_manifest.read_final_source_intents', return_value=intents), patch(
                    'core.release_manifest.row_in_scope', return_value=True):
                coverage = source_inventory_coverage(job_path=job, plugin=_Plugin(), tasks=tasks)
            self.assertEqual(['covered'] * 4, [row['status'] for row in coverage['rows']])
            for task in tasks:
                references = task["generation_references"]
                self.assertEqual(['edit_base'],
                                 [ref['kind'] for ref in references])
                self.assertEqual("edit_base", references[0].get("kind"))
                self.assertEqual(dict(left=.1, top=.2, right=.9, bottom=.8), references[0]['original_region'])
                self.assertEqual(task["edit_base_sha256"], file_sha256(job / references[0]["path"]))
                self.assertEqual(task["source_sha256"], file_sha256(job / task["source_path"]))
                self.assertNotEqual(task["source_sha256"], task["edit_base_sha256"])
                self.assertNotIn('product_boundary', task)
            func_source = next(row for row in intents if row["role"] == "func")
            func_brief = next(row for row in kit["image_briefs"] if row["role"] == "func")
            selection = {"source_id": "source_00", "view_id": "view_01", "usage": "display", "covered_by": []}
            direction = {**func_brief['image_direction'], 'evidence_usage': [selection, *func_brief['image_direction']['evidence_usage']]}
            typed_refs = resolve_edit_references(
                {**func_brief, "image_direction": direction}, kit["source_references"], design_references=kit["approved_design_references"], job=job, child=kit["child"],
            )
            self.assertEqual(["edit_base", "product_evidence"], [ref["kind"] for ref in typed_refs])
            self.assertEqual("source_00", typed_refs[0]["source_id"])
            self.assertEqual("source_02", typed_refs[1]["source_id"])
            from core.image_tasks import _form_task, validate_image_task
            from core.image_prompt_compiler import compile_task_prompt
            from core.visual_semantics import candidate_view_targets
            from core.image_reference_context import measurement_attachment_location
            cross = json.loads(json.dumps(kit))
            direction['evidence_usage'].append({'source_id': 'source_03', 'view_id': 'view_01', 'usage': 'display', 'covered_by': []})
            from core.visual_design_kit import _brief_draft, _finish_image_briefs
            import time
            cross_raw = {'family_art_direction': cross['family_art_direction'], 'image_briefs': [_brief_draft(row) for row in cross['image_briefs']]}
            next(row for row in cross_raw['image_briefs'] if row['source_id'] == 'source_02')['image_direction'] = direction
            reviewed = _finish_image_briefs(cross_raw, job=job, child=kit['child'], product_claims=kit['product_claims'], source_manifest=cross['source_references'], category_id=_Plugin.category_id,
                source_paths=[], source_originals=[], trace_dir=job / 'cross_review', deadline_monotonic=time.monotonic()+10, cached=kit)
            self.assertTrue(all(row['status'] == 'ready' for row in reviewed['image_briefs']))
            cross['image_briefs'] = reviewed['image_briefs']
            formed = _form_task(job=job, plugin=_Plugin(), child=_child(),
                spec=next(row for row in task_specs(_child(), intents) if row['role'] == 'func'),
                design_kit=cross, image_policy=tasks[0]['category_image_policy'], product_type='BATHROOM_CABINET')
            self.assertEqual('ready', formed['formation_status'], formed['formation_reason'])
            validate_image_task(formed)
            self.assertEqual(['source_00', 'source_02', 'source_03'], [ref['source_id'] for ref in formed['generation_references']])
            self.assertEqual('product_evidence', formed['generation_references'][-1]['kind'])
            self.assertEqual(3, len(candidate_view_targets(formed)))
            for group in formed['measurement_authority']['measurement_groups']:
                self.assertTrue(group['id'].startswith('source_03:'))
                self.assertEqual(3, measurement_attachment_location(group, formed['generation_references'])['attachment'])
            self.assertTrue(formed['measurement_authority']['measurement_groups'])
            cross_prompt = compile_task_prompt(task=formed)
            self.assertIn('source_00/view_01: display', cross_prompt)
            self.assertIn('source_02/view_01: display', cross_prompt)
            self.assertIn('source_03/view_01: display', cross_prompt)
            self.assertNotIn('Supporting physical evidence only', cross_prompt)
            self.assertEqual(func_source['source_sha256'], formed['source_sha256'])
            self.assertEqual(typed_refs[0]['sha256'], formed['edit_base_sha256'])
            from core.image_qa import _semantic_gates
            from tests.test_qa_lite_v1 import _observed
            observed = _observed(formed)
            self.assertEqual('pass', _semantic_gates(formed, observed)[2]['status'])
            observed['product_comparisons'][0]['status'] = 'contradiction'
            self.assertEqual('fail', _semantic_gates(formed, observed)[2]['status'])
            observed['product_comparisons'].pop(0)
            self.assertEqual('inconclusive', _semantic_gates(formed, observed)[2]['status'])
            with self.assertRaisesRegex(ValueError, 'not observed in this child'):
                resolve_edit_references({**func_brief, "image_direction": {
                    **direction, 'evidence_usage': [{**selection, 'source_id': 'another-child-source'}]}}, kit["source_references"], design_references=kit["approved_design_references"], job=job, child=kit["child"])
            self.assertTrue(all(task["product_facts"]["product_type"] == "BATHROOM_CABINET" for task in tasks))
            self.assertTrue(all("mirror" not in json.dumps(task["product_facts"]).casefold() for task in tasks))

            from core.visual_design_kit import _local_evidence_repair, compact_product_facts, visual_design_kit_prompt
            repaired_sources = json.loads(json.dumps(kit['source_references']))
            repaired_sources[2]['claims'][0]['text'] = 'Adjustable shelf for storage'
            repaired_sources[2]['input_revision_id'] = 'local-correction'
            updated_prompt = visual_design_kit_prompt(_Plugin(), compact_product_facts(_child()), tasks[0]['category_image_policy'], repaired_sources, product_claims=kit['product_claims'])
            repair_args = dict(child_facts_revision=kit['child_facts_revision_id'], prompt=updated_prompt,
                plugin=_Plugin(), facts=compact_product_facts(_child()), policy=tasks[0]['category_image_policy'], design_refs=[])
            self.assertTrue(_local_evidence_repair(job, kit, repaired_sources, **repair_args))
            local_raw = {'family_art_direction': kit['family_art_direction'], 'image_briefs': [_brief_draft(row) for row in kit['image_briefs']]}
            with patch('core.visual_design_kit.gemini_stream_generate') as whole_planner:
                local = _finish_image_briefs(local_raw, job=job, child=kit['child'], product_claims=kit['product_claims'], source_manifest=repaired_sources, category_id=_Plugin.category_id,
                    source_paths=[], source_originals=[], trace_dir=job / 'local_review', deadline_monotonic=time.monotonic()+10, cached=kit)
                whole_planner.assert_not_called()
            local_kit = {**kit, **local, 'source_references': repaired_sources}
            changed_intents = json.loads(json.dumps(intents))
            next(row for row in changed_intents if row['role'] == 'func')['input_revision_id'] = 'local-correction'
            for spec in task_specs(_child(), changed_intents):
                current = _form_task(job=job, plugin=_Plugin(), child=_child(), spec=spec, design_kit=local_kit,
                    image_policy=tasks[0]['category_image_policy'], product_type='BATHROOM_CABINET')
                previous = next(row for row in tasks if row['role'] == spec['role'])
                self.assertEqual('ready', current['formation_status'], current['formation_reason'])
                self.assertEqual(previous['task_fingerprint'], current['task_fingerprint'])
            repaired_sources[2]['observation']['physical_views'][0]['extent'] = 'detail'
            self.assertFalse(_local_evidence_repair(job, kit, repaired_sources, **repair_args))
            before = kit['source_references'][2]
            observation_revisions = {before['source_id']: {'source_revision': before['input_revision_id'],
                'source_sha256': before['source_sha256'], 'findings': [{'operation': 'source_product:' + before['source_id'] + '/view_01'}]}}
            self.assertTrue(_local_evidence_repair(job, kit, repaired_sources, **repair_args, observation_revisions=observation_revisions))
            observation_revisions[before['source_id']]['source_revision'] = 'unrelated-evidence'
            self.assertFalse(_local_evidence_repair(job, kit, repaired_sources, **repair_args, observation_revisions=observation_revisions))
            self.assertFalse(_local_evidence_repair(job, kit, kit['source_references'], **{**repair_args, 'child_facts_revision': 'changed-color'}))

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
            self.assertIn("source_02/view_01: display", func_prompt)
            self.assertIn("Visible frame support and its joints", func_prompt)
            self.assertIn('redesign source panels, titles, icons and highlights', func_prompt)
            self.assertEqual(1, func_prompt.count('Product evidence ('))
            self.assertIn("Adjustable Shelf", func_prompt)
            self.assertIn("Different Object Heights", func_prompt)
            self.assertIn("Wall-Mounted Organization", func_prompt)
            self.assertIn('necessary functional evidence and qualifiers', func_prompt)
            self.assertIn('Preserve: Sold-product geometry', func_prompt)
            self.assertIn("text_color = #303634", func_prompt)
            self.assertIn("font_family = Inter", func_prompt)
            self.assertNotIn("Derive the new palette from sold-product body color", func_prompt)
            self.assertNotIn("Rebuild all non-sold props, background, graphic layout", func_prompt)
            self.assertIn('remove people and reflected people', func_prompt)
            self.assertNotIn("Edit the role source in place", func_prompt)
            self.assertIn("bath.towels = #8A999E", func_prompt)
            self.assertIn('Apply these core appearances where depicted', func_prompt)
            self.assertNotIn("when it improves hierarchy", func_prompt)
            self.assertIn("readable spacing", func_prompt)
            self.assertNotIn("Cohesion Rule:", func_prompt)
            size_prompt = next(row["prompt"] for row in prompts if row["role"] == "size")
            self.assertIn("with readable spacing", size_prompt)
            self.assertIn("do not duplicate a label on one association", size_prompt)
            self.assertEqual(1, size_prompt.count('Cabinet / width: 24 in'))
            self.assertNotIn('intact diagram as a unit', size_prompt)
            self.assertIn("font_family = Inter", size_prompt)
            self.assertNotIn("when it improves hierarchy", size_prompt)
            self.assertNotIn("Audience And Market:", size_prompt)
            self.assertNotIn("Environment And Staging:", size_prompt)
            main_prompt = next(row["prompt"] for row in prompts if row["role"] == "main")
            self.assertIn("uniform pure-white canvas", main_prompt)
            self.assertNotIn("Market context:", main_prompt)
            self.assertNotIn("Use the room tokens", main_prompt)
            self.assertNotIn("Non-product objects:", main_prompt)

    def test_product_observation_precedes_gap_scoped_ocr(self) -> None:
        from core.visual_semantics import _validate_observations, observe_child_sources
        from core.final_source_intents import _non_size_role, _signals
        observed = _fixture_observation(None, _child(), [{'source_id': 'source_00'}])['source_00']
        observed['objects'][0].update(sale_membership='unknown', membership_evidence=[])
        self.assertEqual('unknown', _validate_observations([observed], ['source_00'], {})['source_00']['objects'][0]['sale_membership'])
        for role in ('scene', 'func', 'size', 'unknown'):
            detail = {**observed, 'role_guess': role, 'has_callouts_or_panels': False, 'text_observations': []}
            checked = _validate_observations([detail], ['source_00'], {})['source_00']
            self.assertEqual('success', checked['status'])
            signals = _signals(1, dict(visual_evidence=checked, claims=[], trusted_text=[]), [])
            self.assertEqual(role if role in {'scene', 'func'} else 'review_required', _non_size_role(dict(visual_evidence=checked, signals=signals)))
        for has_fact, measurements in ((False, []), (False, [{'text': '12 in'}]),
                                       (True, []), (True, [{'text': '12 in'}])):
            prepared = dict(visual_evidence={**observed, 'role_guess': 'size'},
                            signals={**signals, 'has_authored_function_text': has_fact}, measurements=measurements)
            self.assertEqual('func' if has_fact and measurements else 'review_required', _non_size_role(prepared))
        with tempfile.TemporaryDirectory() as tmp, patch('core.visual_semantics.gemini_stream_generate',
                return_value=json.dumps({'sources': [observed]})) as request:
            sources = [{'source_id': 'source_00', 'sha256': 'a' * 64, 'ocr': [], 'path': Path(tmp) / 'source.png'}]
            self.assertEqual(observe_child_sources(Path(tmp), {'asin': 'B1'}, sources),
                             observe_child_sources(Path(tmp), {'asin': 'B1'}, sources))
            self.assertEqual(1, request.call_count)
        partial = _validate_observations([observed], ['source_00', 'source_01'], {})
        self.assertEqual('success', partial['source_00']['status'])
        self.assertEqual('failed', partial['source_01']['status'])
        observed['objects'][0]['sale_membership'] = 'included_accessory'
        self.assertIn('requires product evidence', _validate_observations([observed], ['source_00'], {})['source_00']['error'])
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / 'reports').mkdir(parents=True)
            rows, _ = self._source_fixture(job)
            rows = rows[:2]
            failed = _fixture_observation(job, _child(), [{'source_id': f'source_{i:02d}'} for i in range(2)])
            failed['source_01'] = {'status': 'failed', 'error': 'visual provider unavailable'}
            with (
                patch('core.final_source_intents.ensure_run_scope'),
                patch('core.final_source_intents.download_artifacts_current', return_value=(True, [])),
                patch('core.final_source_intents.read_download_manifest', return_value={'rows': rows}),
                patch('core.final_source_intents.read_product_family', return_value=_family()),
                patch('core.final_source_intents.row_in_scope', return_value=True),
                patch('core.final_source_intents.ocr_evidence_for_image') as ocr,
            ):
                with patch('core.final_source_intents.observe_child_sources', return_value=failed):
                    build_final_source_intents(job_dir=job, plugin=_Plugin())
                unresolved = read_final_source_intents(job, plugin=_Plugin())[1]
                self.assertEqual('review_required', unresolved['role'])
                self.assertEqual([], unresolved['claims'])
                self.assertIn('source_observation_unresolved', unresolved['classification_reason'])
                ocr.assert_not_called()
                calls = []

                def observe_gap(job, child, sources, **kwargs):
                    calls.append([(row['source_id'], row['ocr']) for row in sources])
                    result = _fixture_observation(job, child, sources)
                    for source in sources:
                        if source['source_id'] != 'source_01':
                            continue
                        row = result['source_01']
                        row.update(role_guess='func', has_callouts_or_panels=True)
                        row['text_gaps'] = [] if source['ocr'] else ['Read the shelf annotation']
                        row['text_observations'] = [{'text': 'Adjustable Shelf', 'kind': 'product_fact'}] if source['ocr'] else []
                    return result

                ocr.return_value = {'available': True, 'lines': [
                    {'text': 'Adjustable Shelf', 'confidence': .95},
                    {'text': 'Multi-scene Application', 'confidence': .95}]}
                with patch('core.final_source_intents.observe_child_sources', side_effect=observe_gap):
                    build_final_source_intents(job_dir=job, plugin=_Plugin())
                classified = read_final_source_intents(job, plugin=_Plugin())
                self.assertEqual(['main', 'func'], [row['role'] for row in classified])
                self.assertEqual('success', classified[0]['visual_evidence']['status'])
                self.assertFalse(classified[0]['signals']['ocr_available'])
                self.assertEqual(['Adjustable Shelf'], [row['text'] for row in classified[1]['claims']])
                self.assertEqual([('source_00', []), ('source_01', [])], calls[0])
                self.assertEqual([('source_01', ['Adjustable Shelf', 'Multi-scene Application'])], calls[1])
                ocr.assert_called_once()
                self.assertEqual(job / rows[1]['raw_path'], ocr.call_args.args[0])

                def fail_supplement(job, child, sources, **kwargs):
                    if any(row['ocr'] for row in sources):
                        raise RuntimeError('fixture supplement failure')
                    return observe_gap(job, child, sources, **kwargs)

                ocr.reset_mock()
                with patch('core.final_source_intents.observe_child_sources', side_effect=fail_supplement):
                    build_final_source_intents(job_dir=job, plugin=_Plugin())
                retained = read_final_source_intents(job, plugin=_Plugin())
                ocr.assert_called_once()
                self.assertEqual('main', retained[0]['role'])
                self.assertEqual(classified[0]['visual_evidence'], retained[0]['visual_evidence'])
                self.assertEqual('success', retained[1]['visual_evidence']['status'])
                self.assertEqual(['Read the shelf annotation'], retained[1]['visual_evidence']['text_gaps'])
                self.assertEqual([], retained[1]['claims'])
                self.assertEqual('RuntimeError: fixture supplement failure', retained[1]['ocr_evidence']['supplement_error'])

    def test_measurements_merge_equivalent_units_and_reject_zero_weight(self) -> None:
        from core.final_source_intents import _observed_measurements, _measurement_rows
        from core.image_tasks import _measurement_authority
        from core.visual_semantics import OBSERVATION_POLICY
        from tests.current_image_contract_fixture import current_observed_measurement
        located = [current_observed_measurement(text, obj, axis, key=str(i), kind=kind) for i, (text, obj, axis, kind) in enumerate([
            ('3 ft', 'Overall', 'height', 'dimension'), ('36 in', 'Drawer', 'height', 'dimension'),
            ('440 lbs', 'Bed', 'capacity', 'capacity')])]
        visual = {'status': 'success', 'policy_version': OBSERVATION_POLICY, 'measurements': located}
        observed = _observed_measurements(visual)
        source = {"source_id": "source_00", "role": "size", "measurements": _measurement_rows(observed, {})}
        authority = _measurement_authority("size", source, [(source, current_physical_view())])
        self.assertEqual(['height', 'height', 'capacity'], [r['axis'] for r in authority['measurement_groups']])
        content = _measurement_content(authority, [{'kind': 'measurement_evidence', 'source_id': 'source_00', 'view_id': 'view_01',
            'original_region': dict(left=.1, top=.2, right=.9, bottom=.8)}])
        self.assertEqual(1, content.count('Overall / height'))
        self.assertEqual(1, content.count('Drawer / height'))
        self.assertIn('"endpoints":null', content)
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
        from core.palette_registry import _ciede2000, _delta_e, _srgb_lab
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
        with patch.dict(sys.modules, {"colour": None}):
            self.assertEqual(0, _delta_e((.5, .5, .5), (.5, .5, .5))[0])
        sources = [{
            "source_id": "source_00",
            "source_index": 0,
            "role": "main",
            "source_path": "main.png",
            "source_sha256": "m",
            "input_revision_id": "mr",
            "shopping_intent": "",
            "claims": [],
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
            "measurements": [],
        }]
        for source in sources:
            source["observation"] = _evidence('scene')['visual_evidence']
        draft = {
            "family_art_direction": current_art_direction(),
            "image_briefs": [{
                "role": "scene",
                "source_id": "source_01",
                "image_direction": current_image_direction(source_id='source_01'),
            }],
            "product_visual_read": {
                "sold_product_parts": ["invented mirror"],
            },
        }
        from tests.current_image_contract_fixture import supported_design_reviews
        compiled = compile_visual_design_kit_response(
            draft,
            source_manifest=sources,
            claim_reviews=supported_design_reviews(draft, sources),
        )
        self.assertEqual(
            {"family_art_direction", "image_briefs"},
            set(compiled),
        )
        self.assertEqual(
            current_image_direction(source_id='source_01'),
            compiled["image_briefs"][1]["image_direction"],
        )
        self.assertEqual(['main', 'scene', 'func', 'size'], [row['role'] for row in compiled['image_briefs']])
        self.assertEqual('ready', compiled['image_briefs'][1]['status'])
        self.assertEqual({}, compile_visual_design_kit_response(draft, source_manifest=sources)['image_briefs'][1]['design_review'])
        open_feel = json.loads(json.dumps(draft))
        open_feel["family_art_direction"]["typography_direction"]["body_style"] = (
            "Use a geometric sans-serif with generous spacing to preserve the open feel of the room."
        )
        compiled_open_feel = compile_visual_design_kit_response(open_feel, source_manifest=sources)
        self.assertEqual(
            "Use a geometric sans-serif with generous spacing to preserve the open feel of the room.",
            compiled_open_feel["family_art_direction"]["typography_direction"]["body_style"],
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
        self.assertIn('two open doors', compile_visual_design_kit_response(state_decision,
            source_manifest=sources)['family_art_direction']['environment_and_staging'])
        overlong = json.loads(json.dumps(draft))
        overlong["family_art_direction"]["audience_and_market"] = "x" * 2201
        with self.assertRaisesRegex(VisualDesignKitCompileError, "exceeds 2200"):
            compile_visual_design_kit_response(overlong, source_manifest=sources)
        for field, instruction in (
            ("source_brief", "Title: Spacious Everyday Storage"),
            ("audience_and_market", "Set the headline to Modern Loft Bed in charcoal ink."),
            ("environment_and_staging", "The visible label reads Premium Storage"),
        ):
            polluted = json.loads(json.dumps(draft))
            if field == "source_brief":
                polluted["image_briefs"][0]["image_direction"]["visual_goal"] = instruction
            else:
                polluted["family_art_direction"][field] = instruction
            if field == "source_brief":
                failed = compile_visual_design_kit_response(polluted, source_manifest=sources)
                self.assertEqual("pending", failed["image_briefs"][1]["status"])
                self.assertIn("renderable-copy instruction", failed["image_briefs"][1]["error"])
            else:
                with self.assertRaisesRegex(VisualDesignKitCompileError, "renderable-copy instruction"):
                    compile_visual_design_kit_response(polluted, source_manifest=sources)
        artificial_scene = json.loads(json.dumps(draft))
        artificial_scene["image_briefs"][0]["image_direction"]["visual_goal"] = (
            "Restyle the front door, wall siding, floor, and doormat while keeping the tree and pot unchanged."
        )
        compiled_tree = compile_visual_design_kit_response(
            artificial_scene, source_manifest=sources, category_id="artificial_tree",
            claim_reviews=supported_design_reviews(artificial_scene, sources),
        )
        self.assertIn("front door", compiled_tree["image_briefs"][1]["image_direction"]["visual_goal"])
        sold_change = json.loads(json.dumps(artificial_scene))
        sold_change["image_briefs"][0]["image_direction"]["visual_goal"] = "Replace the tree and pot with a new container."
        from core.visual_design_kit_compiler import design_binding_request
        request = design_binding_request(sold_change['image_briefs'][0], sold_change['family_art_direction'],
            source=next(row for row in sources if row['source_id'] == sold_change['image_briefs'][0]['source_id']), source_manifest=sources)
        from core.visual_semantics import CLAIM_REVIEW_POLICY
        reviews = {request['key']: {'key': request['key'], 'policy': CLAIM_REVIEW_POLICY, 'status': 'supported',
            'response_sha256': 'a' * 64, 'findings': [{'operation': 'source_product:source_01/view_01',
            'status': 'contradiction', 'reason': 'Replacing the sold tree and pot changes product identity'}]}}
        failed = compile_visual_design_kit_response(sold_change, source_manifest=sources, category_id="artificial_tree", claim_reviews=reviews)
        self.assertEqual("pending", failed["image_briefs"][1]["status"])
        self.assertIn('changes product identity', failed['image_briefs'][1]['error'])

    def test_display_copy_contract_is_single_evidence_bound_authority(self) -> None:
        from core.visual_design_kit_compiler import _bind_display_text, claim_review_requests
        from core.visual_semantics import claim_key, CLAIM_REVIEW_POLICY
        for evidence, proposed in (("Natural pine wood", "Waterproof Finish"), ("2 doors", "2 drawers")):
            with self.assertRaisesRegex(VisualDesignKitCompileError, "independent evidence review"):
                _bind_display_text({"evidence_ids": ["e1"], "text": proposed}, {"e1": evidence})
        source = {"source_id": "source_01", "source_index": 1, "role": "func",
                  "observation": _evidence('func')['visual_evidence'],
                  "source_sha256": "f", "input_revision_id": "fr", "source_path": "func.png",
                  "shopping_intent": "show shelf", "measurements": [],
                  "claims": [{"evidence_id": "e1", "text": "Adjustable Shelf", "source_sha256": "f",
                              "type": "visible_function_text", "confidence": "source_visible"}]}
        draft = {"family_art_direction": current_art_direction(), "image_briefs": [{
            "role": "func",
            "source_id": "source_01",
            "image_direction": current_image_direction(source_id='source_01'),
            "display_copy": {"title": {"evidence_ids": ["e1"], "text": "Adjust Shelf Height"}, "labels": []},
        }]}
        from tests.current_image_contract_fixture import supported_design_reviews
        pending = compile_visual_design_kit_response(draft, source_manifest=[source], claim_reviews=supported_design_reviews(draft, [source]))
        self.assertEqual("pending", pending["image_briefs"][2]["status"])
        self.assertIn('independent evidence review', pending['image_briefs'][2]['error'])
        key = claim_key("Adjust Shelf Height", {"e1": "Adjustable Shelf"})
        review = {key: {"key": key, "policy": CLAIM_REVIEW_POLICY, "status": "supported",
                        "reason": "The shelf height is adjustable.", "response_sha256": "a" * 64}}
        review.update(supported_design_reviews(draft, [source]))
        compiled = compile_visual_design_kit_response(draft, source_manifest=[source], claim_reviews=review)
        brief = compiled["image_briefs"][2]
        self.assertEqual('func', brief['role'])
        self.assertEqual("ready", brief["status"])
        self.assertEqual(draft["image_briefs"][0]["image_direction"], brief["image_direction"])
        self.assertEqual("Adjust Shelf Height", build_display_copy_contract([source], brief)["title"])
        self.assertEqual(1, len(claim_review_requests(draft, [source])))
        draft["image_briefs"][0]["display_copy"]["title"]["text"] = "Waterproof Finish"
        stale = compile_visual_design_kit_response(draft, source_manifest=[source], claim_reviews=review)
        self.assertEqual("pending", stale["image_briefs"][2]["status"])
        draft["image_briefs"][0]["display_copy"]["title"] = {}
        empty = compile_visual_design_kit_response(draft, source_manifest=[source], claim_reviews=review)
        self.assertEqual("pending", empty["image_briefs"][2]["status"])
        self.assertNotIn("display_copy_contract", empty["image_briefs"][2])
        draft["image_briefs"][0]["display_copy"] = {"title": None, "labels": []}
        no_copy = compile_visual_design_kit_response(draft, source_manifest=[source],
            claim_reviews=supported_design_reviews(draft, [source]))["image_briefs"][2]
        self.assertEqual("ready", no_copy["status"])
        self.assertEqual([], build_display_copy_contract([source], no_copy)["bindings"])
        from core.image_task_inputs import task_facts, authored_text_contract
        self.assertEqual([], authored_text_contract(no_copy["display_copy_contract"])["strings"])
        child = {"sold_unit_count": 1, "sold_unit_count_source": "amazon_single_unit_listing_policy"}
        self.assertIsNone(task_facts(child, product_type="BED_FRAME")["sold_unit_count"])
        child.update(sold_unit_count=2, sold_unit_count_source="apify_explicit_pack_count")
        self.assertEqual(2, task_facts(child, product_type="BED_FRAME")["sold_unit_count"])


if __name__ == "__main__":
    unittest.main()
