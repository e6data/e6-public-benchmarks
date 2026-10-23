"""Validate wizard inputs using the same CSV parsers as the runner/UI."""
import argparse
from contextlib import contextmanager
from pathlib import Path
import subprocess
import tempfile

try:
    from .load_profile import read_arrivals_profile, read_concurrency_profile
    from .query_file_info import inspect
except ImportError:  # Direct script invocation
    from load_profile import read_arrivals_profile, read_concurrency_profile
    from query_file_info import inspect


@contextmanager
def local_input(source):
    if source.startswith('s3://'):
        with tempfile.TemporaryDirectory(prefix='benchmark-wizard-') as tmp:
            path = Path(tmp) / 'input.csv'
            subprocess.run(['aws', 's3', 'cp', source, str(path), '--only-show-errors'], check=True)
            yield path
    else:
        yield Path(source)


def summarize(kind, source):
    with local_input(source) as path:
        if kind == 'query':
            info = inspect(path)
            if not info['valid']:
                raise ValueError('; '.join(info['errors']))
            return f"Validated {info['rows']} queries"
        if kind == 'arrivals':
            rows = read_arrivals_profile(path)
            seconds = sum(row[2] for row in rows)
            total = sum((a + b) / 2 * duration for a, b, duration in rows)
            return f'Schedule duration: {seconds} seconds; approximately {total:g} submissions'
        rows = read_concurrency_profile(path)
        seconds = max(sum(row[1:]) for row in rows)
        return f'Schedule duration: {seconds} seconds; overlapping rows add workers'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=['query', 'arrivals', 'concurrency'])
    parser.add_argument('source')
    args = parser.parse_args()
    try:
        print(summarize(args.kind, args.source))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Input validation failed: {exc}\n')
