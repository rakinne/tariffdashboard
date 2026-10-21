from pathlib import Path


PREVIEW = Path(__file__).parents[1] / "preview"


def test_preview_contains_one_pending_review_evidence_card() -> None:
    html = (PREVIEW / "index.html").read_text()

    assert html.count('class="evidence-card"') == 1
    assert "$994" in html
    assert "Q2 2026 filing" in html
    assert "Pending review" in html
    assert "Reference only" in html
    assert "not an approved dashboard claim" in html


def test_preview_exposes_provenance_and_visible_gaps() -> None:
    html = (PREVIEW / "index.html").read_text()

    for marker in ("Source locator", "Source fingerprint", "Rights &amp; review", "3 gaps"):
        assert marker in html


def test_preview_has_no_claim_projection_or_ranking_language() -> None:
    html = (PREVIEW / "index.html").read_text().lower()

    assert "approved public projection" in html
    assert "no ranking" in html
    assert "cohort total" in html
