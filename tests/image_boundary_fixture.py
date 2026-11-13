"""Image boundary contracts merged into the existing production cases."""
from io import BytesIO
from functools import lru_cache
import base64
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
from PIL import Image, ImageDraw


@lru_cache(maxsize=8)
def native_bytes(size=(1024, 1024)):
    image = Image.new('RGB', size, 'white')
    ImageDraw.Draw(image).rectangle((size[0]//4, size[1]//4, size[0]*3//4, size[1]*3//4), fill='#808080')
    out = BytesIO(); image.save(out, format='PNG')
    return out.getvalue()


def verify_native_and_transport(test):
    from core import image_provider_transport as transport
    from core.imagegen_artifacts import assert_native_image, assert_image_output, normalize_native_image
    from core.image_provider_common import CandidateCommitError, ImageOutputRejected
    good = native_bytes()
    test.assertEqual([1024, 1024], assert_native_image(good)['size'])
    for data in (native_bytes((2, 2)), native_bytes((1024, 1000))):
        with test.assertRaises(CandidateCommitError):
            assert_native_image(data)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'solid.png'
        for color in ('#808080', '#ff0000', '#ffffff', '#000000'):
            Image.new('RGB', (1600, 1600), color).save(path)
            with test.assertRaises(Exception):
                assert_image_output(path)
            with test.assertRaises(CandidateCommitError):
                assert_native_image(path.read_bytes())
        Image.new('RGBA', (1024, 1024), (0, 0, 0, 0)).save(path)
        with test.assertRaises(CandidateCommitError):
            assert_native_image(path.read_bytes())
        for mode, white, black, transparency in [('RGB', 'white', 'black', (0, 0, 0)), ('L', 255, 0, 0), ('P', 255, 0, 0)]:
            image = Image.new(mode, (1024, 1024), white)
            if mode == 'P': image.putpalette([v for i in range(256) for v in (i, i, i)])
            ImageDraw.Draw(image).rectangle((256, 256, 768, 768), fill=black)
            image.save(path, format='PNG', transparency=transparency)
            data = path.read_bytes()
            with test.assertRaises(ImageOutputRejected): assert_native_image(data)
            with Image.open(BytesIO(normalize_native_image(data))) as visible:
                test.assertEqual('RGB', visible.mode)
                test.assertNotIn('transparency', visible.info)
                test.assertEqual((255, 255, 255), visible.getpixel((512, 512)))
            with test.assertRaises(Exception): assert_image_output(path)
        image = Image.new('RGB', (1024, 1024), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((256, 256, 768, 768), fill='black')
        draw.rectangle((10, 10, 30, 30), fill='#808080')
        image.save(path, format='PNG', transparency=(0, 0, 0))
        data = path.read_bytes()
        test.assertEqual([1024, 1024], assert_native_image(data)['size'])
        with Image.open(BytesIO(normalize_native_image(data))) as visible:
            test.assertEqual((255, 255, 255), visible.getpixel((512, 512)))
            test.assertEqual((128, 128, 128), visible.getpixel((20, 20)))
    import errno
    for failure in (MemoryError('bounded local memory'), OSError(errno.ENOMEM, 'local allocator'),
                    OSError('out of memory when reading image file'), OSError('decoder fixture not available'),
                    OSError('unknown local codec failure'), RuntimeError('local decoder fault')):
        with patch('PIL.Image.open', side_effect=failure):
            with test.assertRaises(CandidateCommitError) as raised: assert_native_image(good)
            test.assertNotIsInstance(raised.exception, ImageOutputRejected)
            if not isinstance(failure, RuntimeError):
                with test.assertRaises(CandidateCommitError) as raised: transport._validate_output_bytes(good)
                test.assertNotIsInstance(raised.exception, ImageOutputRejected)
    source = native_bytes((5000, 1000))
    out = BytesIO(); Image.new('RGB', (5000, 1000), 'white').save(out, format='PNG')
    images = transport._prepare_edit_inputs([source], out.getvalue())
    test.assertEqual((4096, 819), Image.open(BytesIO(images[0])).size)
    test.assertEqual(Image.open(BytesIO(images[0])).size, Image.open(BytesIO(images[-1])).size)
    with test.assertRaisesRegex(Exception, 'original'):
        transport._prepare_edit_inputs([good], out.getvalue())
    # Count actual chunks, even with a missing/lying Content-Length.
    class Response:
        status_code = 200
        headers = {}
        closed = False
        def iter_content(self, chunk_size):
            yield good
            yield b'x'
            raise AssertionError('Read beyond the first excessive chunk')
        def close(self): self.closed = True
    response = Response()
    with patch.object(transport, 'IMAGE_OUTPUT_MAX_BYTES', len(good)), patch.object(
            transport, 'request_public_url', return_value=response):
        with test.assertRaises(CandidateCommitError):
            transport._download_image_bytes('https://example.invalid/generated.png')
    test.assertTrue(response.closed)
    payload = json.dumps({'data': [{'b64_json': base64.b64encode(good).decode()}]})
    with patch.object(transport, 'IMAGE_OUTPUT_MAX_BYTES', len(good)):
        test.assertEqual(good, transport._decode_image_response(payload))
        bad = json.dumps({'data': [{'b64_json': base64.b64encode(good+b'x').decode()}]})
        with test.assertRaises(CandidateCommitError):
            transport._decode_image_response(bad)
    with patch.object(transport, 'IMAGE_RESPONSE_MAX_BYTES', 10):
        with test.assertRaises(CandidateCommitError):
            transport._decode_image_response(payload)
        from types import SimpleNamespace
        body = BytesIO(b'x'*11)
        with test.assertRaises(ImageOutputRejected) as raised:
            transport._bounded_response_bytes(SimpleNamespace(headers={'Content-Length':'1'}, read=body.read))
        test.assertEqual(11, body.tell())
        test.assertEqual(b'x'*10, raised.exception.partial)
        exact = BytesIO(b'x'*10)
        test.assertEqual(b'x'*10, transport._bounded_response_bytes(SimpleNamespace(headers={}, read=exact.read)))
        declared = BytesIO(b'x'*11)
        with test.assertRaises(ImageOutputRejected):
            transport._bounded_response_bytes(SimpleNamespace(headers={'Content-Length':'11'}, read=declared.read))
        test.assertEqual(0, declared.tell())
    with patch.object(transport, 'IMAGE_OUTPUT_MAX_PIXELS', 10):
        with test.assertRaises(CandidateCommitError):
            transport._decode_image_response(payload)


def verify_rejection_disposition(test):
    from core.image_response import (begin_response, submit_response, save_response, recover_response,
        response_binding, response_directory, resolve_response, response_submission_metrics)
    from core.image_generation_executor import generate_one, _finalize_local as finalize_candidate
    from core.image_provider_common import CandidateCommitError
    from core.io import read_json
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp)
        task = dict(job_dir=tmp, logical_task_id='generate:B1:main', task_fingerprint='fixture',
            candidate_revision=0, child='B1', role='main', prompt='fixture', generation_references=[],
            output_path=str(job/'fixture.candidate0.png'), source_path='source.png')
        (job/'source.png').write_bytes(native_bytes())
        audit = dict(response_binding=response_binding(task), logical_task_id=task['logical_task_id'], request_id='paid-once')
        receipt = begin_response(response_directory(task), provider='fixture', audit=audit)
        submit_response(receipt, audit)
        save_response(receipt, native_bytes((2,2)), audit)
        with patch('core.image_generation_executor.generate_with_provider_retries') as remote, patch(
                'core.image_generation_executor.reserve_image'), patch('core.image_generation_executor.release_image'):
            saved = generate_one(task, plugin=None)
            with test.assertRaises(CandidateCommitError):
                finalize_candidate(saved, plugin=None)
            test.assertEqual('output_rejected', read_json(receipt)['status'])
            with test.assertRaises(CandidateCommitError):
                generate_one(task, plugin=None)
            remote.assert_not_called()
        test.assertTrue(receipt.with_suffix('.bin').is_file())
        test.assertEqual(1, response_submission_metrics(job)['image_provider_submission_count'])
        relative = receipt.relative_to(job).as_posix()
        result = resolve_response(job, relative, action='approve_one_resend', reason='Operator reviewed rejected native output; one replacement authorized')
        test.assertEqual(0, result['requests_sent'])
        test.assertEqual({}, recover_response(task))
        replacement = begin_response(response_directory(task), provider='fixture', audit=audit)
        test.assertEqual(1, response_submission_metrics(job)['image_provider_submission_count'])
        # The transport worker, not the test, crosses the replacement POST boundary.
        from core.image_provider_common import ImageOutputRejected
        from core.image_provider_routing import _provider_worker
        from queue import Queue
        queue=Queue()
        def limited(**kwargs):
            kwargs['request_observer'](kwargs['request_audit'])
            raise ImageOutputRejected('Synthetic envelope byte limit reached')
        with patch('core.image_provider_routing.generate_with_registry_image_provider', side_effect=limited):
            _provider_worker('fixture',[str(job/'source.png')],'fixture',None,'paid-once',str(replacement),queue)
        event=queue.get_nowait()
        if event.get('event'):event=queue.get_nowait()
        test.assertTrue(event['local_failure'])
        test.assertEqual('output_rejected',read_json(replacement)['status'])
        with test.assertRaises(CandidateCommitError):recover_response(task)
        test.assertEqual(2,response_submission_metrics(job)['image_provider_submission_count'])
        # Retained rejected bytes must not re-block an explicitly authorized replacement.
        with patch('core.image_response.IMAGE_OUTPUT_MAX_BYTES',1):
            resolve_response(job,replacement.relative_to(job).as_posix(),action='approve_one_resend',reason='Second rejected result explicitly disposed')
            third=begin_response(response_directory(task),provider='fixture',audit=audit)
            submit_response(third,audit)
        test.assertEqual(3,response_submission_metrics(job)['image_provider_submission_count'])
    from types import SimpleNamespace
    from http.client import IncompleteRead
    from core import image_provider_transport as transport
    from core.image_response import save_transport_response, materialize_response
    jpeg = BytesIO()
    with Image.open(BytesIO(native_bytes())) as image: image.save(jpeg, format='JPEG')
    envelope = json.dumps({'data': [{'b64_json': base64.b64encode(jpeg.getvalue()[:250]).decode()}]}).encode()
    prefix, tail = b'first completed chunk', b'last incomplete chunk'
    spec = transport.ImageProviderSpec(name='fixture', display='fixture', api_type='openai_images_edit',
        url='https://fixture.invalid', model='gpt-image-2', key_env='', protocol_profile={},
        request_size='1024x1024', output_contract='square')
    class Response:
        headers = {}
        def __init__(self, partial): self.partial, self.reads, self.stream = partial, 0, BytesIO(envelope)
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, size):
            if not self.partial: return self.stream.read(size)
            self.reads += 1
            if self.reads == 1: return prefix
            raise IncompleteRead(tail, 1)
    for mode in ('header_recovery', 'header_worker', 'partial', 'overflow_partial'):
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp); (job/'source.png').write_bytes(native_bytes())
            task = dict(job_dir=tmp, logical_task_id='generate:B1:main', task_fingerprint='fixture',
                candidate_revision=0, child='B1', role='main', prompt='fixture', generation_references=[])
            audit = dict(response_binding=response_binding(task), logical_task_id=task['logical_task_id'], request_id=mode)
            receipt = begin_response(response_directory(task), provider='fixture', audit=audit)
            if mode == 'header_recovery':
                submit_response(receipt, audit)
                save_transport_response(receipt, 'body', envelope, audit)
                with test.assertRaises(CandidateCommitError): materialize_response(receipt)
            else:
                limit = 41 if mode == 'overflow_partial' else transport.IMAGE_RESPONSE_MAX_BYTES
                with patch.object(transport, '_image_provider_spec', return_value=spec), patch.object(
                        transport, '_provider_api_key', return_value='local-fixture-token'), patch.object(
                        transport, '_canonical_image_edit_request', return_value=SimpleNamespace(
                            prompt='fixture', quality='', background='', moderation='', size='1024x1024')), patch.object(
                        transport, '_openai_images_edit_multipart_body', return_value=(b'fixture request', 'fixture')), patch.object(
                        transport, 'IMAGE_RESPONSE_MAX_BYTES', limit), patch.object(
                        transport, '_decode_image_response', wraps=transport._decode_image_response) as decode, patch.object(
                        transport.urllib.request, 'urlopen', return_value=Response(mode in ('partial', 'overflow_partial'))) as remote:
                    _provider_worker('fixture', [str(job/'source.png')], 'fixture', None, mode, str(receipt), Queue())
                test.assertEqual(1, remote.call_count)
                test.assertEqual(1 if mode == 'header_worker' else 0, decode.call_count)
            record = read_json(receipt)
            test.assertEqual('submitted' if mode == 'partial' else 'output_rejected', record['status'])
            test.assertEqual(1, response_submission_metrics(job)['image_provider_submission_count'])
            if mode in ('partial', 'overflow_partial'):
                expected = prefix+tail if mode == 'partial' else (prefix+tail)[:41]
                test.assertEqual(expected, receipt.with_suffix('.partial').read_bytes())
                test.assertNotIn('body_sha256', record)
            else:
                test.assertEqual(envelope, receipt.with_suffix('.http').read_bytes())
                test.assertFalse(receipt.with_suffix('.bin').exists())
            if mode != 'partial':
                with test.assertRaises(CandidateCommitError): recover_response(task)
                result = resolve_response(job, receipt.relative_to(job).as_posix(), action='approve_one_resend', reason='Explicit fixture disposition')
                test.assertEqual(0, result['requests_sent'])
                test.assertEqual(1, response_submission_metrics(job)['image_provider_submission_count'])


def verify_instance_projection(test, job, source, compiled, kit, plugin):
    from copy import deepcopy
    from core.image_reference_context import resolve_edit_references
    from core.image_prompt_compiler import compile_task_prompt
    from core.image_tasks import _form_task, _task_fingerprint
    from core.required_role_policy import compiled_image_policy
    scene = deepcopy(compiled); scene['role']='scene'
    source = deepcopy(source)
    source['observation']['objects'].extend([
        dict(object_id='unselected_back',kind='same product',state='behind the selected unit',
             sale_membership='product',visibility='visible',membership_evidence=[]),
        dict(object_id='included_anchor',kind='installation anchor',state='detail view',
             sale_membership='included_accessory',visibility='visible',membership_evidence=[])])
    edit = {'create': 'Edit attachment 1 directly.', 'replace': [], 'preserve': []}
    resolve_edit_references(scene, [source], job=job, child='B1', edit_contract=edit)
    selection = edit['create'].split('\n',1)[1]
    owner = scene['region_intent']['targets'][0]['object_id']
    test.assertIn(owner, selection); test.assertIn('left', selection)
    test.assertIn('exactly 1 selected source-visible', selection)
    test.assertIn('unselected_back',selection)
    test.assertNotIn('included_anchor',selection)
    without=deepcopy(scene);without['region_intent']['mode']='not_applicable';without.pop('product_region')
    unmasked={'create':'Edit attachment 1 directly.','replace':[],'preserve':[]}
    refs=resolve_edit_references(without,[source],job=job,child='B1',edit_contract=unmasked)
    test.assertEqual(edit['product_selection'],unmasked['product_selection'])
    test.assertEqual(selection,unmasked['create'].split('\n',1)[1])
    test.assertNotIn('protected_mask',refs[0])
    scene_kit = {**kit, 'image_briefs': [scene], 'source_references': [source]}
    task = _form_task(job=job, plugin=plugin, child={'asin':'B1'}, spec={'role':'scene', 'source':source},
        design_kit=scene_kit, image_policy=compiled_image_policy(plugin), product_type='BED_FRAME')
    test.assertEqual('ready', task['formation_status'])
    test.assertIn(selection, task['edit_contract']['create'])
    ordinary = compile_task_prompt(task=task)
    test.assertLess(ordinary.index('unselected_back'),ordinary.index('Preserve:'))
    # Targeted repair must not project original-source windows into candidate coordinates.
    prompt = compile_task_prompt(task=task, targeted_edit=True)
    test.assertNotIn('normalized windows', prompt)
    from core.image_generation import _compose_revision_prompt
    from tests.current_image_contract_fixture import current_image_task
    for role in ('main', 'scene', 'func', 'size'):
        repair = current_image_task(role)
        original = {**repair['generation_references'][0], 'kind': 'product_evidence'}
        candidate = {**original, 'kind': 'edit_base', 'source_id': 'candidate_0', 'sha256': 'c'*64, 'path': 'candidate.png'}
        repair['generation_references'] = [candidate, original]
        repair['edit_base_sha256'] = candidate['sha256']
        if role == 'func':
            repair['display_copy_contract']['bindings'][1]['target'] = dict(
                source_id=original['source_id'], feature_id=original['visible_evidence'][0]['feature_id'])
        if role == 'size':
            repair['measurement_authority']['measurement_groups'] = [dict(id='width', source_id=original['source_id'],
                measured_part='cabinet', axis='width', render_text='24 in', evidence_type='dimension')]
        before = deepcopy(repair)
        compiled_repair = compile_task_prompt(task=repair, targeted_edit=True)
        reason = 'Correct only the selected defect, including its necessary text or graphic change.'
        complete = _compose_revision_prompt(base_prompt=compiled_repair, request_heading='TARGETED CANDIDATE EDIT',
            request_intro='Edit attachment 1 only for the listed issue.', reason=reason)
        test.assertEqual(before, repair)
        test.assertIn(reason, complete)
        test.assertIn('Attachment 1: edit_base (candidate_0)', complete)
        test.assertIn('Attachment 2: product_evidence (source_00)', complete)
        test.assertIn('color=soft white; sold quantity=1', complete)
        # Inspect the whole request, not only the repair introduction: no other
        # section may invite global redesign or re-render all candidate copy.
        test.assertNotRegex(complete, r'Design [^.]*freely|Remove or replace all other source|Use a (?:plain )?technical canvas|Present the complete sold product|Render only the authored strings')
        style = complete.split('[STYLE]\n', 1)[1].split('[TEXT]\n', 1)[0]
        test.assertIn('except where the requested correction explicitly requires a change', style)
        test.assertIn('constrain that correction', style)
        test.assertIn('do not re-render unaffected text', complete)
        test.assertIn('Do not automatically reuse source coordinates or masks on the candidate', complete)
        test.assertIn('restoration target only when the correction explicitly requests it', complete)
        test.assertIn('text moves or changes explicitly required by the requested correction', complete)
        test.assertNotIn('Original-source coordinates do not apply', complete)
        test.assertNotIn('Supplementary facts or depicted details only', complete)
        if role in {'func', 'size'}:
            test.assertIn('text_color = #303634', style)
            test.assertIn('preserving the candidate', style)
        if role == 'func':
            test.assertIn('<RENDERABLE_TEXT>\nFlexible Shelf Storage\nAdjustable Shelf\nOpen Storage Access\n</RENDERABLE_TEXT>', complete)
            test.assertIn('keep unaffected labels in place', complete)
        if role == 'size':
            test.assertIn('cabinet / width: 24 in', complete)
    from tests.current_image_contract_fixture import current_product_feature
    function = current_image_task('func')
    reference = function['generation_references'][0]
    reference['visible_evidence'].append(current_product_feature(feature='surface_finish'))
    feature_facts = ['Left demonstration is cropped at the canopy; the right view shows the complete tree.',
                     'Step 1 shows the spike cap separated from the disk by a visible gap.']
    reference['visible_evidence'][0]['physical_facts'] = feature_facts + ['Unselected source nine-row mode table and green capsule layout']
    function['display_copy_contract']['bindings'][0]['target'] = dict(source_id='source_00', feature_id='frame_support')
    for binding, feature_id in zip(function['display_copy_contract']['bindings'][1:], ('frame_support', 'surface_finish')):
        binding['target'] = dict(source_id='source_00', feature_id=feature_id)
    function['display_copy_contract']['bindings'][0]['evidence_ids']=['physical:source_00:frame_support:0']
    function['display_copy_contract']['bindings'][1]['evidence_ids']=['physical:source_00:frame_support:1']
    without_windows = compile_task_prompt(task=function)
    test.assertIn('preserving the selected product views and their approved locations', without_windows)
    test.assertIn('without moving, scaling or obscuring product views', without_windows)
    test.assertNotIn('Design hierarchy and line breaks freely', without_windows)
    test.assertIn('Rebuild the hierarchy and grouping of authorized copy in non-product graphic space', without_windows)
    test.assertNotIn('Unselected source nine-row mode table', without_windows)
    text = without_windows.split('[TEXT]\n', 1)[1].split('[OUTPUT]', 1)[0]
    test.assertIn('F1: attachment 1 (source_00), object frame, feature frame_support.', text)
    test.assertIn('[1,"F1",[0]]', text)
    test.assertIn('[2,"F1",[1]]', text)
    test.assertNotIn('TEXT items 1, 2', text)
    for fact in feature_facts:
        test.assertEqual(1, text.count(fact), 'Each caption must retain only its selected physical fact')
        test.assertNotIn(fact, text.split('<RENDERABLE_TEXT>', 1)[1])
    test.assertNotIn('positioning instructions', text)
    test.assertNotIn('Place each label/leader', text)
    for environment in ('graphic_canvas', 'source_setting', 'designed_environment'):
        scoped = deepcopy(function); scoped['image_direction']['environment_mode'] = environment
        prompt = compile_task_prompt(task=scoped)
        style = prompt.split('[STYLE]\n', 1)[1].split('[TEXT]\n', 1)[0]
        test.assertEqual(environment == 'graphic_canvas', 'complete indoor/outdoor setting' in style)
        if environment == 'graphic_canvas':
            test.assertIn('explicit visible action in ROLE, not future use', style)
        test.assertEqual(text, prompt.split('[TEXT]\n', 1)[1].split('[OUTPUT]', 1)[0])
    # The planner chooses presentation; physical copy bindings remain factual.
    original_direction = deepcopy(function['image_direction'])
    function['image_direction']['visual_goal'] = 'Keep both existing detail views; place nearby captions without leaders or a new inset.'
    function['image_direction']['presentation']['state'] = 'An exposed spike remains attached to the trunk, not inserted into soil.'
    unchanged = deepcopy(function)
    prompt = compile_task_prompt(task=function)
    test.assertEqual(unchanged, function)
    test.assertIn(function['image_direction']['visual_goal'], prompt)
    test.assertIn('Target visible state/action: ' + function['image_direction']['presentation']['state'], prompt)
    test.assertNotIn('Target product state/use:', prompt)
    test.assertIn('unless a leader is planned', prompt)
    function['image_direction']['visual_goal'] = 'Show the evidenced soil installation; use a leader on the visible spike collar.'
    function['image_direction']['presentation']['state'] = 'The demonstrated spike is inserted into the local soil cross-section.'
    test.assertIn(function['image_direction']['presentation']['state'], compile_task_prompt(task=function))
    test.assertIn(function['image_direction']['visual_goal'], compile_task_prompt(task=function))
    function['image_direction'] = original_direction
    part = lambda identity, query: dict(part_id=identity, query=query, crop=dict(left=.12, top=.24, right=.56, bottom=.78))
    function['edit_contract']['product_selection'] = dict(source_id='source_00', selected=[
        dict(object_id='frame', components=[part('frame_support', 'front_scope'), part('frame_support/closeup', 'closeup_scope'),
            part('surface_finish/detail', 'finish_scope'), part('physical_rail', 'unrelated_scope'),
            part('frame_supporting/detail', 'prefix_only_scope')]),
        dict(object_id='other_frame', components=[part('frame_support/detail', 'wrong_owner_scope')])])
    windowed = compile_task_prompt(task=function)
    import json
    persisted = json.loads(json.dumps(function, sort_keys=True))
    test.assertEqual(windowed, compile_task_prompt(task=persisted))
    test.assertEqual(_task_fingerprint(function), _task_fingerprint(persisted))
    for query in ('front_scope', 'closeup_scope', 'finish_scope'):
        test.assertIn(query, windowed)
    for query in ('unrelated_scope', 'prefix_only_scope', 'wrong_owner_scope'):
        test.assertNotIn(query, windowed)
    test.assertIn('not output layout boxes', windowed)
    test.assertIn('do not reconstruct hidden or cropped-off parts', windowed)
    test.assertIn("named visible part's surface", windowed)
    test.assertIn('Add a detail view only when planned', windowed)
    test.assertIn('Measurement arrows follow ROLE', windowed)
    for change in ('wrong_source', 'wrong_owner', 'root_only'):
        unbound = deepcopy(function)
        selection = unbound['edit_contract']['product_selection']
        if change == 'wrong_source': selection['source_id'] = 'source_99'
        elif change == 'wrong_owner': selection['selected'][0]['object_id'] = 'unselected_frame'
        else: selection['selected'][0]['components'] = []
        test.assertEqual(without_windows, compile_task_prompt(task=unbound))
    evidence = {**reference, 'kind': 'product_evidence'}
    function['generation_references'] = [{**evidence, 'kind': 'edit_base', 'source_id': 'candidate_0'}, evidence]
    repair_with_windows = compile_task_prompt(task=function, targeted_edit=True)
    test.assertNotIn('Declared source windows', repair_with_windows)
    test.assertNotIn('[0.12,0.24,0.56,0.78]', repair_with_windows)
    slash_ids = current_image_task('func')
    slash_ids['generation_references'][0]['visible_evidence'] = [
        current_product_feature(feature='frame', object_id='frame'),
        current_product_feature(feature='frame/detail', object_id='fastener')]
    for binding, feature_id in zip(slash_ids['display_copy_contract']['bindings'][1:], ('frame', 'frame/detail')):
        binding['target'] = dict(source_id='source_00', feature_id=feature_id)
    slash_ids['edit_contract']['product_selection'] = dict(source_id='source_00', selected=[
        dict(object_id='frame', components=[part('frame/detail', 'wrong_exact_scope'),
            part('frame/detail/left', 'wrong_longest_scope')])])
    conflicting = compile_task_prompt(task=slash_ids)
    test.assertNotIn('wrong_exact_scope', conflicting)
    test.assertNotIn('wrong_longest_scope', conflicting)
    slash_ids['edit_contract']['product_selection']['selected'] = [dict(object_id='fastener', components=[
        part('frame/detail', 'exact_long_id_scope'), part('frame/detail/left', 'longest_id_scope')])]
    resolved = compile_task_prompt(task=slash_ids)
    test.assertEqual(1, resolved.count('exact_long_id_scope'))
    test.assertEqual(1, resolved.count('longest_id_scope'))
    test.assertNotIn('Declared source windows', resolved.split('F1:', 1)[1].split('F2:', 1)[0])
    changed = deepcopy(task); changed['edit_contract']['create'] += ' changed selection'
    test.assertNotEqual(task['task_fingerprint'], _task_fingerprint(changed))
    scene['image_direction']['presentation']['scope']='detail_only'
    edit={'create': 'Edit attachment 1 directly.', 'replace': [], 'preserve': []}
    resolve_edit_references(scene,[source],job=job,child='B1',edit_contract=edit)
    test.assertNotIn('exactly 1', edit['create'])
    test.assertNotIn('unselected_back',edit['create'])


def verify_background(test):
    from core import image_qa
    from tests.test_qa_lite_v1 import _task
    task = _task('main')
    with patch.object(image_qa, 'inspect_image_pixel_evidence', return_value={'white_background': True}):
        test.assertEqual('inconclusive', image_qa._main_background_gate(task, Path('candidate.png'))['status'])
    with tempfile.TemporaryDirectory() as tmp:
        candidate = dict(candidate_path='candidate.png', candidate_sha256='c'*64)
        for boxes in [[(1, 1, 800, 1598)], [(1, 1, 700, 1598), (900, 1, 1598, 1598)]]:
            image = Image.new('RGB', (1600, 1600), 'white')
            draw = ImageDraw.Draw(image)
            for box in boxes: draw.rectangle(box, fill='#808080')
            image.save(Path(tmp)/candidate['candidate_path'])
            pixel = image_qa.inspect_image_pixel_evidence(Path(tmp)/candidate['candidate_path'])
            test.assertFalse(pixel['white_background'])
            test.assertEqual(4, pixel['white_corner_count'])
            with patch('core.vision_gemini_client.gemini_stream_generate', side_effect=AssertionError('Missing references must prevent paid QA')) as model:
                result = image_qa._evaluate(Path(tmp), object(), task, candidate)
            model.assert_not_called()
            test.assertEqual('inconclusive', result['automatic_decision'])
            test.assertEqual(1, sum(g['gate']=='main_background' for g in result['gates']))
            test.assertTrue(any('not pixel identity' in item for item in result['human_review_checklist']))
