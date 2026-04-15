import subprocess, json, shutil

changed = subprocess.run(['git', 'diff', '--name-only'], capture_output=True, text=True).stdout
has_py = any(f.endswith('.py') for f in changed.splitlines())
has_jsx = any(f.endswith(('.jsx', '.js')) and 'frontend-v2' in f for f in changed.splitlines())

msgs = []

if has_py:
    r = subprocess.run(
        ['python', '-m', 'pytest', 'tests/unit/', '-q', '--tb=line', '--no-header', '-x'],
        capture_output=True, text=True, timeout=60
    )
    msgs.append(f"pytest: {'PASS' if r.returncode == 0 else 'FAIL'}")
else:
    msgs.append("pytest: skipped")

if has_jsx:
    npm_cmd = shutil.which('npm') or 'npm'
    r = subprocess.run(
        [npm_cmd, '--prefix', 'frontend-v2', 'run', 'build'],
        capture_output=True, text=True, timeout=60, shell=(not shutil.which('npm'))
    )
    msgs.append(f"vite build: {'PASS' if r.returncode == 0 else 'FAIL'}")
else:
    msgs.append("vite build: skipped")

print(json.dumps({"systemMessage": f"[Stop check] {' | '.join(msgs)}"}))
