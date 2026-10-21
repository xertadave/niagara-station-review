"""Build a release zip – only if every regression test passes.

    python build.py            run the tests, then write dist/niagara-station-review-v<version>.zip
The version comes from station_review/server.py and must have an entry in CHANGELOG.md.
"""
import os
import re
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
v = re.search(r"VERSION = '([\d.]+)'", open(os.path.join(ROOT, 'station_review', 'server.py')).read()).group(1)
print(f'Station Review v{v}: running regression tests…')
r = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT)
if r.returncode:
    sys.exit('\nTESTS FAILED – no zip was built. Fix the failure (or the regression) first.')
os.makedirs(os.path.join(ROOT, 'dist'), exist_ok=True)
out = os.path.join(ROOT, 'dist', f'niagara-station-review-v{v}.zip')
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in ('__pycache__', 'data', 'dist')]   # .git is included: the zip carries the history
        for f in files:
            p = os.path.join(d, f)
            z.write(p, os.path.join('niagara-station-review', os.path.relpath(p, ROOT)))
print(f'\nAll tests passed – built {out}')
