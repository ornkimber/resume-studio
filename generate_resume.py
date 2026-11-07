#!/usr/bin/env python
"""Generate a consistently formatted Word resume from structured YAML.

Edit style_config.yaml to change fonts, margins, spacing, and colors.
Edit resume_en.yaml / resume_zh.yaml to change resume content.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

try:
    import yaml
except ImportError as exc:
    raise SystemExit("Missing dependency: PyYAML. Install with: pip install PyYAML") from exc

try:
    from docx import Document
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
except ImportError as exc:
    raise SystemExit("Missing dependency: python-docx. Install with: pip install python-docx") from exc


REQUIRED_STYLES = {
    "ResumeName",
    "ResumeTitle",
    "ResumeContact",
    "ResumeSection",
    "ResumeJobTitle",
    "ResumeCompanyDate",
    "ResumeBullet",
    "ResumeNormal",
}

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
LOGGER = logging.getLogger("resume_generator")
BULLET_NUM_ATTR = "_resume_bullet_num_id"


def load_yaml(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} file not found: {path}")
    with path.open("r", encoding="utf-8-sig") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{label} root must be a YAML mapping.")
    return data


def setup_logging(log_path: Path) -> None:
    LOGGER.handlers.clear()
    LOGGER.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)


def one_line(value: Any, limit: int = 160) -> str:
    text = str(value).replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def pt(value: float) -> Pt:
    return Pt(float(value))


def hex_color(value: str) -> RGBColor:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected 6-digit hex color, got: {value}")
    return RGBColor(int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def cfg_get(cfg: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = cfg
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def paragraph_alignment(value: str | None):
    if not value:
        return None
    normalized = value.strip().lower()
    return {
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    }.get(normalized)


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def effective_config(raw_cfg: dict[str, Any], lang: str) -> dict[str, Any]:
    cfg = deep_merge({}, raw_cfg)
    overrides = cfg.get("language_overrides", {}).get(lang, {})
    if overrides:
        deep_merge(cfg, overrides)
    cfg.pop("language_overrides", None)
    return cfg


def ensure_style(document: Document, name: str):
    if name in document.styles:
        return document.styles[name]
    return document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)


def clear_numbering(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is not None:
        p_pr.remove(num_pr)
    paragraph.paragraph_format.left_indent = Cm(0)
    paragraph.paragraph_format.first_line_indent = Cm(0)


def next_numbering_id(elements, attr_name: str) -> int:
    values: list[int] = []
    for element in elements:
        value = element.get(qn(attr_name))
        if value is not None and value.isdigit():
            values.append(int(value))
    return max(values, default=0) + 1


def ensure_bullet_numbering(document: Document) -> int:
    """Create one native Word bullet numbering definition per document."""
    existing = getattr(document, BULLET_NUM_ATTR, None)
    if existing is not None:
        return int(existing)

    numbering = document.part.numbering_part.element
    abstract_id = next_numbering_id(numbering.findall(qn("w:abstractNum")), "w:abstractNumId")
    num_id = next_numbering_id(numbering.findall(qn("w:num")), "w:numId")

    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))

    multi_level = OxmlElement("w:multiLevelType")
    multi_level.set(qn("w:val"), "singleLevel")
    abstract.append(multi_level)

    lvl = OxmlElement("w:lvl")
    lvl.set(qn("w:ilvl"), "0")

    start = OxmlElement("w:start")
    start.set(qn("w:val"), "1")
    lvl.append(start)

    num_fmt = OxmlElement("w:numFmt")
    num_fmt.set(qn("w:val"), "bullet")
    lvl.append(num_fmt)

    lvl_text = OxmlElement("w:lvlText")
    cfg = getattr(document, "_resume_cfg", {})
    lvl_text.set(qn("w:val"), str(cfg_get(cfg, "bullet.marker", "-")))
    lvl.append(lvl_text)

    lvl_jc = OxmlElement("w:lvlJc")
    lvl_jc.set(qn("w:val"), "left")
    lvl.append(lvl_jc)

    p_pr = OxmlElement("w:pPr")
    ind = OxmlElement("w:ind")
    ind.set(qn("w:left"), str(cfg_get(cfg, "bullet.left_twips", 620)))
    ind.set(qn("w:hanging"), str(cfg_get(cfg, "bullet.hanging_twips", 440)))
    p_pr.append(ind)
    lvl.append(p_pr)

    r_pr = OxmlElement("w:rPr")
    r_fonts = OxmlElement("w:rFonts")
    bullet_font = str(cfg_get(cfg, "bullet.font", "Aptos"))
    r_fonts.set(qn("w:ascii"), bullet_font)
    r_fonts.set(qn("w:hAnsi"), bullet_font)
    r_fonts.set(qn("w:hint"), "default")
    r_pr.append(r_fonts)
    lvl.append(r_pr)

    abstract.append(lvl)
    numbering.append(abstract)

    num = OxmlElement("w:num")
    num.set(qn("w:numId"), str(num_id))
    abstract_ref = OxmlElement("w:abstractNumId")
    abstract_ref.set(qn("w:val"), str(abstract_id))
    num.append(abstract_ref)
    numbering.append(num)

    setattr(document, BULLET_NUM_ATTR, num_id)
    LOGGER.info("BULLET_NUMBERING abstract_id=%s num_id=%s", abstract_id, num_id)
    return num_id


def apply_bullet_numbering(paragraph, num_id: int) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    old_num_pr = p_pr.find(qn("w:numPr"))
    if old_num_pr is not None:
        p_pr.remove(old_num_pr)

    num_pr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), "0")
    num_pr.append(ilvl)
    num_id_el = OxmlElement("w:numId")
    num_id_el.set(qn("w:val"), str(num_id))
    num_pr.append(num_id_el)
    p_pr.append(num_pr)


def set_run_font(run, cfg: dict[str, Any], lang: str, size_key: str, bold: bool | None = None, color_key: str = "text") -> None:
    fonts = cfg["fonts"][lang]
    run.font.name = fonts["latin"]
    run._element.rPr.rFonts.set(qn("w:eastAsia"), fonts["east_asia"])
    run._element.rPr.rFonts.set(qn("w:ascii"), fonts["latin"])
    run._element.rPr.rFonts.set(qn("w:hAnsi"), fonts["latin"])
    run.font.size = pt(cfg["sizes_pt"][size_key])
    if bold is not None:
        run.bold = bold
    run.font.color.rgb = hex_color(cfg["colors"][color_key])


def configure_paragraph_style(style, cfg: dict[str, Any], lang: str, size_key: str, flag_key: str | None = None, color_key: str = "text") -> None:
    fonts = cfg["fonts"][lang]
    flags = cfg_get(cfg, f"style_flags.{flag_key}", {}) if flag_key else {}
    style.font.name = fonts["latin"]
    style.font.size = pt(cfg["sizes_pt"][size_key])
    style.font.bold = bool(flags.get("bold", False))
    style.font.italic = bool(flags.get("italic", False))
    style.font.color.rgb = hex_color(cfg["colors"][color_key])
    style.element.rPr.rFonts.set(qn("w:eastAsia"), fonts["east_asia"])
    style.element.rPr.rFonts.set(qn("w:ascii"), fonts["latin"])
    style.element.rPr.rFonts.set(qn("w:hAnsi"), fonts["latin"])

    p_pr = style.element.get_or_add_pPr()
    num_pr = p_pr.find(qn("w:numPr"))
    if num_pr is not None:
        p_pr.remove(num_pr)

    fmt = style.paragraph_format
    fmt.line_spacing = cfg["spacing"]["line_spacing"]
    fmt.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    fmt.space_after = pt(cfg["spacing"]["paragraph_after_pt"])
    alignment = paragraph_alignment(cfg_get(cfg, f"alignment.{style.name}", cfg_get(cfg, "alignment.default")))
    if alignment is not None:
        fmt.alignment = alignment
    if style.name != "ResumeBullet":
        fmt.left_indent = Cm(0)
        fmt.first_line_indent = Cm(0)


def configure_styles(document: Document, cfg: dict[str, Any], lang: str) -> None:
    configure_paragraph_style(ensure_style(document, "ResumeNormal"), cfg, lang, "body")
    configure_paragraph_style(ensure_style(document, "ResumeName"), cfg, lang, "name", flag_key="name")
    configure_paragraph_style(ensure_style(document, "ResumeTitle"), cfg, lang, "title")
    configure_paragraph_style(ensure_style(document, "ResumeContact"), cfg, lang, "contact")
    configure_paragraph_style(ensure_style(document, "ResumeSection"), cfg, lang, "section", flag_key="section", color_key="section_heading")
    configure_paragraph_style(ensure_style(document, "ResumeJobTitle"), cfg, lang, "job_title", flag_key="job_title", color_key="job_title")
    configure_paragraph_style(ensure_style(document, "ResumeCompanyDate"), cfg, lang, "company_date", flag_key="company_date", color_key="company_date")
    configure_paragraph_style(ensure_style(document, "ResumeBullet"), cfg, lang, "bullet")

    document.styles["Normal"].font.name = cfg["fonts"][lang]["latin"]
    document.styles["Normal"].element.rPr.rFonts.set(qn("w:eastAsia"), cfg["fonts"][lang]["east_asia"])

    document.styles["ResumeName"].paragraph_format.space_after = pt(cfg["spacing"]["name_after_pt"])
    document.styles["ResumeTitle"].paragraph_format.space_after = pt(cfg["spacing"]["title_after_pt"])
    document.styles["ResumeContact"].paragraph_format.space_after = pt(cfg["spacing"]["contact_after_pt"])

    section_fmt = document.styles["ResumeSection"].paragraph_format
    section_fmt.space_before = pt(cfg["spacing"]["section_before_pt"])
    section_fmt.space_after = pt(cfg["spacing"]["section_after_pt"])

    job_fmt = document.styles["ResumeJobTitle"].paragraph_format
    job_fmt.space_before = pt(cfg["spacing"]["job_before_pt"])
    job_fmt.space_after = pt(cfg["spacing"]["job_after_pt"])

    company_fmt = document.styles["ResumeCompanyDate"].paragraph_format
    company_fmt.space_after = pt(cfg["spacing"]["company_after_pt"])

    bullet_fmt = document.styles["ResumeBullet"].paragraph_format
    bullet_fmt.left_indent = None
    bullet_fmt.first_line_indent = None
    bullet_fmt.space_after = pt(cfg["spacing"]["bullet_after_pt"])


def configure_page(document: Document, cfg: dict[str, Any]) -> None:
    section = document.sections[0]
    page_size = str(cfg_get(cfg, "page.size", "A4")).upper()
    if page_size != "A4":
        raise ValueError(f"Unsupported page size: {page_size}")
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    margins = cfg["page"]["margins_cm"]
    section.left_margin = Cm(float(margins["left"]))
    section.right_margin = Cm(float(margins["right"]))
    section.top_margin = Cm(float(margins["top"]))
    section.bottom_margin = Cm(float(margins["bottom"]))


def strip_links(text: str) -> str:
    return re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", str(text))


def color_key_for_style(style: str) -> str:
    return {
        "ResumeSection": "section_heading",
        "ResumeJobTitle": "job_title",
        "ResumeCompanyDate": "company_date",
    }.get(style, "text")


def add_inline_runs(paragraph, text: str, cfg: dict[str, Any], lang: str, size_key: str, color_key: str = "text") -> None:
    text = strip_links(text)
    pos = 0
    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        if match.start() > pos:
            run = paragraph.add_run(text[pos : match.start()])
            set_run_font(run, cfg, lang, size_key, color_key=color_key)
        run = paragraph.add_run(match.group(1))
        set_run_font(run, cfg, lang, size_key, bold=True, color_key=color_key)
        pos = match.end()
    if pos < len(text):
        run = paragraph.add_run(text[pos:])
        set_run_font(run, cfg, lang, size_key, color_key=color_key)


def add_text(document: Document, text: str, style: str, cfg: dict[str, Any], lang: str, size_key: str) -> None:
    LOGGER.info("ADD_TEXT style=%s size_key=%s lang=%s text=%r", style, size_key, lang, one_line(text))
    if style == "ResumeSection" and cfg_get(cfg, "style_flags.section.all_caps", False):
        text = str(text).upper()
    paragraph = document.add_paragraph(style=style)
    clear_numbering(paragraph)
    add_inline_runs(paragraph, str(text), cfg, lang, size_key, color_key_for_style(style))
    if style == "ResumeSection" and cfg_get(cfg, "style_flags.section.border_bottom", False):
        add_paragraph_bottom_border(paragraph, cfg)
    LOGGER.info(
        "ADD_TEXT_DONE style=%s left_indent=%s first_line_indent=%s numPr=%s",
        style,
        paragraph.paragraph_format.left_indent,
        paragraph.paragraph_format.first_line_indent,
        bool(paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None),
    )


def add_labeled_text(document: Document, label: str, text: str, cfg: dict[str, Any], lang: str) -> None:
    LOGGER.info("ADD_LABELED_TEXT style=ResumeNormal lang=%s label=%r text=%r", lang, one_line(label), one_line(text))
    paragraph = document.add_paragraph(style="ResumeNormal")
    clear_numbering(paragraph)
    separator = "：" if lang == "zh" else ":"
    label_run = paragraph.add_run(f"{label}{separator} ")
    set_run_font(label_run, cfg, lang, "skills", bold=True)
    add_inline_runs(paragraph, text, cfg, lang, "skills")


def add_bullet(document: Document, text: str, cfg: dict[str, Any], lang: str) -> None:
    LOGGER.info("ADD_BULLET style=ResumeBullet lang=%s text=%r", lang, one_line(text))
    paragraph = document.add_paragraph(style="ResumeBullet")
    apply_bullet_numbering(paragraph, ensure_bullet_numbering(document))
    add_inline_runs(paragraph, str(text), cfg, lang, "bullet")


def add_left_right(document: Document, left: str, right: str | None, style: str, cfg: dict[str, Any], lang: str, size_key: str) -> None:
    LOGGER.info("ADD_LEFT_RIGHT style=%s size_key=%s lang=%s left=%r right=%r", style, size_key, lang, one_line(left), one_line(right))
    if not right or cfg_get(cfg, "date_layout.mode", "right_tab") == "inline":
        text = f"{left}  {right}" if right else left
        add_text(document, text, style, cfg, lang, size_key)
        return
    paragraph = document.add_paragraph(style=style)
    clear_numbering(paragraph)
    usable_width = document.sections[-1].page_width - document.sections[-1].left_margin - document.sections[-1].right_margin
    paragraph.paragraph_format.tab_stops.add_tab_stop(usable_width, WD_TAB_ALIGNMENT.RIGHT)
    add_inline_runs(paragraph, left, cfg, lang, size_key, color_key_for_style(style))
    paragraph.add_run("\t")
    add_inline_runs(paragraph, right, cfg, lang, size_key, color_key_for_style(style))


def add_horizontal_rule(document: Document, cfg: dict[str, Any]) -> None:
    if cfg.get("horizontal_rule", {}).get("mode", "skip") != "subtle":
        return
    paragraph = document.add_paragraph(style="ResumeNormal")
    clear_numbering(paragraph)
    add_paragraph_bottom_border(paragraph, cfg)
    paragraph.paragraph_format.space_after = pt(cfg_get(cfg, "horizontal_rule.space_after_pt", 2))


def add_paragraph_bottom_border(paragraph, cfg: dict[str, Any]) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    border = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(cfg_get(cfg, "horizontal_rule.size", 4)))
    bottom.set(qn("w:space"), str(cfg_get(cfg, "horizontal_rule.space", 1)))
    bottom.set(qn("w:color"), cfg["colors"]["horizontal_rule"])
    border.append(bottom)
    p_pr.append(border)


def add_internal_guide(document: Document, cfg: dict[str, Any], lang: str) -> None:
    add_text(document, "INTERNAL STYLE GUIDE — DELETE BEFORE EXPORT", "ResumeSection", cfg, lang, "section")
    lines = [
        f"Language profile: {lang}",
        f"Page: A4, margins {cfg['page']['margins_cm']}",
        f"Fonts: latin={cfg['fonts'][lang]['latin']}, east_asia={cfg['fonts'][lang]['east_asia']}",
        f"Body {cfg['sizes_pt']['body']} pt, line spacing {cfg['spacing']['line_spacing']}",
        "Defined styles: " + ", ".join(sorted(REQUIRED_STYLES)),
        "Edit style_config.yaml to revise fonts, spacing, margins, colors, or this guide toggle.",
    ]
    for line in lines:
        add_text(document, line, "ResumeNormal", cfg, lang, "body")
    document.add_page_break()


def company_location(item: dict[str, Any]) -> str:
    company = item.get("company") or item.get("organization") or item.get("school") or ""
    location = item.get("location")
    return f"{company} — {location}" if location else str(company)


def add_section_heading(document: Document, title: str, cfg: dict[str, Any], lang: str) -> None:
    add_text(document, title, "ResumeSection", cfg, lang, "section")


def render_profile(document: Document, profile: dict[str, Any], cfg: dict[str, Any], lang: str) -> None:
    add_text(document, profile.get("name", ""), "ResumeName", cfg, lang, "name")
    if profile.get("title"):
        add_text(document, profile["title"], "ResumeTitle", cfg, lang, "title")
    for contact in profile.get("contacts", []):
        add_text(document, contact, "ResumeContact", cfg, lang, "contact")


def render_summary(document: Document, section: dict[str, Any], cfg: dict[str, Any], lang: str) -> None:
    add_section_heading(document, section["title"], cfg, lang)
    for paragraph in section.get("paragraphs", []):
        add_text(document, paragraph, "ResumeNormal", cfg, lang, "body")


def render_skills(document: Document, section: dict[str, Any], cfg: dict[str, Any], lang: str) -> None:
    add_section_heading(document, section["title"], cfg, lang)
    for group in section.get("groups", []):
        add_labeled_text(document, group.get("label", ""), group.get("text", ""), cfg, lang)


def render_experience(document: Document, section: dict[str, Any], cfg: dict[str, Any], lang: str) -> None:
    add_section_heading(document, section["title"], cfg, lang)
    for item in section.get("items", []):
        add_left_right(document, item.get("role", ""), item.get("dates"), "ResumeJobTitle", cfg, lang, "job_title")
        if item.get("company") or item.get("location"):
            add_text(document, company_location(item), "ResumeCompanyDate", cfg, lang, "company_date")
        if item.get("description"):
            add_text(document, item["description"], "ResumeNormal", cfg, lang, "body")
        for bullet in item.get("bullets", []):
            add_bullet(document, bullet, cfg, lang)


def render_education(document: Document, section: dict[str, Any], cfg: dict[str, Any], lang: str) -> None:
    add_section_heading(document, section["title"], cfg, lang)
    for item in section.get("items", []):
        add_left_right(document, item.get("school", ""), item.get("dates"), "ResumeJobTitle", cfg, lang, "job_title")
        if item.get("degree"):
            add_text(document, item["degree"], "ResumeCompanyDate", cfg, lang, "company_date")
        for bullet in item.get("bullets", []):
            add_bullet(document, bullet, cfg, lang)


def render_bullet_section(document: Document, section: dict[str, Any], cfg: dict[str, Any], lang: str) -> None:
    add_section_heading(document, section["title"], cfg, lang)
    for bullet in section.get("bullets", []):
        add_bullet(document, bullet, cfg, lang)


def render_resume(document: Document, resume: dict[str, Any], cfg: dict[str, Any], lang: str) -> None:
    profile = resume.get("profile")
    if not isinstance(profile, dict):
        raise ValueError("Resume YAML must contain a profile mapping.")
    sections = resume.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Resume YAML must contain a sections list.")

    render_profile(document, profile, cfg, lang)
    renderers = {
        "summary": render_summary,
        "skills": render_skills,
        "experience": render_experience,
        "education": render_education,
        "bullets": render_bullet_section,
    }
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Each section must be a mapping.")
        section_type = section.get("type")
        renderer = renderers.get(section_type)
        if renderer is None:
            raise ValueError(f"Unsupported section type: {section_type}")
        renderer(document, section, cfg, lang)
        add_horizontal_rule(document, cfg)


def convert_to_pdf(docx_path: Path) -> Path | None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(docx_path.parent), str(docx_path)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return docx_path.with_suffix(".pdf")


def validate_docx_bullets(docx_path: Path) -> None:
    """Ensure native Word bullets only appear on explicit ResumeBullet paragraphs."""
    root = ET.fromstring(ZipFile(docx_path).read("word/document.xml"))
    bad: list[str] = []
    bullet_count = 0
    for index, paragraph in enumerate(root.findall(".//w:body/w:p", WORD_NS), 1):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", WORD_NS))
        style_el = paragraph.find("./w:pPr/w:pStyle", WORD_NS)
        style = ""
        if style_el is not None:
            style = style_el.attrib.get(f"{{{WORD_NS['w']}}}val", "")
        has_numbering = paragraph.find("./w:pPr/w:numPr", WORD_NS) is not None
        has_literal_bullet = "•" in text
        if style == "ResumeBullet":
            bullet_count += 1
            if not has_numbering:
                bad.append(f"{index}: ResumeBullet missing native numbering: {text[:80]}")
            if has_literal_bullet:
                bad.append(f"{index}: ResumeBullet contains literal bullet text: {text[:80]}")
        elif has_numbering or has_literal_bullet:
            bad.append(f"{index}: {style}: {text[:80]}")
    if bad:
        raise ValueError("Invalid bullet formatting: " + "; ".join(bad))
    LOGGER.info("BULLET_VALIDATION_OK bullet_count=%s", bullet_count)


def generate(input_path: Path, config_path: Path, lang: str, output_path: Path, export_pdf: bool = False, log_path: Path | None = None) -> None:
    if lang not in {"en", "zh"}:
        raise ValueError("--lang must be en or zh")

    if log_path is None:
        log_path = output_path.with_suffix(".log")
    setup_logging(log_path)
    LOGGER.info("START input=%s config=%s lang=%s output=%s", input_path, config_path, lang, output_path)

    raw_cfg = load_yaml(config_path, "Config")
    cfg = effective_config(raw_cfg, lang)
    resume = load_yaml(input_path, "Resume")
    LOGGER.info("CONFIG_YAML\n%s", yaml.safe_dump(cfg, allow_unicode=True, sort_keys=True))
    LOGGER.info("RESUME_PROFILE name=%r title=%r section_count=%s", resume.get("profile", {}).get("name"), resume.get("profile", {}).get("title"), len(resume.get("sections", [])))

    document = Document()
    configure_page(document, cfg)
    configure_styles(document, cfg, lang)

    if cfg.get("include_internal_guide", False):
        add_internal_guide(document, cfg, lang)

    render_resume(document, resume, cfg, lang)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)
    validate_docx_bullets(output_path)
    LOGGER.info("VALIDATION_OK output=%s", output_path)

    if export_pdf:
        pdf_path = convert_to_pdf(output_path)
        if pdf_path:
            print(f"PDF exported: {pdf_path}")
        else:
            print("LibreOffice not found; skipped PDF export.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a styled Word resume from structured YAML.")
    parser.add_argument("--input", required=True, type=Path, help="Resume YAML input file, e.g. resume_en.yaml")
    parser.add_argument("--config", required=True, type=Path, help="YAML style config file")
    parser.add_argument("--lang", required=True, choices=["en", "zh"], help="Resume language profile")
    parser.add_argument("--output", required=True, type=Path, help="Output .docx path")
    parser.add_argument("--log", type=Path, help="Debug log path. Defaults to output file name with .log extension.")
    parser.add_argument("--pdf", action="store_true", help="Also export PDF if LibreOffice is installed")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        generate(args.input, args.config, args.lang, args.output, args.pdf, args.log)
    except (FileNotFoundError, ValueError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"DOCX generated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
