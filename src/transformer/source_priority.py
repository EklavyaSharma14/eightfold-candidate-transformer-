"""
Per-field source reliability weights.

These encode "if two sources disagree on this field, who do we believe
more, and by how much" -- e.g. an ATS system of record beats a recruiter's
free-text notes for a job title, but GitHub's repo languages beat a
recruiter's guess at someone's skills.

Weights are 0.0-1.0. Missing (field, source) pairs fall back to
DEFAULT_WEIGHT.
"""

DEFAULT_WEIGHT = 0.5

SOURCE_PRIORITY = {
    "full_name":        {"ats_json": 0.9, "csv": 0.85, "github": 0.6,  "notes": 0.6},
    "emails":           {"ats_json": 0.9, "csv": 0.85, "github": 0.5,  "notes": 0.6},
    "phones":           {"ats_json": 0.9, "csv": 0.85, "github": 0.3,  "notes": 0.6},
    "location":         {"ats_json": 0.85, "csv": 0.8, "github": 0.6,  "notes": 0.5},
    "headline":         {"ats_json": 0.9, "csv": 0.8,  "github": 0.6,  "notes": 0.55},
    "years_experience": {"ats_json": 0.85, "csv": 0.6, "github": 0.3,  "notes": 0.6},
    "skills":           {"ats_json": 0.6, "csv": 0.4,  "github": 0.85, "notes": 0.7},
    "experience":       {"ats_json": 0.9, "csv": 0.6,  "github": 0.4,  "notes": 0.6},
    "education":        {"ats_json": 0.85, "csv": 0.3, "github": 0.2,  "notes": 0.6},
    "links":            {"ats_json": 0.7, "csv": 0.6,  "github": 0.95, "notes": 0.6},
}


def weight_for(field, source_type):
    return SOURCE_PRIORITY.get(field, {}).get(source_type, DEFAULT_WEIGHT)
