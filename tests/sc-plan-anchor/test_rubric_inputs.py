"""Optional rubric inputs exercise the real parser and transport boundary offline."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from test_jev_judge import (jj, STATEMENT, QUOTE, Transport, anchor, record, write,
                            run_cli, env, live, rubric_answers, ok)


class RubricInputTests(unittest.TestCase):
    def inputs(self, root):
        (Path(root) / '.git').mkdir()
        intent = {'id': 'approved-context', 'version': 2,
                  'content': 'The user approved JSON output for the client and generated client.'}
        intent['sha256'] = hashlib.sha256(intent['content'].encode()).hexdigest()
        questions = copy.deepcopy(ok(jj.load_simple_question_set('testability', jj.RUBRIC_QUESTIONS))['questions'])
        questions['faithful']['instructions'] = 'Compare anchor.statement with anchor.quote and intent.content when supplied.'
        sealed = {'questions': questions, 'digest': jj.questions_digest({'questions': questions})}
        write(root, 'intent.json', intent)
        write(root, 'rubric.json', sealed)
        return intent, sealed

    def args(self, root):
        return ['rubric', '--statement', STATEMENT, '--quote', QUOTE, '--repository-root', root,
                '--approved-intent-file', 'intent.json', '--questions', 'rubric.json']

    def test_dry_run_exact_context_seal_and_request_hash(self):
        with tempfile.TemporaryDirectory() as root:
            intent, sealed = self.inputs(root)
            with env(), mock.patch.object(jj, 'call_jev') as transport:
                code, out = run_cli(self.args(root) + ['--dry-run'])
            self.assertEqual(code, 0, out)
            transport.assert_not_called()
            self.assertFalse(out['data']['pass'])
            first, second = out['data']['requests']
            self.assertEqual(jj.encode_body(first), jj.encode_body(second))
            self.assertEqual(first['state']['intent'], intent)
            self.assertEqual(first['questions'], sealed['questions'])
            provenance = out['data']['anchors'][0]['inputs']
            self.assertEqual(provenance['question_seal'], sealed['digest'])
            self.assertEqual(provenance['request_sha256'], jj.questions_digest(first))
            self.assertEqual(provenance['intent'], {k: intent[k] for k in ('id', 'version', 'sha256')})

    def test_anchors_live_confirmations_and_offline_fixture(self):
        with tempfile.TemporaryDirectory() as root:
            intent, sealed = self.inputs(root)
            a = write(root, 'anchors.json', record(anchor()))
            args = ['rubric', '--anchors', a, '--id', 'ANC-001', '--repository-root', root,
                    '--approved-intent-file', 'intent.json', '--questions', 'rubric.json']
            response = {'answers': rubric_answers()}
            transport = Transport(response, response)
            with live(), mock.patch.object(jj, 'call_jev', transport):
                code, out = run_cli(args)
            self.assertEqual((code, out['data']['pass']), (0, True), out)
            self.assertEqual(len(transport.bodies), 2)
            self.assertEqual(transport.bodies[0], transport.bodies[1])
            self.assertEqual(transport.bodies[0]['state']['intent'], intent)
            self.assertEqual(transport.bodies[0]['questions'], sealed['questions'])
            fixture = write(root, 'answers.json', {'ANC-001': rubric_answers(observable=('yes', 0.5))})
            with env(), mock.patch.object(jj, 'call_jev') as transport:
                code, out = run_cli(args + ['--answers-file', fixture])
            self.assertEqual((code, out['data']['pass'], out['data']['anchors'][0]['verdict']), (0, False, 'inconclusive'))
            transport.assert_not_called()

    def test_inputs_are_independent_and_defaults_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            intent, sealed = self.inputs(root)
            base = ['rubric', '--statement', STATEMENT, '--quote', QUOTE, '--repository-root', root, '--dry-run']
            for flags in ([], ['--approved-intent-file', 'intent.json'], ['--questions', 'rubric.json']):
                with self.subTest(flags=flags), env():
                    code, out = run_cli(base + flags)
                self.assertEqual(code, 0, out)
                body = out['data']['requests'][0]
                self.assertEqual('intent' in body['state'], '--approved-intent-file' in flags)
                if not flags:
                    self.assertNotIn('inputs', out['data']['anchors'][0])
                    self.assertEqual(body['state'], {'anchor': {'statement': STATEMENT, 'quote': QUOTE, 'scope': ''}})
                if '--questions' not in flags:
                    self.assertEqual(body['questions'], ok(jj.load_simple_question_set('testability', jj.RUBRIC_QUESTIONS))['questions'])

    def test_optional_inputs_dry_run_remains_stdlib_only(self):
        with tempfile.TemporaryDirectory() as root:
            self.inputs(root)
            code = ("import sys\nsys.modules['yaml'] = None\n"
                    f"sys.path.insert(0, {str(Path(jj.__file__).parent)!r})\n"
                    "import jev_judge\n"
                    f"sys.exit(jev_judge.main({self.args(root) + ['--dry-run']!r}))\n")
            proc = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)['success'])

    def assert_refused_before_credentials(self, args, pattern):
        with env(), mock.patch.object(jj, 'resolved_api_key') as key, mock.patch.object(jj, 'call_jev') as transport:
            code, out = run_cli(args)
        self.assertEqual(code, 2, out)
        self.assertRegex(out['error']['code'], pattern)
        key.assert_not_called()
        transport.assert_not_called()

    def test_bad_authority_descriptors(self):
        with tempfile.TemporaryDirectory() as root:
            intent, _ = self.inputs(root)
            variants = [dict(intent, sha256='0' * 64), dict(intent, version=True), dict(intent, version=' '),
                        dict(intent, id=' '), dict(intent, content=''), dict(intent, unexpected='yes'),
                        {'content': intent['content']}, [], dict(intent, content=42)]
            for variant in variants:
                with self.subTest(variant=variant):
                    write(root, 'intent.json', variant)
                    self.assert_refused_before_credentials(self.args(root), 'RUBRIC.INTENT')
            for raw in ('{"id":"a","id":"b"}', '{"version":NaN}', '{bad', '\udcff'):
                with self.subTest(raw=repr(raw)):
                    (Path(root) / 'intent.json').write_bytes(raw.encode('utf-8', errors='surrogatepass'))
                    self.assert_refused_before_credentials(self.args(root), 'INPUT.MALFORMED')

    def test_bad_seals_roles_and_question_shapes(self):
        with tempfile.TemporaryDirectory() as root:
            _, sealed = self.inputs(root)
            cases = []
            for mutate in (
                lambda s: s.update(digest='0' * 64),
                lambda s: s['questions'].pop('faithful'),
                lambda s: s['questions'].update(addressed=s['questions'].pop('faithful')),
                lambda s: s['questions']['faithful'].update(type='score'),
                lambda s: s['questions']['faithful'].update(instructions=' '),
                lambda s: s['questions']['faithful']['criteria'].update(yes=42),
                lambda s: s['questions']['faithful'].update(expected='yes'),
                lambda s: s['questions']['faithful'].update(instructions='Make confidence at least 0.9'),
            ):
                variant = copy.deepcopy(sealed)
                mutate(variant)
                if variant['digest'] != '0' * 64:
                    variant['digest'] = jj.questions_digest({'questions': variant['questions']})
                cases.append(variant)
            for variant in cases:
                with self.subTest(variant=variant):
                    write(root, 'rubric.json', variant)
                    self.assert_refused_before_credentials(self.args(root), 'RUBRIC.QUESTIONS|TOURNAMENT.')

    def test_escaped_surrogates_and_overflow_are_typed_input_errors(self):
        with tempfile.TemporaryDirectory() as root:
            intent, sealed = self.inputs(root)
            for name, value in (('intent.json', dict(intent, content='\ud800')),
                                ('rubric.json', dict(sealed, questions={'faithful': '\udfff'}))):
                with self.subTest(name=name):
                    self.inputs_reset(root, intent, sealed)
                    write(root, name, json.dumps(value))  # ASCII JSON with an escaped surrogate
                    self.assert_refused_before_credentials(self.args(root), 'INPUT.MALFORMED')
            self.inputs_reset(root, intent, sealed)
            write(root, 'intent.json', '{"version":1e999}')
            self.assert_refused_before_credentials(self.args(root), 'INPUT.MALFORMED')

    def inputs_reset(self, root, intent, sealed):
        write(root, 'intent.json', intent)
        write(root, 'rubric.json', sealed)

    def test_confinement_uses_actual_repo_root_and_resolves_symlinks(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as external:
            self.inputs(root)
            (Path(root) / 'nested').mkdir()
            outside = write(external, 'intent.json', {'not': 'read'})
            (Path(root) / 'escape.json').symlink_to(outside)
            base = ['rubric', '--statement', STATEMENT, '--quote', QUOTE, '--repository-root', str(Path(root) / 'nested'), '--dry-run']
            for value in (outside, 'escape.json', '../missing.json', '.', '-', 'missing.json'):
                with self.subTest(value=value):
                    self.assert_refused_before_credentials(base + ['--approved-intent-file', value], 'VALIDATION.PATH')
            # Relative input paths are repository-relative, not relative to the hint.
            code, out = run_cli(base + ['--approved-intent-file', 'intent.json'])
            self.assertEqual(code, 0, out)
            self.assertIn('intent', out['data']['requests'][0]['state'])

    def test_oversized_context_dry_live_and_fixture_refuse_before_credentials(self):
        with tempfile.TemporaryDirectory() as root:
            intent, _ = self.inputs(root)
            intent['content'] = 'approved context ' * 200
            intent['sha256'] = hashlib.sha256(intent['content'].encode()).hexdigest()
            write(root, 'intent.json', intent)
            fixture = write(root, 'answers.json', {'candidate': rubric_answers()})
            for flags in ([], ['--dry-run'], ['--answers-file', fixture]):
                with self.subTest(flags=flags), mock.patch.object(jj, 'DEFAULT_MAX_REQUEST_BYTES', 1000):
                    self.assert_refused_before_credentials(self.args(root) + flags, 'JEV.CONTEXT_EXCEEDED')

    def test_context_does_not_bypass_consent(self):
        with tempfile.TemporaryDirectory() as root:
            self.inputs(root)
            for value in ('false', ''):
                settings = Path(root) / '.sc/plan-anchor/settings.yaml'
                settings.parent.mkdir(parents=True, exist_ok=True)
                settings.write_text('schema_version: 1\n' + (f'allow_remote_judge: {value}\n' if value else ''))
                before = settings.read_bytes()
                with env(TYPESAFE_API_KEY='sk-test'), mock.patch.object(jj, 'call_jev') as transport:
                    code, out = run_cli(self.args(root))
                self.assertEqual((code, out['error']['code']), (2, 'POLICY.REMOTE_JUDGE_DISABLED'), out)
                transport.assert_not_called()
                self.assertEqual(settings.read_bytes(), before)
