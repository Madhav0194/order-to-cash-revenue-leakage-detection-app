import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATOR = ROOT / 'src' / 'generate_full_dataset.py'
VALIDATOR = ROOT / 'src' / 'validate_full_dataset.py'
MANIFEST = ROOT / 'data' / 'full' / 'manifest.json'


def run(script):
    subprocess.run([sys.executable, str(script)], cwd=ROOT, check=True)


def snapshot():
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    return {name: (entry['rows'], entry['sha256']) for name, entry in manifest['files'].items()}


def main():
    print('REPRODUCIBILITY RUN 1', flush=True)
    run(GENERATOR)
    run(VALIDATOR)
    first = snapshot()
    print('REPRODUCIBILITY RUN 2', flush=True)
    run(GENERATOR)
    run(VALIDATOR)
    second = snapshot()
    if first != second:
        differing = sorted(set(first) | set(second))
        differing = [name for name in differing if first.get(name) != second.get(name)]
        raise AssertionError('Non-deterministic files: ' + ', '.join(differing))
    print(f'REPRODUCIBILITY PASSED: {len(first)} files identical across both runs')
    print('Fixed seed: 20261022')


if __name__ == '__main__':
    main()
