#!/usr/bin/env python3
"""Run plan-anchor's real judge/batch cases against an installed sc-decidr wheel."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--venv', required=True, type=Path)
    parser.add_argument('--env-file', required=True, type=Path, help='Consumed and deleted, including on failure')
    parser.add_argument('--key-variable', required=True, help='TypeSafe credential variable name from the sc-agent export')
    parser.add_argument('--sc-agent-source', required=True, type=Path, help='sc-agent checkout providing the shared report renderer')
    parser.add_argument('--source-sha', required=True, help='plan-anchor revision under test')
    parser.add_argument('--pin-tag', required=True, help='Published tag or explicit source-build label')
    parser.add_argument('--wheel-version', help='Distribution version for a source-build label')
    parser.add_argument('--pin-sha', required=True, help='sc-agent wheel source revision')
    parser.add_argument('--platform', required=True, choices=('macos', 'colima'))
    parser.add_argument('--results', required=True, type=Path)
    args = parser.parse_args()
    try:
        if not args.pin_tag.startswith('prerelease/v') and not args.wheel_version:
            parser.error('--wheel-version is required for a source-build label')
        source = args.sc_agent_source.resolve()
        renderer = source / 'templates/integration-report/render.py'
        if not renderer.is_file():
            parser.error(f'missing sc-agent report renderer: {renderer}')
        variable = args.key_variable
        values = dict(line.split('=', 1) for line in args.env_file.read_text().splitlines()
                      if line.strip() and not line.lstrip().startswith('#'))
        if not values.get(variable):
            raise RuntimeError('TypeSafe key is required; no integration tests run')
        env = {k: v for k, v in os.environ.items() if k != variable and not k.endswith('_API_KEY') and not k.startswith('SC_AGENT__')}
        env.update({variable: values[variable], 'PLAN_ANCHOR_LIVE_INTEGRATION': '1',
                    'PLAN_ANCHOR_INTEGRATION_KEY_VARIABLE': variable,
                    'PLAN_ANCHOR_INTEGRATION_WHEEL_VERSION': args.wheel_version or args.pin_tag.removeprefix('prerelease/v'),
                    # REQ-SAG-0004 requires each decision to carry a caller-supplied project.
                    # Keep the live suite's calls in the plan-anchor project through sc-agent's
                    # documented project-resolution path instead of changing the wheel contract.
                    'SC_PROJECT': 'plan-anchor',
                    'SC_AGENT_TEST_TRAP_PLATFORM_KEYRING': '1'})
        python = args.venv.resolve() / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        results = args.results.resolve()
        results.mkdir(parents=True, exist_ok=True)
        junit = results / f'{args.platform}.xml'
        test_file = ROOT / 'tests/integration/test_installed_wheel.py'
        cases = [f'{test_file}::{name}' for name in ('test_judge_writes_real_run_artifact',
                 'test_batch_preserves_correlation_and_durable_log', 'test_invalid_key_maps_auth_and_withholds_body')]
        with tempfile.TemporaryDirectory(prefix='plan-anchor-integration-') as scratch:
            completed = subprocess.run([str(python), '-m', 'pytest', *cases, '-v',
                                        '-o', 'junit_family=legacy', f'--junitxml={junit}'],
                                       env=env, cwd=scratch, stdin=subprocess.DEVNULL, timeout=600)
        subprocess.run([str(python), str(renderer), str(junit),
                        '--platform', args.platform, '--mode', 'live', '--source-revision', args.source_sha,
                        '--wheel-revision', f'{args.pin_tag}@{args.pin_sha}', '--output',
                        str(ROOT / f'site/reports/integration/{args.platform}.xhtml'),
                        '--reports-dir', str(ROOT / 'site/reports'),
                        '--title', 'Plan-anchor integration report'], check=True,
                       stdin=subprocess.DEVNULL, timeout=60)
        return completed.returncode
    except subprocess.TimeoutExpired as exc:
        print(f"integration: {args.platform} child timed out after {exc.timeout} seconds", file=sys.stderr)
        return 2
    finally:
        args.env_file.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
