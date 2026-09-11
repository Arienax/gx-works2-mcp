"""Package the Windows test binary, then smoke-test the extracted ZIP itself."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ('legacy', 'minimal', 'manual', 'examples', 'combined', 'adaptive')


def run(args, *, env=None, timeout=120):
    result = subprocess.run([str(x) for x in args], cwd=ROOT, env=env, text=True,
                            encoding='utf-8', errors='replace', capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Command failed: ' + str(args[0]) + '\n' + result.stdout + '\n' + result.stderr)
    return result.stdout


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    os.chdir(ROOT)
    if sys.platform != 'win32':
        raise RuntimeError('This packaging check must execute on Windows')
    package = ROOT / 'dist/GXWorks-Agent-Web'
    assets = ROOT / 'release-assets'
    assets.mkdir(exist_ok=True)
    exe = package / 'GXWorks-Agent-Web.exe'
    with exe.open('rb') as binary:
        assert binary.read(2) == b'MZ'
        binary.seek(0x3c)
        binary.seek(struct.unpack('<I', binary.read(4))[0])
        assert binary.read(4) == b'PE\0\0'
        assert struct.unpack('<H', binary.read(2))[0] == 0x8664
    from PyInstaller.archive.readers import ZlibArchiveReader
    toc = ZlibArchiveReader(str(ROOT / 'build/web/PYZ-00.pyz')).toc
    assert 'prompt_context_policy' in toc, 'Context module missing from frozen executable'
    for name in ('START_CONTEXT_TEST.cmd', 'start-adaptive.cmd', 'start-legacy.cmd', 'scripts/start_context_test.ps1'):
        source = ROOT / name
        target = package / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding='utf-8-sig').replace('\r\n', '\n')
        encoding = 'utf-8-sig' if name.endswith('.ps1') else 'utf-8'
        target.write_bytes(text.replace('\n', '\r\n').encode(encoding))
    shutil.copy2(ROOT / 'CONTEXT_TEST_README.zh-CN.md', package / 'CONTEXT_TEST_README.zh-CN.md')
    for name in ('source-manifest.json', 'context-changes.patch'):
        shutil.copy2(ROOT / 'build/context-test' / name, package / name)
        shutil.copy2(ROOT / 'build/context-test' / name, assets / name)
    policy_checks = []
    for name in POLICIES:
        env = dict(os.environ, GXWORKS_CONTEXT_POLICY=name)
        result = json.loads(run([exe, '--context-policy-info'], env=env))
        assert result['context_policy'] == {'name': name, 'version': 1}
        assert result['server_started'] is False and result['model_called'] is False
        expected_manuals = 'automatic' if name in ('legacy', 'manual', 'combined') else ('adaptive' if name == 'adaptive' else 'off')
        assert result['automatic_manuals'] == expected_manuals
        assert result['control_examples'] == (name in ('legacy', 'examples', 'combined'))
        policy_checks.append(result)
    clean_env = dict(os.environ)
    clean_env.pop('GXWORKS_CONTEXT_POLICY', None)
    assert json.loads(run([exe, '--context-policy-info'], env=clean_env))['context_policy']['name'] == 'legacy'
    launcher_checks = []
    for name in ('adaptive', 'legacy'):
        raw = run(['powershell.exe', '-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File',
                   package / 'scripts/start_context_test.ps1', '-Policy', name, '-ValidateOnly', '-NoBrowser'])
        values = [json.loads(line) for line in raw.splitlines() if line.strip().startswith('{')]
        assert values and values[-1]['validated'] is True and values[-1]['service_started'] is False
        assert values[-1]['workspace'].replace('/', '\\').lower().endswith('contextpolicytests\\refresh-c6bc6ef\\' + name)
        assert not Path(values[-1]['workspace']).exists(), 'ValidateOnly created a workspace'
        launcher_checks.append(values[-1])
    for forbidden in ('config.json', '.env', '.git', '.venv', 'node_modules', 'workspace', 'workspaces'):
        assert not (package / forbidden).exists(), 'Private/development file in package: ' + forbidden
    manifest = json.loads((package / 'source-manifest.json').read_text(encoding='utf-8'))
    info = {**manifest, 'build_kind': 'context-policy-test-preview',
            'repository': os.environ.get('GITHUB_REPOSITORY'),
            'workflow_run': 'https://github.com/' + os.environ['GITHUB_REPOSITORY'] + '/actions/runs/' + os.environ['GITHUB_RUN_ID'],
            'source_ref': os.environ.get('GITHUB_REF'), 'python': platform.python_version(),
            'build_os': platform.platform(), 'web_executable_architecture': 'x64', 'gateway_architecture': 'x86',
            'exe_sha256': sha(exe), 'code_signed': False, 'default_source_policy': 'legacy',
            'recommended_test_launcher': 'start-adaptive.cmd',
            'live_model_acceptance_performed': False, 'native_gx_simulator_plc_acceptance_performed': False,
            'python_packages': json.loads(run([sys.executable, '-m', 'pip', 'list', '--format=json']))}
    save(package / 'build-info.json', info)
    shutil.copy2(package / 'build-info.json', assets / 'build-info.json')
    name = 'GXWorks-Agent-Web-context-c6bc6ef-Windows-x64'
    zip_path = Path(shutil.make_archive(str(assets / name), 'zip', package.parent, package.name))
    extracted_checks = []
    with tempfile.TemporaryDirectory(prefix='gx-context-unzip-') as temporary:
        shutil.unpack_archive(str(zip_path), temporary, 'zip')
        extracted = Path(temporary) / package.name
        assert sha(extracted / exe.name) == info['exe_sha256']
        for policy in ('legacy', 'adaptive'):
            env = dict(os.environ, GXWORKS_CONTEXT_POLICY=policy)
            result = json.loads(run([sys.executable, 'scripts/web_package_smoke.py', '--package-dir', extracted,
                                     '--archive', ROOT / 'build/web/PYZ-00.pyz'], env=env, timeout=180))
            assert result.get('ok') is True and result.get('qt_modules_excluded') is True
            extracted_checks.append({'policy': policy, 'result': result})
    proof = {'ok': True, 'tested_zip': zip_path.name, 'zip_sha256': sha(zip_path),
             'policy_module_bundled': True, 'compiled_policy_checks': policy_checks,
             'launcher_checks': launcher_checks, 'extracted_zip_smoke': extracted_checks,
             'live_model_called': False, 'gx_called': False, 'physical_plc_called': False}
    save(assets / 'context-package-smoke.json', proof)
    # Preserve the exact prepared source as a separate audit artifact, not inside the install ZIP.
    import zipfile
    with zipfile.ZipFile(assets / 'context-source-changes.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        names = subprocess.check_output(['git', 'diff', '--name-only', manifest['base_commit']], text=True).splitlines()
        for path_name in names:
            path = ROOT / path_name
            if path.is_file() and not path.is_symlink():
                archive.write(path, path_name)
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
