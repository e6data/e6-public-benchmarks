"""Offline documentation contracts: no installs, engine requests or AWS operations."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from urllib.parse import unquote

from utilities.load_profile import read_profile


REPO = Path(__file__).resolve().parents[4]
FRAMEWORK = Path(__file__).resolve().parents[2]


def documents():
    paths = subprocess.check_output(
        ['git', 'ls-files', '*.md'], cwd=REPO, text=True).splitlines()
    return [REPO / name for name in paths if '/apache-jmeter-' not in name]


def anchors(text):
    return {re.sub(r'[^\w\- ]', '', heading.lower()).replace(' ', '-')
            for heading in re.findall(r'^#+\s+(.+)$', text, re.M)}


class DocumentationTests(unittest.TestCase):
    def test_local_markdown_links_and_anchors(self):
        for path in documents():
            for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
                if '://' in target or target.startswith('mailto:'):
                    continue
                file, _, anchor = unquote(target).partition('#')
                dest = path.parent / file if file else path
                with self.subTest(document=str(path.relative_to(REPO)), target=target):
                    self.assertTrue(dest.exists(), 'Missing local link target')
                    if anchor and dest.suffix == '.md':
                        self.assertIn(anchor, anchors(dest.read_text()))

    def test_shell_examples_parse_without_placeholder_rewriting(self):
        for path in documents():
            blocks = re.findall(r'```(?:bash|sh)\n(.*?)```', path.read_text(), re.S)
            for index, block in enumerate(blocks):
                with self.subTest(document=str(path.relative_to(REPO)), block=index):
                    result = subprocess.run(['bash', '-n'], input=block,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_script_and_plan_references_exist(self):
        for path in documents():
            text = path.read_text()
            references = re.findall(r'(?:\./|\butilities/)[\w/.-]+\.(?:sh|py)\b', text)
            for name in references:
                # Root README directs users into the framework before its examples.
                with self.subTest(document=str(path.relative_to(REPO)), script=name):
                    self.assertTrue((FRAMEWORK / name).is_file(), name)
            for name in re.findall(r'\bTest-Plan-[\w.-]+\.jmx\b', text):
                with self.subTest(document=str(path.relative_to(REPO)), plan=name):
                    self.assertTrue((FRAMEWORK / 'Test-Plans' / name).is_file(), name)

    def test_profile_and_warmup_guidance(self):
        readme = (FRAMEWORK / 'README.md').read_text()
        for line in readme.splitlines():
            if line.startswith('| `Test-Plan-') and 'load-profile' in line and 'http-endpoint' not in line:
                self.assertIn('LOAD_PROFILE', line)
                self.assertNotIn('HOLD_PERIOD', line)
        settings = (FRAMEWORK / 'config/README.md').read_text()
        self.assertIn('Warm-up explicitly disables Query History capture', settings)
        self.assertNotIn('warm-up/measured', settings)
        self.assertNotIn('always runs for the full', readme)

    def test_documented_profile_csvs_use_the_runtime_parser(self):
        for path in documents():
            for block in re.findall(r'```csv\n(.*?)```', path.read_text(), re.S):
                if not block.startswith(('StartValue,', 'Threads,')):
                    continue
                with self.subTest(document=str(path.relative_to(REPO))), tempfile.TemporaryDirectory() as tmp:
                    profile = Path(tmp) / 'profile.csv'
                    profile.write_text(block)
                    kind, rows = read_profile(profile)
                    self.assertIn(kind, {'arrivals', 'concurrency'})
                    self.assertTrue(rows)

    def test_terminal_guidance_references_existing_scripts(self):
        for folder in (FRAMEWORK, FRAMEWORK / 'utilities'):
            for script in folder.glob('*.sh'):
                for line in script.read_text().splitlines():
                    if not line.lstrip().startswith('echo '):
                        continue
                    for name in re.findall(r'\./[\w/.-]+\.(?:sh|py)\b', line):
                        with self.subTest(script=script.name, reference=name):
                            self.assertTrue((FRAMEWORK / name).is_file())
