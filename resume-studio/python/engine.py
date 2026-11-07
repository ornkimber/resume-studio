"""Resume Studio JSON bridge. Word rendering remains in original_renderer.py.

One UTF-8 JSON request on stdin, one JSON response on stdout. No UI or server.
The CLI also accepts --input/--config/--lang/--output for ordinary batch use.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import traceback
from typing import Any

import yaml
import original_renderer as renderer

ENGINE_VERSION = "0.1.0"
MAX_SOURCE = 2_000_000


def issue(source: str, path: str, message: str, stage: str = "validation", **extra) -> dict:
    return dict(source=source, path=path, message=message, stage=stage, **extra)


def yaml_locations(text: str) -> dict:
    locations = {}
    try:
        root = yaml.compose(text)
        def walk(node, path, ancestors):
            if node is None or id(node) in ancestors:
                return
            locations[path] = dict(line=node.start_mark.line + 1, column=node.start_mark.column + 1)
            ancestors = ancestors | {id(node)}
            if isinstance(node, yaml.MappingNode):
                for key, value in node.value:
                    walk(value, f"{path}.{key.value}".lstrip("."), ancestors)
            elif isinstance(node, yaml.SequenceNode):
                for index, value in enumerate(node.value):
                    walk(value, f"{path}[{index}]", ancestors)
        walk(root, "", set())
    except (yaml.YAMLError, RecursionError):
        pass
    return locations


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str):
            raise yaml.constructor.ConstructorError(None, None, "Use text keys in resume and style files.", key_node.start_mark)
        if key in result:
            raise yaml.constructor.ConstructorError(None, None, f"Duplicate key: {key}", key_node.start_mark)
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def parse_source(text, format, source):
    if not isinstance(text, str) or len(text) > MAX_SOURCE:
        return None, [issue(source, "", "Source must be text smaller than 2 MB.", "parse")], {}
    if format not in ("yaml", "toml"):
        return None, [issue(source, "", "Choose YAML or TOML.", "parse")], {}
    try:
        data = yaml.load(text.lstrip("\ufeff"), Loader=UniqueKeyLoader) if format == "yaml" else tomllib.loads(text.lstrip("\ufeff"))
        if not isinstance(data, dict):
            return None, [issue(source, "", "The document must contain named fields.", "parse")], {}
        # Reject recursive aliases, dates, and other non-JSON data before crossing the bridge.
        json.dumps(data, allow_nan=False)
        return data, [], yaml_locations(text) if format == "yaml" else {}
    except (yaml.YAMLError, tomllib.TOMLDecodeError, ValueError, TypeError, RecursionError) as exc:
        extra = {}
        mark = getattr(exc, "problem_mark", None)
        if mark:
            extra = dict(line=mark.line + 1, column=mark.column + 1)
        else:
            match = re.search(r"at line (\d+), column (\d+)", str(exc))
            if match:
                extra = dict(line=int(match[1]), column=int(match[2]))
        message = getattr(exc, "problem", None) or str(exc)
        if isinstance(exc, TypeError):
            message = "Use strings, numbers, booleans, lists, and tables. Quote dates as text."
        return None, [issue(source, "", message, "parse", **extra)], {}


def validate_resume(data):
    errors = []
    def fail(path, message): errors.append(issue("resume", path, message))
    def text(obj, key, path, required=False):
        value = obj.get(key)
        if value is None and not required: return
        if not isinstance(value, str) or (required and not value.strip()):
            fail(f"{path}.{key}".lstrip("."), "Enter non-empty text." if required else "Expected text.")
        elif any(ord(c) < 32 and c not in "\t\n\r" for c in value):
            fail(f"{path}.{key}".lstrip("."), "Remove unsupported control characters.")
    def strings(obj, key, path):
        values = obj.get(key, [])
        if not isinstance(values, list):
            fail(f"{path}.{key}", "Expected a list of text values.")
        else:
            for i, value in enumerate(values): text({"value": value}, "value", f"{path}.{key}[{i}]", True)
    profile = data.get("profile")
    if not isinstance(profile, dict): fail("profile", "Add a profile table with a name.")
    else:
        text(profile, "name", "profile", True)
        text(profile, "title", "profile")
        strings(profile, "contacts", "profile")
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        fail("sections", "Add at least one resume section.")
        return errors
    for i, section in enumerate(sections):
        path = f"sections[{i}]"
        if not isinstance(section, dict):
            fail(path, "Expected a section table."); continue
        kind = section.get("type")
        if kind not in ("summary", "skills", "experience", "education", "bullets"):
            fail(path + ".type", "Choose summary, skills, experience, education, or bullets."); continue
        text(section, "title", path, True)
        if kind in ("summary", "bullets"):
            strings(section, "paragraphs" if kind == "summary" else "bullets", path)
        else:
            key = "groups" if kind == "skills" else "items"
            items = section.get(key, [])
            if not isinstance(items, list):
                fail(path + "." + key, "Expected a list of tables."); continue
            for j, item in enumerate(items):
                p = f"{path}.{key}[{j}]"
                if not isinstance(item, dict): fail(p, "Expected a table."); continue
                required = ["label", "text"] if kind == "skills" else ["role"] if kind == "experience" else ["school"]
                for field in required: text(item, field, p, True)
                for field in ("company", "organization", "location", "dates", "degree", "description"):
                    text(item, field, p)
                strings(item, "bullets", p)
    return errors


def validate_style(raw, lang):
    errors = []
    def fail(path, message): errors.append(issue("style", path, message))
    overrides = raw.get("language_overrides", {})
    if not isinstance(overrides, dict):
        return {}, [issue("style", "language_overrides", "Expected a table of language overrides.")]
    for language, override in overrides.items():
        if language not in ("en", "zh") or not isinstance(override, dict):
            fail(f"language_overrides.{language}", "Use an en or zh table.")
    if errors: return {}, errors
    cfg = renderer.effective_config(copy.deepcopy(raw), lang)
    missing = object()
    def get(path):
        current = cfg
        for key in path.split("."):
            if not isinstance(current, dict) or key not in current: return missing
            current = current[key]
        return current
    def number(path, low, high, required=True, integer=False):
        value = get(path)
        if value is missing and not required: return
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high or (integer and int(value) != value):
            fail(path, f"Enter {'a whole number' if integer else 'a number'} between {low} and {high}.")
    def choice(path, choices):
        value = get(path)
        if value is not missing and (not isinstance(value, str) or value not in choices):
            fail(path, "Choose " + ", ".join(choices) + ".")
    for path in ("page", "page.margins_cm", "fonts", "sizes_pt", "spacing", "colors"):
        if not isinstance(get(path), dict): fail(path, "Add this settings table.")
    for path in ("style_flags", "alignment", "bullet", "date_layout", "horizontal_rule"):
        if get(path) is not missing and not isinstance(get(path), dict): fail(path, "Expected a settings table.")
    for edge in ("top", "bottom", "left", "right"): number(f"page.margins_cm.{edge}", 0, 10)
    margins = get("page.margins_cm")
    if isinstance(margins, dict):
        for a, b, limit in (("left", "right", 20), ("top", "bottom", 28.7)):
            if all(type(margins.get(k)) in (int, float) for k in (a, b)) and margins[a] + margins[b] >= limit:
                fail("page.margins_cm", "Leave at least 1 cm of usable page width and height.")
    choice("page.size", ("A4", "a4"))
    for field in ("latin", "east_asia"):
        path = f"fonts.{lang}.{field}"
        if not isinstance(get(path), str) or not get(path).strip(): fail(path, "Enter a font family name.")
    for key in ("body", "name", "title", "contact", "section", "job_title", "company_date", "bullet", "skills"):
        number(f"sizes_pt.{key}", 1, 144)
    number("spacing.line_spacing", 0.5, 5)
    for key in ("paragraph_after_pt", "name_after_pt", "title_after_pt", "contact_after_pt", "section_before_pt", "section_after_pt", "job_before_pt", "job_after_pt", "company_after_pt", "bullet_after_pt"):
        number(f"spacing.{key}", 0, 200)
    for key in ("text", "section_heading", "job_title", "company_date", "horizontal_rule"):
        value = get("colors." + key)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", value): fail("colors." + key, 'Use six hexadecimal digits in quotes, e.g. "444444".')
    for path in ("include_internal_guide",):
        if get(path) is not missing and type(get(path)) is not bool: fail(path, "Use true or false.")
    flags = get("style_flags")
    if isinstance(flags, dict):
        for name, values in flags.items():
            if not isinstance(values, dict): fail("style_flags." + name, "Expected a table."); continue
            for flag, value in values.items():
                if type(value) is not bool: fail(f"style_flags.{name}.{flag}", "Use true or false.")
    alignment = get("alignment")
    if isinstance(alignment, dict):
        for key in alignment: choice("alignment." + key, ("left", "right", "center", "justify"))
    choice("date_layout.mode", ("right_tab", "inline"))
    choice("horizontal_rule.mode", ("skip", "subtle"))
    for path, low, high in (("bullet.left_twips", 0, 12000), ("bullet.hanging_twips", 0, 12000), ("horizontal_rule.size", 1, 96), ("horizontal_rule.space", 0, 31)):
        number(path, low, high, False, True)
    number("horizontal_rule.space_after_pt", 0, 200, False)
    for key in ("marker", "font"):
        value = get("bullet." + key)
        if value is not missing and (not isinstance(value, str) or not value.strip()): fail("bullet." + key, "Enter non-empty text.")
    return cfg, errors


def handle(request: dict) -> dict:
    errors = []
    lang = request.get("language", "en")
    if lang not in ("en", "zh"):
        return dict(ok=False, errors=[issue("resume", "language", "Choose en or zh.")])
    data, e, resume_locations = parse_source(request.get("resume", ""), request.get("resumeFormat", "yaml"), "resume")
    errors.extend(e)
    raw, e, style_locations = parse_source(request.get("style", ""), request.get("styleFormat", "yaml"), "style")
    errors.extend(e)
    if data is not None: errors.extend(validate_resume(data))
    cfg = {}
    if raw is not None:
        cfg, e = validate_style(raw, lang)
        errors.extend(e)
    for error in errors:
        locations = resume_locations if error["source"] == "resume" else style_locations
        path = error["path"]
        if error["source"] == "style" and f"language_overrides.{lang}.{path}" in locations:
            path = f"language_overrides.{lang}.{path}"
        while path and path not in locations:
            parent = re.sub(r"(\.[^.\[]+|\[\d+\])$", "", path)
            if parent == path: break
            path = parent
        if path in locations and "line" not in error: error.update(locations[path])
    if errors: return dict(ok=False, errors=errors)
    result = dict(ok=True, errors=[], engineVersion=ENGINE_VERSION, sectionCount=len(data["sections"]), name=data["profile"]["name"])
    if request.get("action", "validate") == "validate": return result
    if request.get("action") != "generate":
        return dict(ok=False, errors=[issue("app", "", "Unknown engine action.", "request")])
    with tempfile.TemporaryDirectory(prefix="resume-studio-") as directory:
        output = Path(directory) / "resume.docx"
        log = io.StringIO()
        handler = logging.StreamHandler(log)
        renderer.LOGGER.handlers.clear()
        renderer.LOGGER.addHandler(handler)
        renderer.LOGGER.setLevel(logging.INFO)
        try:
            document = renderer.Document()
            # The renderer already reads this setting; the legacy entry point omitted it.
            setattr(document, "_resume_cfg", cfg)
            renderer.configure_page(document, cfg)
            renderer.configure_styles(document, cfg, lang)
            if cfg.get("include_internal_guide", False): renderer.add_internal_guide(document, cfg, lang)
            renderer.render_resume(document, data, cfg, lang)
            document.save(output)
            renderer.validate_docx_bullets(output)
            content = output.read_bytes()
            result.update(docx=base64.b64encode(content).decode("ascii"), sha256=hashlib.sha256(content).hexdigest(), log=log.getvalue()[-16000:])
            return result
        except Exception as exc:
            return dict(ok=False, errors=[issue("app", "", str(exc), "generation")], details=traceback.format_exc(), log=log.getvalue()[-16000:])
        finally:
            renderer.LOGGER.removeHandler(handler)
            handler.close()


def main():
    parser = argparse.ArgumentParser(description="Resume Studio Python engine")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--lang", default="en", choices=("en", "zh"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.input:
            if not args.config or not args.output: parser.error("--input requires --config and --output")
            request = dict(action="generate", language=args.lang, resume=args.input.read_text(encoding="utf-8-sig"), style=args.config.read_text(encoding="utf-8-sig"), resumeFormat="toml" if args.input.suffix.lower() == ".toml" else "yaml", styleFormat="toml" if args.config.suffix.lower() == ".toml" else "yaml")
        else:
            request = json.loads(sys.stdin.buffer.read(MAX_SOURCE * 3).decode("utf-8-sig"))
        if not isinstance(request, dict): raise ValueError("Request must be a JSON object.")
        result = handle(request)
        if args.input and result["ok"]:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=args.output.parent, delete=False, suffix=".tmp") as temp:
                temporary = Path(temp.name)
                temp.write(base64.b64decode(result.pop("docx")))
            try: os.replace(temporary, args.output)
            finally: temporary.unlink(missing_ok=True)
            result["output"] = str(args.output.resolve())
    except Exception as exc:
        result = dict(ok=False, errors=[issue("app", "", str(exc), "request")], details=traceback.format_exc())
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False) + "\n").encode("utf-8"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
