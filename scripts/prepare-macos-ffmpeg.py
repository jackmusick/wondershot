#!/usr/bin/env python3
"""Stage a relocatable FFmpeg and its non-system libraries for the macOS app."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'src-tauri/binaries/macos'

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def dependencies(path):
    return [line.strip().split(' (compatibility')[0] for line in run('otool', '-L', str(path)).splitlines()[1:]]

def stage():
    source = Path(os.environ.get('WONDERSHOT_FFMPEG', shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg')).resolve()
    if not source.is_file():
        raise SystemExit('FFmpeg is required to build Wondershot. Install it with brew install ffmpeg.')
    if STAGE.exists():
        shutil.rmtree(STAGE)
    libs = STAGE / 'libs'
    libs.mkdir(parents=True)
    copied = {}

    def copy(path, executable=False):
        path = path.resolve()
        if path in copied:
            return copied[path]
        name = 'ffmpeg' if executable else path.name
        if not executable and any(p.name == name for p in copied.values()):
            name = hashlib.sha256(str(path).encode()).hexdigest()[:8] + '-' + name
        dest = STAGE / name if executable else libs / name
        shutil.copy2(path, dest)
        dest.chmod(0o755)
        copied[path] = dest
        if not executable:
            subprocess.run(['install_name_tool', '-id', '@rpath/' + name, str(dest)], check=True)
        for dep in dependencies(path):
            if dep.startswith(('/System/', '/usr/lib/')):
                continue
            resolved = Path(dep.replace('@loader_path', str(path.parent)))
            if dep.startswith('@rpath/'):
                # Homebrew libraries normally use absolute install names.
                # Fail rather than produce an app with unresolved dependencies.
                raise RuntimeError(f'Cannot stage unresolved dependency {dep} in {path}')
            if resolved.resolve() == path:
                continue
            if not resolved.is_file():
                raise RuntimeError(f'Missing dependency {dep} in {path}')
            target = copy(resolved)
            load = ('@executable_path/../Resources/libs/' if executable else '@loader_path/') + target.name
            # The resource executable lives in Resources, so its own directory
            # is Resources (not Contents/MacOS).
            if executable:
                load = '@executable_path/libs/' + target.name
            subprocess.run(['install_name_tool', '-change', dep, load, str(dest)], check=True)
        subprocess.run(['codesign', '--force', '--sign', '-', str(dest)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return dest

    binary = copy(source, True)
    (STAGE / 'FFMPEG-LICENSE.txt').write_text(run(str(source), '-L') + '\n')
    subprocess.run([str(binary), '-version'], check=True, stdout=subprocess.DEVNULL)
    print(f'Staged FFmpeg with {len(copied) - 1} relocatable libraries')

if __name__ == '__main__':
    stage()
