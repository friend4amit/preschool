"""Images that must never reach the public site.

`docs/plan.md` makes one of these a hard requirement: Dr Surashree Shome's portrait
and biography came from the Udgam site and must not appear on Aaroham's. The plan
asks for a `grep -ri "surashree|shome"` before launch; this makes it automatic, so
it cannot be forgotten on the one deploy that matters.

The others are files that would embarrass the school for duller reasons — visible
dreamstime watermarks, and burnt-in text ("BACK TO SCHOOL", a phone number) that no
amount of restyling can remove.

**What this cannot check.** It asserts over the repository and over what `seed_media`
will process. It says nothing about objects already sitting in an R2 bucket or in a
server's media directory — removing a published image is a separate, manual step, and
a test that implied otherwise would be worse than no test.
"""

from pathlib import Path

import pytest

from apps.website.management.commands.seed_media import BLOCKED, BLOCKED_STEMS, is_blocked

REPO = Path(__file__).resolve().parents[3]

# Where shipped assets live. `apps/` and `docs/` are deliberately NOT scanned: the
# blocklist module has to name her in order to block her, and docs/plan.md has to
# name her in order to say why. Scanning those would make this test fail on the very
# code and prose that enforce the rule, and the obvious "fix" would be to delete
# them.
SHIPPED = ["static", "templates", "assets", "media"]


def _shipped_files():
    for folder in SHIPPED:
        root = REPO / folder
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                yield path


def test_there_are_shipped_files_to_check():
    """Guards the guard. An rglob that matched nothing would make the assertion
    below vacuously true, and this test would pass forever while checking nothing."""
    assert any(_shipped_files())


def test_no_shipped_filename_names_the_excluded_person():
    offenders = [str(p.relative_to(REPO)) for p in _shipped_files() if BLOCKED.search(p.name)]
    assert not offenders, (
        f"These shipped files name a person who must not appear on this site: "
        f"{offenders}. See docs/plan.md."
    )


def test_no_shipped_template_mentions_the_excluded_person():
    offenders = []
    for path in _shipped_files():
        if path.suffix.lower() not in {".html", ".txt", ".css", ".js", ".md"}:
            continue
        if BLOCKED.search(path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"These shipped files mention her: {offenders}"


# --- the blocklist itself --------------------------------------------------------------


def test_the_blocklist_still_names_every_exclusion():
    """A silent deletion from BLOCKED_STEMS would be invisible until something
    shipped. This is the tripwire."""
    assert set(BLOCKED_STEMS) >= {
        "surashree-shome",
        "group-70",
        "group-71",
        "group-72",
        "udgam",
        "group-42",
        "early-child-care-and-education",
    }


@pytest.mark.parametrize(
    "name",
    [
        "2026/02/surashree-shome.png",
        "surashree-shome-150x150.png",
        "SURASHREE-SHOME.PNG",
        "Shome.jpg",
        "2026/02/Group-70.png",
        "Group-71-300x200.png",
        "Udgam.png",
        "2026/02/Group-42.png",
        "Early-Child-Care-and-Education.png",
    ],
)
def test_blocked_files_are_refused(name):
    assert is_blocked(name) is not None, f"{name} should be blocked"


@pytest.mark.parametrize(
    "name",
    [
        "2026/02/kids-plying-banner.png",
        "2026/02/class-techer.png",
        # The one that caught a real bug: "udgam" is blocked as an exact name, but
        # "udgam-family-kids" is a different photograph that merely shares the
        # prefix. A naive startswith() rejected it.
        "2026/02/udgam-family-kids.png",
        "2026/02/group-26-2.png",
        "2026/02/g-img-01.png",
    ],
)
def test_ordinary_files_are_not_refused(name):
    assert is_blocked(name) is None, f"{name} should NOT be blocked"


def test_the_reason_is_reported_not_just_the_refusal():
    """Whoever hits this needs to know why, or they will try to work around it."""
    assert "must not appear" in is_blocked("surashree-shome.png")
    assert "watermark" in is_blocked("Group-70.png")
