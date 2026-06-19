# Named Model

## Status: not started

No `NamedModel` mixin exists yet; catalog models still declare `name` per-subclass and `LinkableModel` carries only a `name: str` annotation. Scoped and ready, pending prioritization.

## Context

This work is an instance of the broader pattern in [ModelDrivenMetadata.md](ModelDrivenMetadata.md): encode per-model behavior on the model itself, consume it generically from shared infrastructure.

`NamedModel` is a new abstract Django base for catalog entities that have a human-readable `name` field. Today every catalog model declares `name = models.CharField(...)` per-subclass with subtly varying config (max_length, unique, blank). The convention is universal but enforced only by a `name: str` type annotation on `LinkableModel` — there's no actual base-class field, so the contract isn't visible to Django's introspection or the type checker beyond the bare annotation.

`NamedModel` makes the convention real: a typed Django field on an abstract base, subclassed by every catalog model that participates, with subclasses overriding the field declaration only when their config legitimately differs.

## The contract

```python
class NamedModel(models.Model):
    """A catalog entity with a human-readable name.

    Concrete subclasses inherit ``name`` directly with the base's defaults,
    or override the field declaration when they need different config
    (max_length, unique, blank, help_text). Abstract field override is a
    standard Django idiom — see the Django docs on abstract base classes.
    """

    name = models.CharField(max_length=200, validators=[validate_no_mojibake])

    class Meta:
        abstract = True

    def __str__(self) -> str:
        return self.name
```

Subclasses fall into two groups:

- **Use the base default unchanged**: Person (`max_length=200, validators=[validate_no_mojibake]`).
- **Override the field declaration** for a different shape:
  - `max_length=300`: Title, MachineModel, CorporateEntity.
  - `unique=True`: Manufacturer, System, Series, GameplayFeature, taxonomy models.
  - `blank=True`: Location (claim-controlled name).
  - Add `help_text`: CorporateEntity.

Override is verbose (the subclass redeclares the entire field), but Django supports it cleanly on abstract bases, and the cost is bounded — each subclass redeclares its `name` field exactly as it does today.

## Why this is separate from `LinkableModel`

`LinkableModel` answers "what's this model's URL identity?" — `entity_type`, `public_id_field`, `link_url_pattern`. Some models could be linkable without being named (an entity identified only by location-path or a tokenized ID). Some models could be named without being linkable (an internal-only entity that has a label but no public URL).

Today every catalog model that's linkable also has a `name` field — the two concerns coexist in practice — but the umbrella's [one capability per base](ModelDrivenMetadata.md#pattern-base-class--mixin) rule argues for splitting. `LinkableModel`'s `name: str` type annotation is a workaround for the missing base — once `NamedModel` exists, the annotation moves to where the contract actually lives.

## Current state and hoist plan

Today's situation:

- 14+ catalog models declare `name = models.CharField(...)` per-subclass with subtly varying config.
- `LinkableModel` carries `name: str` as a type annotation only — no Django field on the base.
- The comment in `core/models.py` explicitly explains why: "different max_length / validators per entity."
- Every consumer that reads `obj.name` relies on the convention; nothing on the type system or Django introspection enforces it.

Hoist:

1. Add `NamedModel(models.Model)` to `apps/core/models.py` with the typed `name` field, abstract Meta, and `__str__` returning `self.name`.
2. Make every catalog model that has a `name` field inherit `NamedModel`. Subclasses with the base's default config (Person) drop their field declaration; subclasses with different config keep it as an override.
3. **Remove the `name: str` type annotation from `LinkableModel`** — the contract now lives on `NamedModel`. Update the surrounding comment in `core/models.py` to reflect the new home.
4. Mostly no consumer changes — every `obj.name` read continues to work, and the type checker can now see `name` declared on `NamedModel` rather than only as a type hint.

No semantic change. Existing tests covering name-based behavior carry over.

## What stays out of scope

- **`display_name_field` ClassVar override hook.** Considered and rejected — every catalog model uses `name` as the display field, with no exceptions today. Adding a ClassVar to override a convention that nobody overrides is preemptive infrastructure (see the umbrella's [one capability per base](ModelDrivenMetadata.md#pattern-base-class--mixin) rule's "pick the smallest one that fits" guidance). If a future model ever needs a non-`name` display field, declare a `ClassVar[str] = "name"` on `NamedModel` then.
- **Search behavior, name normalization, slug derivation.** All of these read `obj.name` but live in their own subsystems. `NamedModel` provides the field; downstream consumers stay where they are.
- **`slug`.** `slug` is a similar per-subclass-declared field with a `slug: str` annotation on `LinkableModel`. A parallel `SluggedModel` could be argued for, but `LinkableModel` already provides the URL identity contract via `public_id_field`, and not every linkable model uses a `slug` field for that (Location uses `location_path`). So `slug` is more conventional than load-bearing — defer until it's a real pain.

## Why this lives in `apps.core.models`

`NamedModel` is generic infrastructure — not catalog-specific, not claim-specific, not soft-delete-specific. Living in `apps/core/models.py` alongside `LinkableModel` and `LifecycleStatusModel` keeps the core per-capability mixins co-located. Catalog models import and inherit from it; nothing about `NamedModel` itself reaches into the catalog layer. Claim-specific capability now lives with provenance on `ClaimControlledModel`.
