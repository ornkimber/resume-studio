import base64
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python'))
import engine
import original_renderer
import yaml


class EngineTests(unittest.TestCase):
    def request(self, lang='en', **kwargs):
        return dict(action='generate', language=lang, resume=(ROOT / f'fixtures/resume_{lang}.yaml').read_text(encoding='utf-8'), style=(ROOT / 'fixtures/style_config.yaml').read_text(encoding='utf-8'), resumeFormat='yaml', styleFormat='yaml', **kwargs)

    def test_word_xml_matches_original_for_both_languages(self):
        for lang in ('en', 'zh'):
            with self.subTest(lang=lang), tempfile.TemporaryDirectory() as folder:
                baseline = Path(folder) / 'baseline.docx'
                original_renderer.generate(ROOT / f'fixtures/resume_{lang}.yaml', ROOT / 'fixtures/style_config.yaml', lang, baseline)
                for handler in original_renderer.LOGGER.handlers[:]:
                    original_renderer.LOGGER.removeHandler(handler); handler.close()
                response = engine.handle(self.request(lang))
                self.assertTrue(response['ok'], response)
                with ZipFile(baseline) as old, ZipFile(io.BytesIO(base64.b64decode(response['docx']))) as new:
                    for part in ('word/document.xml', 'word/styles.xml', 'word/numbering.xml'):
                        self.assertEqual(old.read(part), new.read(part), f'{lang}: {part}')

    def test_toml_input_generates_native_docx(self):
        request = self.request()
        request['resumeFormat'] = 'toml'
        request['resume'] = '[profile]\nname="Example 中文"\n[[sections]]\ntype="bullets"\ntitle="Skills"\nbullets=["**Python:** development"]'
        response = engine.handle(request)
        self.assertTrue(response['ok'], response)
        with ZipFile(io.BytesIO(base64.b64decode(response['docx']))) as doc:
            self.assertIn('Example 中文', doc.read('word/document.xml').decode())
            self.assertIn(b'<w:numPr>', doc.read('word/document.xml'))

    def test_invalid_yaml_includes_location(self):
        request = self.request(); request['resume'] = 'profile: [\n'
        response = engine.handle(request)
        self.assertFalse(response['ok']); self.assertEqual(response['errors'][0]['stage'], 'parse')
        self.assertIn('line', response['errors'][0])

    def test_invalid_toml_is_actionable(self):
        request = self.request(); request.update(resumeFormat='toml', resume='[profile\nname="X"')
        response = engine.handle(request)
        self.assertFalse(response['ok']); self.assertEqual(response['errors'][0]['source'], 'resume')

    def test_missing_and_wrong_fields_are_collected(self):
        request = self.request(); request['resume'] = 'profile: {}\nsections:\n  - type: experience\n    title: Jobs\n    items:\n      - role: 15\n        bullets: invalid\n'
        response = engine.handle(request)
        self.assertFalse(response['ok'])
        self.assertGreaterEqual(len(response['errors']), 3)
        self.assertTrue(any(e['path'] == 'sections[0].items[0].role' for e in response['errors']))

    def test_invalid_styles_never_reach_renderer(self):
        for style in ({}, {'page': []}, {'language_overrides': []}):
            request = self.request(); request['style'] = yaml.safe_dump(style)
            response = engine.handle(request)
            self.assertFalse(response['ok']); self.assertTrue(response['errors'])

    def test_language_overrides_do_not_modify_shared_config(self):
        config = yaml.safe_load(self.request()['style']); before = copy.deepcopy(config)
        chinese, errors = engine.validate_style(config, 'zh')
        english, errors2 = engine.validate_style(config, 'en')
        self.assertEqual(config, before); self.assertFalse(errors + errors2)
        self.assertNotEqual(chinese['spacing']['line_spacing'], english['spacing']['line_spacing'])

    def test_custom_bullet_settings_reach_existing_renderer(self):
        request = self.request(); style = yaml.safe_load(request['style']); style['bullet']['marker'] = '*'
        style['bullet']['left_twips'] = 700; request['style'] = yaml.safe_dump(style)
        response = engine.handle(request); self.assertTrue(response['ok'], response)
        with ZipFile(io.BytesIO(base64.b64decode(response['docx']))) as doc:
            self.assertIn(b'<w:lvlText w:val="*"', doc.read('word/numbering.xml'))
            self.assertIn(b'w:left="700"', doc.read('word/numbering.xml'))

    def test_duplicate_keys_and_recursive_aliases_rejected(self):
        for source in ('profile: {}\nprofile: {}', 'profile: &p {name: *p}'):
            request = self.request(); request['resume'] = source
            self.assertFalse(engine.handle(request)['ok'])

    def test_cli_creates_output_folder_and_reports_json(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'new/subfolder/简历.docx'
            process = subprocess.run([sys.executable, str(ROOT / 'python/engine.py'), '--input', str(ROOT / 'fixtures/resume_zh.yaml'), '--config', str(ROOT / 'fixtures/style_config.yaml'), '--lang', 'zh', '--output', str(output)], capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(json.loads(process.stdout)['ok']); self.assertTrue(output.exists())

    def test_stdio_error_has_nonzero_exit_and_valid_json(self):
        process = subprocess.run([sys.executable, str(ROOT / 'python/engine.py')], input=b'{bad', capture_output=True)
        self.assertNotEqual(process.returncode, 0); self.assertFalse(json.loads(process.stdout)['ok'])


if __name__ == '__main__': unittest.main()
