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
story.append(Paragraph(f"{YOUR_FULL_NAME} &nbsp;&middot;&nbsp; {YOUR_EMAIL} &nbsp;&middot;&nbsp; Eightfold Engineering Intern (Jul–Dec 2026), Stage 2", sub_style))
story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#cccccc"), spaceAfter=4))


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(t, bullet_style), bulletColor=colors.HexColor("#1a3c6e")) for t in items],
        bulletType="bullet", start="circle", leftIndent=12, bulletFontSize=6, spaceBefore=0, spaceAfter=3,
    )


story.append(Paragraph("Pipeline", h_style))
story.append(Paragraph(
    "I broke the pipeline into seven stages: <b>detect → extract → normalize → merge → "
    "confidence → project → validate.</b> Detect just figures out, from the manifest, which "
    "extractor each source needs. Extract pulls a raw, not-yet-normalized record out of each "
    "source — this is also where ATS's own field names get remapped onto the fields I actually "
    "use — and is wrapped so that a bad source produces a logged error rather than a crash. "
    "Normalize converts each raw field into a standard format. Merge combines the normalized "
    "values across sources into one record and resolves any conflicts along the way. Confidence "
    "scores every field that ended up populated. Project reshapes the canonical record according "
    "to whatever runtime config was passed in. Validate is a last check on the projected output's "
    "shape before it gets returned.",
    body_style))

story.append(Paragraph("Canonical Schema &amp; Normalized Formats", h_style))
story.append(Paragraph(
    "The default schema follows the brief's table (candidate_id, full_name, emails[], phones[], "
    "location, links, headline, years_experience, skills[], experience[], education[], "
    "provenance[], overall_confidence). I added one extra field, <b>source_errors</b>, which logs "
    "which sources failed and why for a given candidate — it answers \"why is this profile thin?\" "
    "the same way provenance answers \"why is this particular value what it is?\"", body_style))
story.append(bullets([
    "<b>Phones</b> normalize to E.164 using the <i>phonenumbers</i> library. If there's no country "
    "code and no location hint to infer one from, it falls back to a default region but flags the "
    "result as a guess (lower confidence) rather than treating it like a clean parse.",
    "<b>Dates</b> become YYYY-MM. A year-only value like \"2019\" becomes 2019-01 but with an "
    "explicit low-precision note attached — I didn't want a default month to look any more certain "
    "than it actually is. \"Present\"/\"Current\" are treated as open-ended (null end date) instead "
    "of being forced into a real date.",
    "<b>Country</b> normalizes to ISO 3166-1 alpha-2 using <i>pycountry</i> plus a small alias table. "
    "Two-letter tokens get checked against US state abbreviations before the country lookup runs, "
    "so something like \"San Francisco, CA\" doesn't get misread as Canada.",
    "<b>Skills</b> map to a canonical name through an alias table (\"js\"/\"JS\" → JavaScript). "
    "Anything not in the table gets kept as-is, just with reduced confidence, rather than dropped.",
    "<b>Names</b> only get trimmed and have whitespace collapsed — never re-cased. Auto-titlecasing "
    "breaks real names (think \"O'Brien\"), and that felt like exactly the kind of mistake worth "
    "avoiding on purpose.",
]))

story.append(Paragraph("Merge &amp; Conflict-Resolution Policy", h_style))
story.append(Paragraph(
    "<b>Match key:</b> I'm assuming an upstream manifest already supplies the crosswalk — which "
    "CSV row, ATS record, GitHub fixture, and notes file all belong to a given candidate_id. More "
    "on why under Out of Scope.", body_style))
story.append(Paragraph(
    "<b>Scalar fields</b> (name, headline, years_experience, location) are winner-take-all, decided "
    "by a per-field source-priority table — ATS beats CSV beats GitHub beats notes for job title, "
    "for example, but for skills GitHub and notes outrank ATS and CSV, since actual code is more "
    "objective evidence than a recruiter's guess. field_confidence works out to source_weight times "
    "normalization_quality, with agreeing sources adding a small bonus (capped at 1.0) and "
    "disagreeing ones costing a penalty. A single high-priority source still beats two low-priority "
    "ones that happen to agree with each other — it's a hierarchy, not a vote. Whatever loses still "
    "gets kept in provenance rather than thrown away.", body_style))
story.append(Paragraph(
    "<b>List fields</b> (emails, phones, skills, experience, education) just get unioned and "
    "deduplicated instead of picking a winner — someone can genuinely have two emails, but not two "
    "different \"true\" current titles. <b>overall_confidence</b> is the sum of populated-field "
    "confidences divided by a fixed field count, so a thin profile scores low instead of looking "
    "artificially confident just because the few fields it does have are solid.", body_style))

story.append(Paragraph("Runtime Config (Projection Layer)", h_style))
story.append(Paragraph(
    "The full canonical record always gets built first — the config only acts as a downstream lens "
    "on top of it, with no special-casing anywhere. The default schema actually runs through the "
    "same projection function as any custom config does, which is what makes \"no code changes\" "
    "true in practice rather than just something I'm claiming. Each field in a config has a "
    "<i>path</i> (the output key), a <i>from</i> (the canonical path it pulls from — supports "
    "addressing like emails[0] or skills[].name), a <i>type</i>, and optionally <i>required</i> and "
    "<i>normalize</i> (to override the display form of an already-normalized value, e.g. E.164 → "
    "national format). A few top-level toggles control the rest: include_confidence (also strips "
    "per-skill confidence when off), include_provenance (also gates source_errors), and on_missing, "
    "which can be null, omit, or error. error fails loudly for that one candidate specifically — it "
    "doesn't take the rest of a batch down with it.", body_style))

story.append(Paragraph("Edge Cases Handled", h_style))
story.append(bullets([
    "Missing or corrupt sources (malformed JSON, a missing file, empty notes) get logged in "
    "source_errors and skipped — the candidate still gets a profile built from whatever's left.",
    "Conflicting values resolve by priority, with the loser kept in provenance along with why it lost.",
    "Messy dates get a best-effort YYYY-MM parse; year-only values are flagged low-precision instead "
    "of guessing a month with false confidence.",
    "A phone with no country code and no location hint to infer one falls back to a default-region "
    "guess that's explicitly flagged, or just null if it still won't validate — nothing's invented.",
    "The same skill written differently across sources gets canonicalized into a single entry with "
    "all contributing sources combined.",
]))

story.append(Paragraph("What I Left Out (and Why)", h_style))
story.append(Paragraph(
    "Fuzzy cross-source identity resolution when there's no shared ID — matching records across "
    "systems without one is its own project, so I pushed that assumption up to the manifest layer "
    "instead of trying to half-solve it here. Resume PDF/DOCX parsing — I used GitHub and notes as "
    "my two unstructured sources instead, since resume layouts vary enough that doing this properly "
    "felt like a separate effort; the extractor interface is the same shape for every source type "
    "though, so adding a resume extractor later is one more function, not a redesign. Live GitHub "
    "API calls in the test suite — a cached fixture is used instead so results stay deterministic "
    "and the tests run offline (the live-fetch code path exists, it just isn't exercised by tests). "
    "NER-based skill extraction from free text — dictionary and keyword matching only. And no UI "
    "beyond a CLI, since the brief explicitly said that was lower priority.", body_style))

doc.build(story)
print(f"Wrote {OUT_PATH}")
