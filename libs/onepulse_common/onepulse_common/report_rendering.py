"""Report Rendering (HLD Section 2, Step 7; closes FR-5).

FR-5: "The system shall render a finalized report's content into a
locked, per-project visual template." Physical Architecture and LLD
specify this as a deterministic builder with a single hard-coded layout
and no model call — the content it renders was already produced upstream
(Investigation, Synthesis, Deterministic Status Rollup); this module only
lays it out.

Colors are a plain navy-accent identity (no separate brand asset exists
in this repo to pull from) — Arial throughout, per the project's stated
visual direction, not invented from nothing.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

_NAVY = RGBColor(0x1F, 0x38, 0x64)
_WHITE = RGBColor(0xFF, 0xFF, 0xFF)
_DARK_TEXT = RGBColor(0x26, 0x26, 0x26)

_STATUS_COLORS: dict[str, RGBColor] = {
    "Red": RGBColor(0xC0, 0x00, 0x00),
    "Amber": RGBColor(0xED, 0x7D, 0x31),
    "Green": RGBColor(0x54, 0x82, 0x35),
    "Unknown": RGBColor(0x80, 0x80, 0x80),
}

_FONT = "Arial"


@dataclass(frozen=True)
class Finding:
    work_item_id: int
    title: str
    status: str
    evidence: str


def week_of(as_of: _dt.date) -> _dt.date:
    """Monday of the week containing as_of — deterministic, no model call."""
    return as_of - _dt.timedelta(days=as_of.weekday())


def render_status_report(
    *,
    program_name: str,
    as_of: _dt.date,
    overall_status: str,
    executive_summary: str,
    findings: list[Finding],
    output_path: str,
) -> None:
    if overall_status not in _STATUS_COLORS:
        raise ValueError(f"Unrecognized overall_status: {overall_status!r}")

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout

    # -- Header band (navy) with title --------------------------------
    header = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), prs.slide_width, Inches(1.0))
    header.fill.solid()
    header.fill.fore_color.rgb = _NAVY
    header.line.fill.background()
    title_tf = header.text_frame
    title_tf.margin_left = Inches(0.4)
    title_tf.margin_top = Inches(0.1)
    p = title_tf.paragraphs[0]
    p.text = f"{program_name} — Week of {week_of(as_of).isoformat()}"
    p.font.name = _FONT
    p.font.size = Pt(28)
    p.font.bold = True
    p.font.color.rgb = _WHITE

    # -- Overall Status badge ------------------------------------------
    badge = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(10.6), Inches(1.25), Inches(2.4), Inches(0.9))
    badge.fill.solid()
    badge.fill.fore_color.rgb = _STATUS_COLORS[overall_status]
    badge.line.fill.background()
    badge_tf = badge.text_frame
    badge_p = badge_tf.paragraphs[0]
    badge_p.text = overall_status.upper()
    badge_p.alignment = PP_ALIGN.CENTER
    badge_p.font.name = _FONT
    badge_p.font.size = Pt(24)
    badge_p.font.bold = True
    badge_p.font.color.rgb = _WHITE

    label_box = slide.shapes.add_textbox(Inches(10.6), Inches(1.0), Inches(2.4), Inches(0.3))
    label_p = label_box.text_frame.paragraphs[0]
    label_p.text = "OVERALL STATUS"
    label_p.alignment = PP_ALIGN.CENTER
    label_p.font.name = _FONT
    label_p.font.size = Pt(11)
    label_p.font.bold = True
    label_p.font.color.rgb = _NAVY

    # -- Executive Summary ----------------------------------------------
    summary_header = slide.shapes.add_textbox(Inches(0.4), Inches(1.25), Inches(9.8), Inches(0.35))
    sh_p = summary_header.text_frame.paragraphs[0]
    sh_p.text = "Executive Summary"
    sh_p.font.name = _FONT
    sh_p.font.size = Pt(16)
    sh_p.font.bold = True
    sh_p.font.color.rgb = _NAVY

    summary_box = slide.shapes.add_textbox(Inches(0.4), Inches(1.65), Inches(9.8), Inches(1.6))
    summary_tf = summary_box.text_frame
    summary_tf.word_wrap = True
    sp = summary_tf.paragraphs[0]
    sp.text = executive_summary
    sp.font.name = _FONT
    sp.font.size = Pt(13)
    sp.font.color.rgb = _DARK_TEXT

    # -- Key Findings -----------------------------------------------------
    kf_header = slide.shapes.add_textbox(Inches(0.4), Inches(3.35), Inches(12.5), Inches(0.35))
    kf_p = kf_header.text_frame.paragraphs[0]
    kf_p.text = "Key Findings"
    kf_p.font.name = _FONT
    kf_p.font.size = Pt(16)
    kf_p.font.bold = True
    kf_p.font.color.rgb = _NAVY

    findings_box = slide.shapes.add_textbox(Inches(0.4), Inches(3.75), Inches(12.5), Inches(3.4))
    findings_tf = findings_box.text_frame
    findings_tf.word_wrap = True

    for i, finding in enumerate(findings):
        title_p = findings_tf.paragraphs[0] if i == 0 else findings_tf.add_paragraph()
        title_p.text = f"#{finding.work_item_id}  {finding.title}  —  {finding.status}"
        title_p.font.name = _FONT
        title_p.font.size = Pt(14)
        title_p.font.bold = True
        title_p.font.color.rgb = _DARK_TEXT

        evidence_p = findings_tf.add_paragraph()
        evidence_p.text = f"Evidence: {finding.evidence}"
        evidence_p.level = 1
        evidence_p.font.name = _FONT
        evidence_p.font.size = Pt(12)
        evidence_p.font.italic = True
        evidence_p.font.color.rgb = RGBColor(0x59, 0x59, 0x59)

    prs.save(output_path)
