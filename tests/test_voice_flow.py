"""Voice decisions and queued-result delivery, without microphones or playback."""
import importlib.util
import io
from contextlib import redirect_stdout
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-voice-flow')

spec = importlib.util.spec_from_file_location('aries_voice_flow',
    Path(__file__).resolve().parents[1] / 'experiments/voice/voice.py')
voice = importlib.util.module_from_spec(spec)
spec.loader.exec_module(voice)


async def test_weak_language_evidence_still_stays_inside_the_two_languages():
    """Changed 2026-10-03 against a measurement. Returning None on weak evidence
    let the decoder choose among all 99 languages, which answered Macedonian
    speech with pt, bg, ro, hr and pl; `decode_command` then discarded seven of
    ten real commands as "unsupported detected language". The weak winner between
    the two languages this person speaks now decides; only the vocabulary prompt
    is forfeited, because that is where a wrong guess does damage."""
    model = Mock()
    model.detect_language.return_value = ('en', .01, [('en', .01), ('mk', .005)])
    model.transcribe.return_value = ([], SimpleNamespace(language='en', language_probability=.01))
    args = SimpleNamespace(languages=('mk', 'en'), language=None)
    voice.decode_command(model, [], args)
    kwargs = model.transcribe.call_args.kwargs
    check('weak evidence still constrains decoding to an allowed language',
          kwargs['language'] == 'en')
    check('but weak evidence forfeits the vocabulary prompt',
          kwargs['initial_prompt'] is None)
    model.detect_language.return_value = ('mk', .2, [('mk', .2), ('en', .02)])
    model.transcribe.return_value = ([], SimpleNamespace(language='mk', language_probability=.2))
    voice.decode_command(model, [], args)
    check('confident evidence does get the prompt',
          model.transcribe.call_args.kwargs['initial_prompt'] == voice.PROMPTS['mk'])
    check('measured Macedonian confidence of .2 remains usable',
          voice.pick_language(model, [], args.languages) == ('mk', .2))
    model.detect_language.return_value = ('fr', .9, [('fr', .9)])
    check('no allowed-language evidence at all is unknown, not a guess',
          voice.pick_language(model, [], args.languages) == (None, 0.0))


async def test_caption_echoes_and_wake_word_boundaries():
    for text in ('Thank you for watching.', 'Thanks for watching! Subscribe for more videos.',
                 'Captions by GetTranscribed.com', 'Ari, thanks for watching.'):
        check('discard standalone caption: ' + text, voice.caption_hallucination(text))
    check('a quoted phrase inside an actual command is preserved',
          not voice.caption_hallucination('Ari, write Thank you for watching in the file'))
    check('a bare wake name opens the follow-up window', voice.wake_match('Ари') == '')
    check('a longer word never wakes the assistant', voice.wake_match('Ariana play music') is None)
    model = Mock()
    segment = SimpleNamespace(text='Thanks for watching!', no_speech_prob=.01,
                              avg_logprob=-.1, compression_ratio=1.)
    model.transcribe.return_value = ([segment], SimpleNamespace(language='en'))
    text, _, _ = voice.transcribe(model, [], 'en')
    check('caption filtering actually runs after segment decoding',
          not text and any('caption hallucination' in reason for reason in voice.DROPPED))


async def test_queued_command_reads_only_its_result_and_speaks_the_answer():
    receipt = {'message': 'Task queued', 'result': {'id': 'goal-1', 'state': 'queued'}}
    finished = {'id': 'goal-1', 'state': 'done', 'steps': [{'execution_result': {
        'filesystems': [{'metric': 'disk.used_pct', 'subject': '/', 'value': 8.5,
                         'unit': '%', 'detail': {'free_gib': 396.28, 'size_gib': 433.09}}]}}]}
    responses = [io.BytesIO(json.dumps({'id': 'goal-1', 'state': 'running'}).encode()),
                 io.BytesIO(json.dumps(finished).encode())]
    with patch.object(voice.urllib.request, 'urlopen', side_effect=responses) as get, \
            patch.object(voice.time, 'sleep'):
        result = voice.await_outcome(receipt)
    spoken = voice.spoken_outcome(result, 'mk')
    check('polls only the submitted goal, without resubmitting the action',
          get.call_count == 2 and all(c.args[0].endswith('/workspace/goal-1') for c in get.call_args_list))
    check('says measured disk space rather than the queue receipt',
          '396' in spoken and '8.5' in spoken and 'queued' not in spoken.lower())


async def test_pending_failed_and_unavailable_results_do_not_claim_completion():
    receipt = {'result': {'id': 'goal-2', 'state': 'queued'}}
    with patch.object(voice.urllib.request, 'urlopen') as get:
        result = voice.await_outcome(receipt, timeout=0)
    check('zero wait has no network call and reports work still pending',
          not get.called and 'still working' in voice.spoken_outcome(result, 'en'))
    with patch.object(voice.urllib.request, 'urlopen', side_effect=TimeoutError('offline')):
        result = voice.await_outcome(receipt)
    check('network failure makes completion unknown',
          result['state'] == 'unknown' and 'cannot confirm' in voice.spoken_outcome(result, 'en'))
    stale = {'state': 'failed', 'gaps': ['Read-back failed'],
             'reading': {'metric': 'disk.used_pct', 'value': 8.5, 'subject': '/'}}
    check('old readings cannot hide a failed final outcome',
          'failed' in voice.spoken_outcome(stale, 'en').lower()
          and '8.5' not in voice.spoken_outcome(stale, 'en'))
    check('approval remains a request to the user',
          'approval' in voice.spoken_outcome({'state': 'proposed'}, 'en'))
    with patch.object(voice.urllib.request, 'urlopen', return_value=io.BytesIO(
            json.dumps({'id': 'another-goal', 'state': 'done'}).encode())):
        result = voice.await_outcome(receipt)
    check('another goal cannot supply the answer', result['state'] == 'unknown')


async def test_ambiguous_aliases_never_submit_a_room_conversation():
    import tempfile
    for text in ('ара, што правиш', 'Ара отвори Firefox', 'ary open Firefox'):
        check('ordinary speech is not a wake: '+text,voice.wake_match(text) is None)
    for text in ('Ари, отвори Firefox','ARIES, show status','Хари, отвори Firefox'):
        check('explicit supported name still activates: '+text,bool(voice.wake_match(text)))
    with tempfile.TemporaryDirectory() as directory:
        args=SimpleNamespace(mute=False,silence_ms=400,max_seconds=15,start_timeout=8,
            input=None,reply_wait=8,pending_state=Path(directory)/'pending.json')
        speaker=Mock()
        with patch.object(voice,'listen',side_effect=[([],{'endpoint_wait':.4}),KeyboardInterrupt]), \
             patch.object(voice,'decode_command',return_value=('ара, отвори Firefox',.01,None,'mk',.9)), \
             patch.object(voice,'act') as act,patch.object(voice,'Pulse'), \
             patch.object(voice,'speech',speaker),patch('builtins.print'):
            try:voice.serve(Mock(),Mock(),args)
            except KeyboardInterrupt:pass
        check('real serve loop neither submits nor speaks after an ambiguous alias',not act.called and not speaker.speak.called)


async def test_the_real_serve_loop_speaks_the_completed_result():
    args = SimpleNamespace(mute=False, silence_ms=400, max_seconds=15,
                           start_timeout=8, input=None, reply_wait=8)
    result = {'id': 'goal-3', 'state': 'done', 'cards': [{'title': 'Answer', 'text': '42'}]}
    speaker = Mock()
    with patch.object(voice, 'listen', side_effect=[([], {'endpoint_wait': .4}), KeyboardInterrupt]), \
            patch.object(voice, 'decode_command', return_value=('Ari, show status', .01, None, 'en', .9)), \
            patch.object(voice, 'act', return_value=({'message': 'Task queued'}, .02, None)), \
            patch.object(voice, 'await_outcome', return_value=result) as wait, \
            patch.object(voice, 'Pulse'), patch.object(voice, 'speech', speaker), \
            patch('builtins.print'):
        try:
            voice.serve(Mock(), Mock(), args)
        except KeyboardInterrupt:
            pass
    check('serve actually waits for the result before replying', wait.call_count == 1)
    check('serve passes the answer to blocking speech, not the queue receipt',
          speaker.speak.call_count == 1 and '42' in speaker.speak.call_args.args[0]
          and speaker.speak.call_args.kwargs == {'language': 'en', 'blocking': True})


async def test_measurement_answer_uses_final_requested_evidence():
    outcome = {'state': 'answered', 'agent': {'finished': True, 'contract': {
        'answer': 'measurements', 'requirements': [{'metric': 'cpu.used_pct'}]}},
        'cards': [{'title': 'Answer', 'text': 'CPU 3.3%', 'evidence': 'fresh'}],
        'evidence': [
            {'evidence_id': 'old', 'verified': True,
             'data': {'metric': 'cpu.used_pct', 'value': 8.4}},
            {'evidence_id': 'fresh', 'verified': True, 'data': [
                {'metric': 'cpu.used_pct', 'value': 3.3},
                {'metric': 'memory.used_pct', 'value': 42.9}]}]}
    answer = voice.spoken_outcome(outcome, 'en')
    check('speech agrees with final recheck and stays on the requested metric',
          '3.3' in answer and '8.4' not in answer and '42.9' not in answer)
    parent = {'state': 'done', 'orchestration': {'role': 'parent'}, 'cards': [
        {'title': 'Answer', 'text': 'The processor is at 3.3%.'},
        {'title': 'Goal outcome', 'text': '1 of 1 sub-goals verified'}]}
    check('parallel answers never read the bookkeeping cards aloud',
          voice.spoken_outcome(parent, 'en') == 'The processor is at 3.3%.')


async def test_rejected_command_is_spoken_without_execution_retry():
    args = SimpleNamespace(mute=False, silence_ms=400, max_seconds=15,
                           start_timeout=8, input=None, reply_wait=8)
    clarification = 'наведи ја датотеката или адресата; /one.txt; /two.txt'
    error = 'HTTP 400: ' + json.dumps({'detail': 'AMBIGUOUS: ' + clarification})
    speaker = Mock()
    with patch.object(voice, 'listen', side_effect=[([], {'endpoint_wait': .4}), KeyboardInterrupt]), \
            patch.object(voice, 'decode_command', return_value=('Ари, прочитај ја', .01, None, 'mk', .9)), \
            patch.object(voice, 'act', return_value=(None, .02, error)) as act, \
            patch.object(voice, 'await_outcome') as wait, patch.object(voice, 'Pulse'), \
            patch.object(voice, 'speech', speaker), patch('builtins.print'):
        try:
            voice.serve(Mock(), Mock(), args)
        except KeyboardInterrupt:
            pass
    check('a real serve-loop rejection speaks the requested clarification',
          speaker.speak.call_args.args[0] == clarification)
    check('a rejected command is never retried or polled as a running task',
          act.call_count == 1 and wait.call_count == 0)
    check('connection errors are audible without exposing raw transport internals',
          'Traceback' not in voice.spoken_error('Traceback secret transport detail', 'en'))
    check('repeat protection gives an audible waiting instruction',
          'wait' in voice.spoken_error('HTTP 429: {}', 'en'))


async def test_delayed_results_are_polled_once_without_replaying_commands():
    pending = voice.PendingReplies()
    check('only bounded queued IDs enter delayed delivery',
          pending.add({'id': 'goal-later', 'state': 'running'}, 'mk')
          and not pending.add({'id': '../settings', 'state': 'queued'}, 'mk'))
    done = {'id': 'goal-later', 'state': 'done', 'cards': [{'title': 'Answer', 'text': '42'}]}
    with patch.object(voice.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(done).encode())) as get:
        result = pending.ready()
        check('completed task is delivered with its original language', result == (done, 'mk'))
        check('status polling cannot post or rerun the command',
              get.call_args.args == (voice.BASE + '/workspace/goal-later',))
    check('the same completion is never delivered twice', pending.ready() is None)
    pending.add({'id': 'offline-task', 'state': 'queued'}, 'en')
    with patch.object(voice.urllib.request, 'urlopen', side_effect=TimeoutError):
        check('a transient status failure retains the existing goal',
              pending.ready() is None and 'offline-task' in pending.goals)
    with patch.object(voice.time, 'monotonic', return_value=float('inf')):
        check('pending delivery expires instead of polling forever', pending.ready() is None and not pending.goals)


async def test_serve_delivers_a_late_answer_between_captures():
    args = SimpleNamespace(mute=False, silence_ms=400, max_seconds=15,
                           start_timeout=8, input=None, reply_wait=0)
    receipt = {'id': 'late-answer', 'state': 'queued'}
    done = {'id': 'late-answer', 'state': 'done', 'cards': [{'title': 'Answer', 'text': '42'}]}
    speaker = Mock()
    with patch.object(voice, 'listen', side_effect=[([], {'endpoint_wait': .4}), KeyboardInterrupt]), \
            patch.object(voice, 'decode_command', return_value=('Ari, show status', .01, None, 'en', .9)), \
            patch.object(voice, 'act', return_value=({'result': receipt}, .02, None)) as act, \
            patch.object(voice, 'await_outcome', return_value=receipt), \
            patch.object(voice.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(done).encode())), \
            patch.object(voice, 'Pulse'), patch.object(voice, 'speech', speaker), patch('builtins.print'):
        try:
            voice.serve(Mock(), Mock(), args)
        except KeyboardInterrupt:
            pass
    said = [call.args[0] for call in speaker.speak.call_args_list]
    check('serve first acknowledges waiting, then speaks the completed answer',
          len(said) == 2 and 'still working' in said[0] and '42' in said[1])
    check('late-answer delivery invokes the original action only once', act.call_count == 1)


async def test_file_reply_reads_verified_contents_instead_of_process_prose():
    result = {'state': 'done', 'agent': {'finished': True, 'contract': {
        'requirements': [{'capability': 'file.read', 'path': '/note.txt'}]}},
        'cards': [{'title': 'Verified goal result', 'text': 'Verified file: /note.txt', 'evidence': 'final'}],
        'evidence': [{'evidence_id': 'final', 'source': 'file.read', 'verified': True,
                      'data': {'path': '/note.txt', 'text': 'The actual note.'}}]}
    check('a file answer speaks the content from final verified evidence',
          voice.spoken_outcome(result, 'mk') == 'Во датотеката пишува: The actual note.')
    result['evidence'][0]['data']['text'] = 'word ' * 300
    spoken = voice.spoken_outcome(result, 'en')
    check('long spoken files are explicitly a bounded preview',
          spoken.startswith('The file begins: ') and len(spoken) < 850)


async def test_pending_replies_survive_restart_without_replaying_actions():
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'pending.json'
        pending = voice.PendingReplies(path)
        check('queued result is accepted for durable delivery',
              pending.add({'id': 'restart-test', 'state': 'queued', 'request': 'private text'}, 'mk'))
        check('state persists IDs only with private file permissions',
              'private text' not in path.read_text() and path.stat().st_mode & 0o777 == 0o600)
        restored = voice.PendingReplies(path)
        check('restart recovers the pending goal and language', restored.goals['restart-test'][0] == 'mk')
        done = {'id': 'restart-test', 'state': 'done'}
        with patch.object(voice.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(done).encode())) as get:
            check('restored delivery reads the original result', restored.ready() == (done, 'mk'))
            check('restored delivery only makes a status GET', get.call_args.args[0].endswith('/workspace/restart-test'))
        check('delivered result is removed durably', not voice.PendingReplies(path).goals)
        path.write_text('{broken')
        check('corrupt state does not prevent voice startup', not voice.PendingReplies(path).goals)
        path.write_text(json.dumps({'version': 1, 'goals': [
            {'id': '../../shell/act', 'language': 'mk', 'expires': voice.time.time()+60},
            {'id': 'expired', 'language': 'mk', 'expires': voice.time.time()-1},
            {'id': 'too-far', 'language': 'mk', 'expires': voice.time.time()+3600},
            {'id': 'invalid-expiry', 'language': 'mk', 'expires': 'tomorrow'}]}))
        check('invalid IDs and expired or invalid deadlines are discarded', not voice.PendingReplies(path).goals)


async def test_receipt_is_saved_before_waiting_for_completion():
    import tempfile
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'pending.json'
        args = SimpleNamespace(mute=True, silence_ms=400, max_seconds=15,
                               start_timeout=8, input=None, reply_wait=8, pending_state=path)
        receipt = {'id': 'interrupted-wait', 'state': 'queued'}
        with patch.object(voice, 'listen', return_value=([], {'endpoint_wait': .4})), \
                patch.object(voice, 'decode_command', return_value=('Ari, show status', .01, None, 'en', .9)), \
                patch.object(voice, 'act', return_value=({'result': receipt}, .02, None)), \
                patch.object(voice, 'await_outcome', side_effect=KeyboardInterrupt), \
                patch.object(voice, 'Pulse'), patch('builtins.print'):
            try:
                voice.serve(Mock(), Mock(), args)
            except KeyboardInterrupt:
                pass
        check('a restart during the initial wait preserves the accepted task ID',
              'interrupted-wait' in voice.PendingReplies(path).goals)


async def test_capture_never_reads_a_sink_monitor():
    """The 2026-10-03 bug: `default.audio.source` was an OUTPUT sink, so every
    capture came from that sink's monitor and ARIES listened to itself at
    -21.6 dBFS instead of to the room at -55.6 dBFS. Resolution, not a threshold,
    is the fix, so the resolution is what is tested."""
    MIC = 'alsa_input.pci-0000_00_1f.3.analog-stereo'
    SINK = 'alsa_output.pci-0000_00_1f.3.iec958-stereo'
    graph = [{'info': {'props': {'media.class': 'Audio/Source', 'node.name': MIC}}},
             {'info': {'props': {'media.class': 'Audio/Sink', 'node.name': SINK}}},
             {'info': {'props': {'media.class': 'Audio/Source',
                                 'node.name': SINK + '.monitor'}}}]
    check('a sink monitor is not counted as an input',
          voice.real_sources(graph) == [MIC])

    def resolve(nodes, default):
        """capture_target() with the graph replaced, and its notice captured."""
        voice._TARGET[:] = [False, 0.0, None]
        said = io.StringIO()
        with patch.object(voice, '_pw_nodes', return_value=nodes), \
                patch.object(voice, 'default_source_name', return_value=default), \
                redirect_stdout(said):
            return voice.capture_target(), said.getvalue()

    target, said = resolve(graph, SINK)
    check('a default source that is really a sink is overridden by the microphone',
          target == MIC)
    check('and the override is announced, not silent', 'not a microphone' in said)
    target, said = resolve(graph, MIC)
    check('a correct default source is left alone', target == MIC)
    target, said = resolve([], None)
    check('no input at all resolves to None rather than to a guess', target is None)
    check('having no input at all is said out loud too', 'no real audio input' in said)

    unplugged = graph + [{'id': 49, 'info': {
        'props': {'media.class': 'Audio/Device', 'device.description': 'Built-in Audio'},
        'params': {'EnumRoute': [{'direction': 'Input', 'available': 'no'},
                                 {'direction': 'Output', 'available': 'no'}]}}}]
    with_device = [{'info': {'props': {'media.class': 'Audio/Source', 'node.name': MIC,
                                       'device.id': 49}}}] + unplugged[1:]
    check('an input whose every jack reads unavailable is reported as unplugged',
          voice.source_is_connected(MIC, with_device) is False)
    target, said = resolve(with_device, None)
    check('and that is what gets said, ahead of any default-source complaint',
          target == MIC and 'NOTHING IS PLUGGED INTO IT' in said)
    check('a graph that cannot answer the question says None, not False',
          voice.source_is_connected(MIC, graph) is None)

    voice._TARGET[:] = [False, 0.0, None]
    check('an explicit --input is always honoured',
          voice.capture_target('plughw:2,0') == 'plughw:2,0')
    with patch.object(voice, 'capture_target', return_value=MIC) as resolved, \
            patch('subprocess.Popen', side_effect=AssertionError('stop here')):
        try:
            voice.record(0.1)
        except AssertionError:
            pass
        check('record() resolves its target instead of trusting the session default',
              resolved.called)


async def test_own_speech_is_not_taken_as_a_command():
    """The 44-goal loop of 2026-09-29: ARIES transcribed its own reply, the wake
    word survived, and it acted again. Remembering what was said is the check."""
    voice._LAST_SPOKEN[0] = ''
    voice.speech = SimpleNamespace(speak=lambda *a, **k: None)
    voice.speak_and_remember('Отворив Firefox за тебе.', 'mk')
    check('every spoken reply is remembered', voice._LAST_SPOKEN[0] == 'Отворив Firefox за тебе.')
    check('the reply heard back is recognised as an echo',
          voice.echoes_own_speech('отворив firefox за тебе', voice._LAST_SPOKEN[0]))
    check('an unrelated command is not an echo',
          not voice.echoes_own_speech('ари пушти ја музиката', voice._LAST_SPOKEN[0]))
    check('a single short word is too little evidence to call an echo',
          not voice.echoes_own_speech('да', voice._LAST_SPOKEN[0]))

    args = SimpleNamespace(languages=('mk', 'en'), language=None)

    def decode(text, *, playing, no_speech=.01, logprob=-.1):
        model = Mock()
        model.detect_language.return_value = ('mk', .9, [('mk', .9)])
        segment = SimpleNamespace(text=text, no_speech_prob=no_speech,
                                  avg_logprob=logprob, compression_ratio=1.)
        model.transcribe.return_value = ([segment],
                                         SimpleNamespace(language='mk', language_probability=.9))
        voice.DROPPED.clear()
        with patch.object(voice, 'audio_is_playing', return_value=playing):
            heard, _, _, _, _ = voice.decode_command(model, [], args)
        return heard

    check('while audio is out, our own sentence is discarded',
          decode('Отворив Firefox за тебе.', playing=True) == '')
    check('the reason is recorded, not silent',
          any('echo of our own reply' in d for d in voice.DROPPED))
    check('in a quiet room the same words are a person speaking, not an echo',
          decode('Отворив Firefox за тебе.', playing=False) == 'Отворив Firefox за тебе.')

    # Removed 2026-10-03 and kept removed on purpose: a stricter bar while audio
    # plays caught 0 false wakes (2 -> 2 on one 155 s recording) and cost 2 real
    # commands in 10 at +10 dB SNR. A middling score must therefore pass whether
    # or not the speakers are on, so that a person talking over music is heard.
    MIDDLING = dict(no_speech=.45, logprob=-.8)
    check('a middling score passes in a quiet room',
          decode('Ари, пушти ја музиката', playing=False, **MIDDLING) == 'Ари, пушти ја музиката')
    check('and passes equally while audio is playing — no second, stricter bar',
          decode('Ари, пушти ја музиката', playing=True, **MIDDLING) == 'Ари, пушти ја музиката')
    check('no threshold constant exists that depends on playback',
          not [n for n in dir(voice) if n.startswith('PLAYBACK_')])


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
