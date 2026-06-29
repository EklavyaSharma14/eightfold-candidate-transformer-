#!/usr/bin/env python3
"""Generates the one-page Step 1 design document as a PDF."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem, HRFlowable
from reportlab.lib import colors

YOUR_FULL_NAME = "Eklavya Sharma"
YOUR_EMAIL = "eklavya.sharma.ug23@nsut.ac.in"

OUT_PATH = f"design/{YOUR_FULL_NAME.replace(' ', '')}_{YOUR_EMAIL}_Eightfold.pdf"

styles = getSampleStyleSheet()
title_style = ParagraphStyle("TitleSmall", parent=styles["Title"], fontSize=14, leading=16, spaceAfter=2)
sub_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=8.5, leading=10, alignment=TA_CENTER,
                            textColor=colors.HexColor("#555555"), spaceAfter=8)
h_style = ParagraphStyle("H", parent=styles["Heading2"], fontSize=10.5, leading=12, spaceBefore=7, spaceAfter=2,
                          textColor=colors.HexColor("#1a3c6e"))
body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=8.3, leading=10.2, spaceAfter=1)
bullet_style = ParagraphStyle("Bullet", parent=styles["Normal"], fontSize=8.3, leading=10, spaceAfter=1,
                               leftIndent=10)

doc = SimpleDocTemplate(
    OUT_PATH, pagesize=letter,
    topMargin=0.45 * inch, bottomMargin=0.45 * inch,
    leftMargin=0.55 * inch, rightMargin=0.55 * inch,
)

story = []
story.append(Paragraph("Multi-Source Candidate Data Transformer — Technical Design", title_style))
story.append(Paragraph(f"{YOUR_FULL_NAME} &nbsp;&middot;&nbsp; {YOUR_EMAIL} &nbsp;&middot;&nbsp; Eightfold Engineering Intern (Jul–Dec 2026), Stage 1", sub_style))
story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cccccc"), spaceAfter=4))


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(t, bullet_style), bulletColor=colors.HexColor("#1a3c6e")) for t in items],
        bulletType="bullet", start="circle", leftIndent=12, bulletFontSize=6, spaceBefore=0, spaceAfter=3,
    )


story.append(Paragraph("Pipeline", h_style))
story.append(Paragraph(
    "<b>detect → extract → normalize → merge → confidence → project → validate.</b> "
    "Detect dispatches each manifest entry to the right extractor. Extract pulls a loosely-canonical "
    "raw record out of each source (this is where ATS's own field names get remapped onto our concepts), "
    "wrapped so a bad source produces a logged error, never a crash. Normalize converts per-field raw "
    "values into our canonical formats. Merge combines normalized values across sources into one record "
    "with conflict resolution. Confidence scores every populated field. Project reshapes the canonical "
    "record per the runtime config. Validate checks the projected output's shape before returning it.",
    body_style))

story.append(Paragraph("Canonical Schema &amp; Normalized Formats", h_style))
story.append(Paragraph(
    "Default schema matches the brief's table (candidate_id, full_name, emails[], phones[], location, "
    "links, headline, years_experience, skills[], experience[], education[], provenance[], "
    "overall_confidence), plus <b>source_errors</b> (which sources were skipped and why — answers "
    "\"why is this profile thin?\" the same way provenance answers \"why is this value what it is?\").", body_style))
story.append(bullets([
    "<b>Phones</b> → E.164 (<i>phonenumbers</i>). No country code + no location hint → falls back to a "
    "configured default region, but flagged as a guess (lower confidence), never presented as a clean parse.",
    "<b>Dates</b> → YYYY-MM. Year-only (\"2019\") → 2019-01 with an explicit low-precision note, not a "
    "confident-looking fake month. \"Present\"/\"Current\" → open-ended (null end), not coerced into a real date.",
    "<b>Country</b> → ISO 3166-1 alpha-2 (<i>pycountry</i> + alias table). 2-letter tokens are checked "
    "against US state codes <i>before</i> country lookup, so \"San Francisco, CA\" doesn't resolve to Canada.",
    "<b>Skills</b> → canonical name via an alias table (\"js\"/\"JS\" → JavaScript). Unknown skills are kept "
    "as-is with reduced confidence rather than dropped.",
    "<b>Names</b> → trimmed/whitespace-collapsed only, never re-cased — auto-titlecasing breaks real names "
    "(\"O'Brien\") and is exactly the confident-but-wrong move the brief warns against.",
]))

story.append(Paragraph("Merge &amp; Conflict-Resolution Policy", h_style))
story.append(Paragraph(
    "<b>Match key:</b> an upstream manifest supplies the crosswalk (which CSV row / ATS record / GitHub "
    "fixture / notes file belongs to a given candidate_id) — see Descoped.", body_style))
story.append(Paragraph(
    "<b>Scalar fields</b> (name, headline, years_experience, location): winner-take-all by a per-field "
    "source-priority table (e.g. ATS &gt; CSV &gt; GitHub &gt; notes for title; GitHub &gt; notes &gt; ATS "
    "for skills, since code is more objective evidence than a recruiter's guess). field_confidence = "
    "source_weight × normalization_quality; agreeing sources add a bonus (capped at 1.0); disagreeing ones "
    "cost a penalty. One strong source beats two weak ones that agree with each other — majority vote among "
    "low-priority sources does not override a single high-priority one. Every losing value is kept in "
    "provenance, never discarded.", body_style))
story.append(Paragraph(
    "<b>List fields</b> (emails, phones, skills, experience, education): unioned and deduplicated, not "
    "winner-take-all — a candidate can legitimately have two emails, not two \"true\" current titles. "
    "<b>overall_confidence</b> = sum of populated-field confidences ÷ a <i>fixed</i> field count, so a thin "
    "profile scores low rather than being inflated by the few confident fields it happens to have.", body_style))

story.append(Paragraph("Runtime Config (Projection Layer)", h_style))
story.append(Paragraph(
    "The full canonical record is always built first; the config is a pure downstream lens with no special "
    "casing — the <b>default schema runs through the same projection code path</b> as any custom config, "
    "which is what makes \"no code changes\" structural rather than a promise. Each field spec has "
    "<i>path</i> (output key), <i>from</i> (canonical path, supports emails[0] / skills[].name addressing), "
    "<i>type</i>, optional <i>required</i> and <i>normalize</i> (override the display form of an already-"
    "normalized value, e.g. E.164 → national). Top-level toggles: include_confidence (also strips per-skill "
    "confidence), include_provenance (also gates source_errors), on_missing ∈ {null, omit, error}. "
    "<b>error</b> fails loud for that one candidate in a batch — it does not take down the rest.", body_style))

story.append(Paragraph("Edge Cases Handled", h_style))
story.append(bullets([
    "<b>Missing/corrupt source</b> (malformed JSON, missing file, empty notes) — logged in source_errors "
    "and skipped; candidate still gets a profile from whatever survives.",
    "<b>Conflicting values</b> — priority-based winner; loser kept in provenance with the reason.",
    "<b>Partial/messy dates</b> — best-effort to YYYY-MM; year-only flagged low-precision, never a fabricated month.",
    "<b>Phone with no country code or location hint</b> — default-region guess, explicitly flagged, "
    "or null if it still doesn't validate — never invented.",
    "<b>Same skill, different casing/spelling</b> — canonicalized and merged into one entry with combined sources.",
]))

story.append(Paragraph("Deliberately Out of Scope (time-boxed)", h_style))
story.append(Paragraph(
    "Fuzzy cross-source identity resolution with no shared ID (its own ML/heuristics project — pushed to the "
    "manifest layer here); resume PDF/DOCX parsing (used GitHub + notes as the unstructured pair instead; the "
    "extractor interface is pluggable so a resume extractor is one more module, not a redesign); live GitHub "
    "API calls in the test suite (cached fixture used instead, for deterministic/offline runs — the live-fetch "
    "path exists but isn't exercised by tests); NER-based skill extraction from free text (dictionary + keyword "
    "matching only); any UI beyond a CLI.", body_style))

doc.build(story)
print(f"Wrote {OUT_PATH}")
