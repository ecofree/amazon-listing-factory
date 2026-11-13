from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import image_qa
from core.candidate_state import CandidateStateError
from core.image_tasks import IMAGE_TASK_POLICY_VERSION
from tests.current_image_contract_fixture import current_image_task, current_prompt_artifact, current_image_direction


def _task(role: str, mode: str = 'none') -> dict:
    family = role.split('_', 1)[0]
    return {
        'child': 'B1', 'role': role, 'role_family': family,
        'policy_version': IMAGE_TASK_POLICY_VERSION, 'task_fingerprint': 'task',
        'category_image_policy': {'main_image_policy': 'white_background'},
        'measurement_authority': {'mode': mode, 'render_text': []},
        'renderable_text_contract': {'mode': 'exact' if family in {'func', 'size'} else 'none',
                                   'strings': ['Adjustable Shelf'] if family == 'func' else []},
        'source_path': 'source.png', 'source_sha256': 's' * 64,
        'generation_references': [{'source_id': 'source_00'}],
        'image_direction': current_image_direction(),
    }


def _checks(required, status='pass'):
    return [dict(check=name, status=status, candidate_observation='One same-color cabinet with matching visible structure; text Adjustable Shelf',
                 reference_observation='source_00 shows the same structure and the contract authorizes Adjustable Shelf',
                 source_ids=['source_00'], reason='The visible product and exact approved text agree with the bound reference') for name in required]


class QaLiteV1Tests(unittest.TestCase):
    def test_factual_qa_and_resume_reuse_bound_response(self):
        from tests.continuity_contract_fixture import verify_qa_semantics, verify_qa_service_recovery
        verify_qa_semantics(self); verify_qa_service_recovery(self)
        from core.io import file_sha256
        task = current_image_task('func_01')
        plugin = type('Plugin', (), {'category_id': 'bathroom_cabinet'})()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'candidate.png').write_bytes(b'bound fixture candidate')
            (root / 'source.png').write_bytes(b'bound source')
            task['generation_references'] = [dict(source_id='source_00', child='B1', kind='edit_base', path='source.png',
                sha256=file_sha256(root / 'source.png'), purpose='Product evidence')]
            prompts = current_prompt_artifact(tmp, task)
            candidate = {'candidate_path': 'candidate.png', 'candidate_sha256': file_sha256(root / 'candidate.png'),
                         'provider_name':'fixture-provider','task_prompt_fingerprint': 'original-saved-prompt'}
            candidate['reuse_evidence'] = dict(original_task_fingerprint='original-task',
                current_task_fingerprint=task['task_fingerprint'],
                current_prompt_sha256=prompts['prompts'][0]['prompt_sha256'],
                candidate_sha256=candidate['candidate_sha256'],basis='same_edit_instructions_and_attachment_bytes')
            with (patch.object(image_qa, 'load_job', return_value={}),
                  patch.object(image_qa, 'require_current_image_branch'),
                  patch.object(image_qa, 'scoped_child_set', return_value={'B1'}),
                  patch.object(image_qa, 'read_image_prompts', return_value=prompts),
                  patch.object(image_qa, 'read_image_tasks', return_value={'tasks': [task]}),
                  patch.object(image_qa, 'current_candidate', return_value=candidate),
                  patch.object(image_qa, '_local_gates', return_value=[dict(gate='image_integrity', status='pass', evidence='Decodable fixture')]) as local,
                  patch('core.vision_gemini_client.gemini_stream_generate', return_value=json.dumps({'checks': _checks(['product_fidelity', 'unauthorized_text'])})) as model):
                first = image_qa.run_image_qa(job_dir=root, plugin=plugin)
                resumed = image_qa.run_image_qa(job_dir=root, plugin=plugin)
                candidate['provider_name']='copy'
                diagnostic=image_qa.run_image_qa(job_dir=root,plugin=plugin)
                self.assertEqual([],diagnostic['qa'])
                self.assertEqual('generation',diagnostic['failures'][0]['failure_owner'])
                candidate['provider_name']='fixture-provider'
                for field in ('current_task_fingerprint','current_prompt_sha256','candidate_sha256','basis'):
                    with self.subTest(stale_reuse=field):
                        original=candidate['reuse_evidence'][field]
                        candidate['reuse_evidence'][field]='foreign'
                        rejected=image_qa.run_image_qa(job_dir=root,plugin=plugin)
                        candidate['reuse_evidence'][field]=original
                        self.assertEqual([],rejected['qa'])
                        self.assertEqual('generation',rejected['failures'][0]['failure_owner'])
            self.assertEqual(1, model.call_count)
            self.assertEqual(1, local.call_count)
            self.assertEqual([], first['failures'])
            self.assertEqual(first['qa'], resumed['qa'])
            self.assertEqual('success', resumed['tasks'][0]['status'])
            self.assertEqual('pass', resumed['qa'][0]['automatic_decision'])
            from types import SimpleNamespace
            from core.release_manifest import build_release_manifest
            with (patch('core.release_manifest._product_family', return_value={'family': {'parent_asin': 'B1', 'children': [{'asin': 'B1'}]}}),
                  patch('core.release_manifest.scoped_family_children', return_value=[{'asin': 'B1'}]),
                  patch('core.release_manifest.required_role_policy', return_value=SimpleNamespace(counts={'func': 1}, policy_id='policy')),
                  patch('core.release_manifest.image_branch_currentness', return_value=(True, '')),
                  patch('core.release_manifest.read_image_prompts', return_value=prompts),
                  patch('core.release_manifest.read_image_tasks', return_value={'tasks': [task]}),
                  patch('core.release_manifest.validate_task_inventory'),
                  patch('core.release_manifest._review_rows', return_value={}) as reviews,
                  patch('core.release_manifest.current_candidate', return_value=candidate),
                  patch('core.release_manifest.task_record_current', return_value={}),
                  patch('core.release_manifest.production_reference_error', return_value=''),
                  patch('core.release_manifest.source_inventory_coverage', return_value={'status': 'success', 'rows': []}),
                  patch('core.vision_gemini_client.gemini_stream_generate', side_effect=AssertionError('Release must not call a model'))):
                release = build_release_manifest(job_dir=root, plugin=plugin)
                candidate['provider_name']='mock'
                simulation=build_release_manifest(job_dir=root,plugin=plugin)
                self.assertEqual('blocked_reference',simulation['rows'][0]['final_decision'])
                candidate['provider_name']='fixture-provider'
                evidence=first['qa'][0]
                reviews.return_value={(task['child'],task['role'],candidate['candidate_sha256']):dict(
                    child=task['child'],role=task['role'],decision='reject',candidate_sha256=candidate['candidate_sha256'],
                    release_candidate_fingerprint=evidence['release_candidate_fingerprint'],
                    qa_policy_id=evidence['qa_policy_id'],qa_evidence_fingerprint=evidence['evidence_fingerprint'])}
                rejected=build_release_manifest(job_dir=root,plugin=plugin)
                self.assertEqual('rejected_human',rejected['rows'][0]['final_decision'])
                from core.qa_evidence import evidence_fingerprint, write_qa_evidence
                from copy import deepcopy
                wrong=deepcopy(evidence);wrong['automatic_decision']='fail';wrong['automatic_pass']=False
                next(g for g in wrong['gates'] if g['gate']=='unauthorized_text')['status']='fail'
                wrong['evidence_fingerprint']=evidence_fingerprint(wrong);write_qa_evidence(root,[wrong])
                approval={**next(iter(reviews.return_value.values())),'decision':'approve',
                    'qa_evidence_fingerprint':wrong['evidence_fingerprint'],'resolutions':[]}
                reviews.return_value={(task['child'],task['role'],candidate['candidate_sha256']):approval}
                self.assertEqual('blocked_auto',build_release_manifest(job_dir=root,plugin=plugin)['rows'][0]['final_decision'])
                approval['resolutions']=[{'check':'unauthorized_text','candidate_sha256':candidate['candidate_sha256'],
                    'source_sha256':task['source_sha256'],'conclusion':'confirmed','evidence':'Source banner is absent from candidate pixels.'}]
                self.assertEqual('approved',build_release_manifest(job_dir=root,plugin=plugin)['rows'][0]['final_decision'])

            self.assertEqual('approved', release['rows'][0]['final_decision'])

    def test_missing_and_invalid_candidates_stay_with_generation_owner(self):
        task = current_image_task('func_01')
        plugin = type('Plugin', (), {'category_id': 'bathroom_cabinet'})()
        with tempfile.TemporaryDirectory() as tmp:
            prompts = current_prompt_artifact(tmp, task)
            with (patch.object(image_qa, 'load_job', return_value={}), patch.object(image_qa, 'require_current_image_branch'),
                  patch.object(image_qa, 'scoped_child_set', return_value={'B1'}),
                  patch.object(image_qa, 'read_image_prompts', return_value=prompts),
                  patch.object(image_qa, 'read_image_tasks', return_value={'tasks': [task]}),
                  patch.object(image_qa, 'current_candidate', return_value={}) as current):
                self.assertEqual([], image_qa.run_image_qa(job_dir=tmp, plugin=plugin)['failures'])
                current.side_effect = CandidateStateError('manifest bytes changed')
                result = image_qa.run_image_qa(job_dir=tmp, plugin=plugin)
                self.assertEqual([], result['qa'])
                self.assertEqual('generation', result['failures'][0]['failure_owner'])
                self.assertEqual('blocked', result['tasks'][0]['status'])
            from core.io import file_sha256
            from core.qa_evidence import qa_receipt_root
            root=Path(tmp); (root/'source.png').write_bytes(b'source'); (root/'candidate.png').write_bytes(b'candidate')
            task['generation_references']=[dict(kind='edit_base',child='B1',source_id='source_00',purpose='Product truth',
                path='source.png',sha256=file_sha256(root/'source.png'))]
            candidate=dict(candidate_path='candidate.png',candidate_sha256=file_sha256(root/'candidate.png'))
            with patch('core.vision_gemini_client.gemini_stream_generate', return_value='{"checks":[]}') as remote:
                for _ in range(2):
                    gates,_=image_qa._factual_gates(root,task,candidate)
                    self.assertTrue(all(g['status']=='inconclusive' for g in gates))
                self.assertEqual(1,remote.call_count,'Malformed known replies are retained without another POST')
            (root/'candidate.png').write_bytes(b'new candidate')
            candidate['candidate_sha256']=file_sha256(root/'candidate.png')
            with patch('core.vision_gemini_client.gemini_stream_generate', side_effect=TimeoutError('Reply lost after send')) as remote:
                for _ in range(2):
                    gates,_=image_qa._factual_gates(root,task,candidate)
                    self.assertTrue(all(g['status']=='inconclusive' for g in gates))
                self.assertEqual(1,remote.call_count,'Unknown replies are never silently resubmitted')
            required=['product_fidelity','unauthorized_text']
            for invalid in ([],_checks(required)*2,_checks(required)+_checks(['extra'])):
                with self.assertRaises(ValueError): image_qa._parse_factual_gates(json.dumps({'checks':invalid}),required,{'source_00'})
            foreign=_checks(required);foreign[0]['source_ids']=['other_child']
            with self.assertRaises(ValueError): image_qa._parse_factual_gates(json.dumps({'checks':foreign}),required,{'source_00'})
            failed=image_qa._parse_factual_gates(json.dumps({'checks':_checks(required,'fail')}),required,{'source_00'})
            self.assertEqual(['fail','inconclusive'], [g['status'] for g in failed])
            from tests.four_stage_fixture import verify_qa_attribution
            verify_qa_attribution(self)


    def test_unknown_visual_facts_require_bound_human_resolution(self):
        from core.qa_evidence import evidence_is_current, _validate_row, evidence_fingerprint, QaEvidenceError
        from core.release_manifest import _validate_resolutions, _review_is_current, ReleaseManifestError
        task, candidate = _task('func'), dict(candidate_path='candidate.png', candidate_sha256='c' * 64)
        with (patch.object(image_qa, '_local_gates', side_effect=lambda *_: [dict(gate='image_integrity', status='pass', evidence='Decoded')]),
              patch.object(image_qa, '_factual_gates', side_effect=lambda job,t,c,**kw: (
                  [dict(gate=g,status='inconclusive',evidence='Pixels are unclear at the measured connection') for g in image_qa._factual_checks(t,c)], {}))):
            evidence = image_qa._evaluate(Path('.'), object(), task, candidate)
            scoped = image_qa._evaluate(Path('.'), object(), _task('size', 'source_image'), {**candidate, 'revision_mode': 'targeted_edit'})
        self.assertEqual('inconclusive', evidence['automatic_decision'])
        self.assertFalse(evidence['automatic_pass'])
        self.assertEqual({'product_fidelity', 'unauthorized_text'}, {g['gate'] for g in evidence['gates'] if g['status'] == 'inconclusive'})
        self.assertEqual({'product_fidelity', 'unauthorized_text', 'dimension_accuracy', 'edit_scope'}, {g['gate'] for g in scoped['gates'] if g['status'] == 'inconclusive'})
        self.assertTrue(evidence_is_current(evidence, task, candidate))
        with patch('core.vision_gemini_client.gemini_scope_execution_revision', return_value='changed-connection'):
            self.assertTrue(evidence_is_current(evidence, task, candidate))
        with patch('core.qa_evidence.QA_POLICY_VERSION', 'changed-hard-factual-rules'):
            self.assertFalse(evidence_is_current(evidence, task, candidate))
        invalid = {**evidence, 'automatic_decision': 'pass'}
        invalid['evidence_fingerprint'] = evidence_fingerprint(invalid)
        with self.assertRaisesRegex(QaEvidenceError, 'contradicts'):
            _validate_row(invalid)
        target = {'candidate_sha256': candidate['candidate_sha256'], 'source_sha256': task['source_sha256'],
                  'unresolved_checks': [g['gate'] for g in evidence['gates'] if g['status'] == 'inconclusive']}
        with self.assertRaises(ReleaseManifestError):
            _validate_resolutions([], target)
        resolutions = [{**{k: target[k] for k in ('candidate_sha256', 'source_sha256')}, 'check': check,
                        'conclusion': 'confirmed', 'evidence': 'Compared source and candidate; exact product and approved text confirmed.'}
                       for check in target['unresolved_checks']]
        _validate_resolutions(resolutions, target)
        from core.image_task_inputs import release_candidate_fingerprint
        review = dict(decision='approve', resolutions=resolutions, candidate_sha256=candidate['candidate_sha256'],
                      release_candidate_fingerprint=release_candidate_fingerprint(task, candidate),
                      qa_policy_id=evidence['qa_policy_id'], qa_evidence_fingerprint=evidence['evidence_fingerprint'])
        self.assertTrue(_review_is_current(review, task=task, candidate=candidate, evidence=evidence))
        self.assertFalse(_review_is_current(review, task=task, candidate={**candidate, 'candidate_sha256': 'd' * 64}, evidence=evidence))
        from contextlib import nullcontext
        from core.release_manifest import record_human_reviews
        with (patch('core.release_manifest.job_run_lock', return_value=nullcontext()),
              patch('core.release_manifest.build_release_manifest', return_value={'rows': [{'child': 'B1', 'role': 'func', 'automatic_decision': 'fail'}]})):
            with self.assertRaisesRegex(ReleaseManifestError, 'factual failure'):
                record_human_reviews(job_dir='unused', plugin=object(), targets=[('B1', 'func')], decision='approve', resolutions=resolutions)

    def test_background_edge_signal_does_not_prove_product_or_canvas(self):
        from tests.image_boundary_fixture import verify_background
        verify_background(self)
        from tests.audit_planning_fixture import verify_main_quantity
        verify_main_quantity(self)


if __name__ == '__main__':
    unittest.main()
