"""Live variants of the existing judge, batch-order and auth-error cases; no answer stubs."""
from functools import partial
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/sc-plan-anchor'))
from layout_support import SCRIPTS, TEST_TRACKER
from test_jev_judge import anchor, record, run_cli, write
import test_tournament as tournament_cases
import jev_judge as jj

if os.environ.get('PLAN_ANCHOR_LIVE_INTEGRATION') != '1':
    raise pytest.UsageError('select the real-provider suite with scripts/integration.py')


@pytest.fixture
def live(tmp_path, monkeypatch, record_property):
    assert importlib.metadata.version('sc-decidr') == os.environ['PLAN_ANCHOR_INTEGRATION_WHEEL_VERSION']
    monkeypatch.chdir(tmp_path)
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True, timeout=30)
    subprocess.run([sys.executable, str(SCRIPTS / 'plan_anchor_settings.py'), 'set', 'allow_remote_judge', 'true'],
                   check=True, capture_output=True, text=True, timeout=30)
    config = tmp_path / 'wheel-config'
    config.mkdir()
    (config / 'default.json').write_text(json.dumps({'max_sends': 1, 'log_root': str(tmp_path / 'logs')}))
    # Configure log isolation only; both partials execute the real installed wheel.
    monkeypatch.setattr(jj.decidr_client, 'call', partial(jj.decidr_client.call, config_dir=str(config)))
    monkeypatch.setattr(jj.decidr_client, 'call_batch', partial(jj.decidr_client.call_batch, config_dir=str(config)))
    record_property('provider', 'typesafe')
    record_property('model', 'jev-latest')
    record_property('mode', 'live')
    record_property('tracker', TEST_TRACKER)
    return tmp_path


def test_judge_writes_real_run_artifact(live, record_property):
    # Same inputs and artifact assertions as JudgeFixtureTests, without --answers-file.
    anchors = write(str(live), 'anchors.json', record(anchor()))
    item = write(str(live), 'item.txt', 'Sprint 2 copies the legacy runtime crates into crates/runtime.')
    code, output = run_cli(['judge', '--anchors', anchors, '--gate', 'plan', '--item-id', 'live-item',
                            '--item-file', item, '--anchor', 'ANC-001', '--run-dir', str(live / 'runs'),
                            '--timeout', '120', '--repository-root', str(live)])
    assert code == 0 and output['success'], output
    run = output['data']
    assert run['fixture'] is False
    assert run['model_answered'].startswith('jev')
    assert [row['anchor_id'] for row in run['results']] == ['ANC-001']
    assert run['results'][0]['verdict'] != 'error'
    saved = json.loads(Path(run['run_path']).read_text())
    assert saved['results'] == run['results']
    record_property('result', 'real judge artifact; verdict=' + run['results'][0]['verdict'])


def test_batch_preserves_correlation_and_durable_log(live, record_property):
    # Reuse BatchTests' request/candidate inputs, with real answers instead of FIXTURE.
    requests = write(str(live), 'requests.jsonl', tournament_cases.jsonl(tournament_cases.BatchTests.LINES))
    code, output = run_cli(['batch', '--input', requests, '--run-dir', str(live / 'batch-runs'),
                            '--run-name', 'live', '--request-prefix', 'integration', '--repeat', '1',
                            '--model', 'jev-latest', '--max-workers', '2', '--timeout', '120',
                            '--repository-root', str(live)])
    assert code == 0, output
    rows = [json.loads(line) for line in output.splitlines()]
    assert [row['request_id'] for row in rows] == ['integration/s1/ANC-001/cur/r1',
                                                 'integration/s1/ANC-001/alt/r1',
                                                 'integration/s3/ANC-001/cur/r1']
    assert all(row['ok'] and row['verdict'] != 'error' for row in rows)
    saved = [json.loads(line) for line in (live / 'batch-runs/tournament-live.jsonl').read_text().splitlines()]
    assert saved == rows
    record_property('result', 'three real results; input correlation/order equals durable JSONL')


def test_invalid_key_maps_auth_and_withholds_body(live, monkeypatch, record_property):
    key = 'invalid-plan-anchor-integration-key-0001'
    monkeypatch.setenv(os.environ['PLAN_ANCHOR_INTEGRATION_KEY_VARIABLE'], key)
    body = {'model': 'jev-latest', 'state': jj.build_state(anchor(),
            {'id': 's1', 'title': 'Sprint', 'text': 'Copy the legacy runtime crates.'}),
            'questions': tournament_cases.PLAN_QS['questions']}
    outcome = jj.call_jev(body, 120)
    assert isinstance(outcome, jj.Err)
    assert outcome.error.code == 'AUTH.CREDENTIALS' and outcome.error.status == 401
    assert 'withheld' in outcome.error.message
    assert key not in json.dumps(outcome.error.to_json())
    assert all(key not in path.read_text() for path in live.rglob('*.jsonl'))
    record_property('result', 'HTTP401 maps to AUTH.CREDENTIALS; body withheld; key redacted')
