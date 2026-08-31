"""Architecture tests — the half of the layer contract import-linter cannot express.

import-linter enforces the *direction* of dependencies (views -> services -> selectors
-> models) but it cannot forbid `django.http` specifically, because subpackages of
external packages aren't valid targets in a forbidden contract. So the "no HTTP below
views" half lives here.

Doing it by AST rather than by configuration has a real advantage: it applies to every
app added in later phases automatically. Nobody has to remember to add `apps.billing.
services` to a list in `.importlinter` — the day that file exists, this test covers it.
"""

import ast
from pathlib import Path

import pytest

APPS_DIR = Path(__file__).resolve().parents[2]

# Modules below the controller layer. These take arguments and return objects; they
# do not know what a request is.
LOWER_LAYER_FILENAMES = ("services.py", "selectors.py", "models.py")

# Importing any of these is the signature of HTTP knowledge leaking downward.
# django.shortcuts is on the list deliberately: get_object_or_404 raises an HTTP
# concern from a layer that should be raising a domain one.
FORBIDDEN_PREFIXES = (
    "django.http",
    "django.shortcuts",
    "django.urls",
    "django.template",
    "rest_framework",
    "ninja",
)


def _lower_layer_modules() -> list[Path]:
    found: list[Path] = []
    for filename in LOWER_LAYER_FILENAMES:
        found.extend(p for p in APPS_DIR.rglob(filename) if "migrations" not in p.parts)
    return sorted(found)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def test_there_are_lower_layer_modules_to_check():
    """Guards the guard: an rglob that silently matches nothing would make every
    assertion below vacuously true."""
    assert _lower_layer_modules(), "Found no services/selectors/models to check."


@pytest.mark.parametrize("path", _lower_layer_modules(), ids=lambda p: str(p.name))
def test_no_http_below_the_controller_layer(path: Path):
    offenders = sorted(
        module for module in _imported_modules(path) if module.startswith(FORBIDDEN_PREFIXES)
    )
    assert not offenders, (
        f"{path.relative_to(APPS_DIR.parent)} imports {offenders}. "
        "Services, selectors and models must not know about HTTP — move the request "
        "handling up into views.py and pass plain arguments down. See docs/plan.md."
    )
