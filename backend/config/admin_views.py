"""Custom admin views (not tied to a specific model)."""

import time

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpRequest, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect

# Each entry: (POST value, label, description, resolver function path)
_RESOLVE_OPTIONS = [
    ("taxonomy", "Taxonomy", "tags, cabinets, systems, series, franchises, etc., < 1s"),
    ("manufacturers", "Manufacturers", "~700 entities, < 1s"),
    ("corporate-entities", "Corporate Entities", "~700 entities, < 1s"),
    ("people", "People", "~600 entities, < 1s"),
    ("themes", "Themes", "~600 entities, < 1s"),
    ("gameplay-features", "Gameplay Features", "~170 entities, < 1s"),
    ("titles", "Titles", "~6,000 entities, ~3s"),
    ("models", "Models + relationships", "~7,000 entities, ~20s"),
    ("all", "Everything", "All of the above in dependency order, ~25s"),
]


def _run_resolve(target: str) -> tuple[str, int]:
    """Run resolution for the given target. Returns (label, count)."""
    from apps.catalog.resolve import resolve_all_entities, resolve_machine_models

    if target == "taxonomy":
        from apps.catalog.models.taxonomy import (
            Cabinet,
            CreditRole,
            DisplaySubtype,
            DisplayType,
            GameFormat,
            RewardType,
            Tag,
            TechnologyGeneration,
            TechnologySubgeneration,
        )
        from apps.provenance.models import ClaimControlledModel

        taxonomy_models: list[type[ClaimControlledModel]] = [
            TechnologyGeneration,
            TechnologySubgeneration,
            DisplayType,
            DisplaySubtype,
            Cabinet,
            GameFormat,
            RewardType,
            Tag,
            CreditRole,
        ]
        total = 0
        for m in taxonomy_models:
            total += resolve_all_entities(m)
        return "taxonomy entities", total
    elif target == "manufacturers":
        from apps.catalog.models import Manufacturer

        return "manufacturers", resolve_all_entities(Manufacturer)
    elif target == "corporate-entities":
        from apps.catalog.models import CorporateEntity

        return "corporate entities", resolve_all_entities(CorporateEntity)
    elif target == "people":
        from apps.catalog.models import Person

        return "people", resolve_all_entities(Person)
    elif target == "themes":
        from apps.catalog.models import Theme

        return "themes", resolve_all_entities(Theme)
    elif target == "gameplay-features":
        from apps.catalog.models import GameplayFeature

        return "gameplay features", resolve_all_entities(GameplayFeature)
    elif target == "titles":
        from apps.catalog.models import Title

        return "titles", resolve_all_entities(Title)
    elif target == "models":
        count = resolve_machine_models()
        return "models + all entities", count
    elif target == "all":
        from apps.catalog.models import CorporateEntity, Manufacturer, Person

        resolve_all_entities(Manufacturer)
        resolve_all_entities(CorporateEntity)
        resolve_all_entities(Person)
        count = resolve_machine_models()
        return "all entities", count
    else:
        raise ValueError(f"Unknown resolve target: {target}")


@staff_member_required
def resolve_view(request: HttpRequest) -> HttpResponse:
    """Re-resolve catalog entities from their claims.

    GET renders a page with buttons for each entity type.
    POST runs the selected resolution and redirects with a success message.
    """
    if request.method == "POST":
        target = request.POST.get("target", "")
        start = time.monotonic()
        label, count = _run_resolve(target)
        elapsed = time.monotonic() - start

        from apps.catalog.cache import invalidate_all

        invalidate_all()

        if count >= 0:
            messages.success(request, f"Resolved {count} {label} in {elapsed:.1f}s.")
        else:
            messages.success(request, f"Resolved {label} in {elapsed:.1f}s.")
        return redirect("admin-resolve")

    csrf_token = get_token(request)
    buttons_html = ""
    for value, label, desc in _RESOLVE_OPTIONS:
        buttons_html += f"""
        <form method="post" style="margin-bottom: 0.75rem;" onsubmit="
            this.querySelector('button').disabled = true;
            this.querySelector('button').textContent = 'Resolving...';
            document.getElementById('status').style.display = 'block';
        ">
            <input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">
            <input type="hidden" name="target" value="{value}">
            <button type="submit" style="
                width: 100%; padding: 0.6rem 1rem; font-size: 0.95rem;
                cursor: pointer; text-align: left;
            ">{label} <span style="color: #888; font-size: 0.85rem;">&mdash; {desc}</span></button>
        </form>"""

    return HttpResponse(
        f"""<!DOCTYPE html>
<html>
<head><title>Re-resolve</title>
<style>
  body {{ font-family: -apple-system, sans-serif; max-width: 36rem; margin: 3rem auto; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.5rem; }}
  p {{ color: #555; margin-bottom: 1.5rem; }}
  #status {{ display: none; color: #666; margin-top: 1rem; }}
  a {{ display: block; margin-top: 1.5rem; }}
</style>
</head>
<body>
  <h1>Re-resolve entities</h1>
  <p>Re-resolve catalog entities from their claims after changing source settings.</p>
  {buttons_html}
  <p id="status">Resolving&hellip; the page will refresh when complete.</p>
  <a href="/djadmin/">&larr; Back to admin</a>
</body>
</html>""",
        content_type="text/html",
    )
