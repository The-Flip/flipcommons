# Python Development

## Type Checking

The backend uses **mypy** with the **django-stubs** plugin. Pre-commit runs mypy in daemon mode (`dmypy`) so full-project analysis stays fast on every commit. `strict = true` is global; pre-commit and CI fail on any error.

**If local mypy disagrees with CI,** the daemon is likely out of sync (common after branch switches or rebases). Run:

```sh
make mypy-restart
```

Other daemon commands: `make mypy-warm` (pays cold-start up front), `make mypy-status` (is the daemon alive?).

## Typing

Types do two jobs here: **catch errors** — a wrong value fails to type-check — and **document intent** — a reader sees what a value _is_, not just its machine shape. "Code MUST be as strongly typed as possible" means serving both: pick the type that carries the most of each the situation affords. The jobs rarely conflict; where they seem to, it is almost always an alias faking structure (see [Typing for intent](#typing-for-intent)).

The smells below defeat the first job. They are _sometimes_ legitimate, but usually a sign the type can be tightened:

- Use of `Any`, `object`, `cast`, `isinstance`, `setattr`, `getattr`, `TYPE_CHECKING`, `# type: ignore`, `# noqa`
- Compound types in signatures whose meaning isn't obvious from the types alone — `tuple[...]`, nested dicts (`dict[X, dict[Y, Z]]`), `Callable[[A, B, C], R]`. **Heuristic**: if a reader would need a comment to know what each position/key means, name it (`NamedTuple` / `TypedDict` / `dataclass` / type alias). Applies to 2-tuples that cross a module boundary or appear in a public signature; locally unpacked pairs (`found, value = _lookup(key)`) are fine as plain tuples.

### Typing for intent

The second job is not a smell to remove but a practice to apply: name a value's _meaning_ even when mypy learns nothing new from the name (`Slug = str`, `PublicId = str` — to the checker still `str`).

**Use a semantic alias** (`Slug = str`, `EntityType = str`) when a bare scalar would force a reader to infer what the value is — but only where that inference is costly: public function signatures, type parameters, and fields on a `NamedTuple` / `TypedDict` that cross a module boundary. A bare `str` / `int` stays fine for locals, private helpers, loop variables and params whose name already says it (`def slugify(text: str)`). The test is the same "would a reader need a comment?" heuristic used for compound types above — applied to a single value's _meaning_ rather than a shape's _positions_.

**Not on anything that becomes a Pydantic schema** — Ninja `Schema` fields and route path/query params alike, since Ninja builds a model from the view signature too. Pydantic registers a PEP 695 alias as a named component, so the value emits `{"$ref": "#/$defs/Username"}` where a bare `str` emits `{"type": "string"}` — that leaks a spurious type into the generated `schema.d.ts` and trips the Schema/Ref suffix discipline. Wire values take the primitive; see the note in [`backend/apps/catalog/api/schemas.py`](../backend/apps/catalog/api/schemas.py). The exception is a shape genuinely worth naming on the wire, like `JsonBody`, where the shared component is the point.

**Never use an alias to fake structure.** `UserRow = tuple[int, str, datetime]` reads like a type but callers still index by position — that is a strictness gap wearing an intent costume, and the fix is a `NamedTuple`, not a better alias name. Aliases name one value's meaning; named records name a multi-field shape. (This is why [the rule below](#choosing-a-data-shape) and [Reviewing.md](Reviewing.md) warn against aliases — they are warning against _this_ misuse, not against intent aliases.)

The codebase already does this: `JsonData` / `JsonBody` are preferred over a bare `dict[str, Any]` because the name carries the contract.

**Prefer a transparent `type X = …` alias to `NewType`** for any value that flows through the Django ORM. The ORM hands back bare `int` / `str`, so a `NewType` forces a wrap (`ChangeSetId(row.changeset_id)`) — and the `cast` noise it invites — at every read, for no checker gain the alias doesn't already give as documentation. Reserve `NewType` for values that never touch the ORM and are genuinely dangerous to mix (rare). Don't redeclare the same alias locally in two apps — import the one canonical spelling.

**Keep a semantic scalar alias in a dependency-free leaf module** — `apps/core/types.py`, or an app's own `types.py` — never beside its Django model. `from apps.core.models.license import LicenseId` would drag the `License` model into every annotation-only importer, which is exactly what the alias exists to avoid. Put it in the lowest app that uses it, so even `core` can name its own fields (e.g. `EntityKey.object_id: ClaimSubjectId`).

### Valid exceptions to strong types

Broad types are acceptable when required by a third party:

- Django management-command `**kwargs` / `**options`
- Django signal receivers and auth-backend hooks
- Django-Ninja dispatch edges where schemas validate runtime shape
- Third-party APIs that genuinely discard type information
- Unavoidable django-stubs limitations

Every exception needs a short reason at the use site.

### Choosing a data shape

- Use Ninja/Pydantic `Schema` for API request/response shapes
- Use `TypedDict` for internal dicts with stable keys
- Use `Protocol` for structural contracts
- Use `NamedTuple` or dataclass for records with named fields
- Do not use a type alias to hide positional tuple structure (e.g. `UserRow = tuple[int, str, datetime]`) — use a `NamedTuple` instead
- Do not use `dict[str, Any]` for JSON-shaped data:
  - Use `apps.core.types.JsonData` for read-side JSON mappings
  - Use `apps.core.types.JsonBody` for mutable/test-client JSON bodies

#### Worked examples

```python
# Bad — reader has to remember what the positions mean.
def resolve_labels(items: Iterable[tuple[str, object]]) -> ...

# Good — the record has a name and the fields are self-describing.
class FieldValue(NamedTuple):
    field_name: str
    value: object

def resolve_labels(items: Iterable[FieldValue]) -> ...
```

```python
# Bad — three concepts (target model, pk, label) smushed into a nested dict.
labels: dict[tuple[type[Model], int], str]

# Good — the (model, pk) pair is named; the dict is just "labels keyed by FK refs."
class FkRef(NamedTuple):
    model: type[Model]
    pk: int

labels: dict[FkRef, str]
```

```python
# Bad — Callable signature with non-obvious parameters; signature drift
# is only caught wherever the formatter happens to be assigned.
ValueFormatter = Callable[[dict[str, object], RelationshipSchema, LabelLookup], str | None]

def _format_credit(value, schema, labels) -> str: ...

# Good — a no-op decorator pins each implementation to the contract,
# so signature drift is flagged on the function itself.
def value_formatter(fn: ValueFormatter) -> ValueFormatter:
    return fn

@value_formatter
def _format_credit(value, schema, labels) -> str: ...
```

### Django typing idioms

For helpers generic over model classes, prefer `_default_manager` over `.objects`; django-stubs can see `_default_manager` on `type[Model]`.

Do not replace `obj.fk_id is not None` with `obj.fk is not None` just to satisfy mypy. The first is a column check; the second may fetch the related object. If you need the related object narrowed, bind it locally after the `_id` guard and assert it is not `None`.

For queryset-annotated attributes, prefer a narrow structural `Protocol` over widening the whole model to `Any`.

### Pydantic and Ninja

Serialization helpers should usually return Ninja/Pydantic `Schema` instances, not dicts that are later revalidated into the same schema.

Use dict returns only when the dict is the real runtime contract, such as cached JSON-byte hot paths.

When a Ninja response type is a union of schemas with shared fields, make dispatch structurally unambiguous: required distinguishing fields on the richer schema, and `extra="forbid"` on the minimal schema where needed.

**Don't put a semantic scalar alias on the wire.** A transparent alias (`type ChangeSetId = int`) used as a Ninja route param or a `Schema` field surfaces as a _named_ OpenAPI component — `ChangeSetId` lands in the generated schema and the frontend's `schema.d.ts`, and `apps/core/tests/test_openapi_boundaries.py` fails it (component names must end in `Schema` / `Ref` or be allowlisted). Keep route params and `Schema` fields bare `int` / `str`; the alias is for internal Python signatures (`claim.changeset_id`, helper params, `NamedTuple` / dataclass fields). Keeping the wire bare also lets the internal alias be renamed without a frontend-visible schema or codegen diff.

### Suppressions

If you use `# type: ignore[code]` or `# noqa: RULE`, you MUST include a reason.

`ANN401` applies to top-level `Any` parameters and return annotations. It does not apply to nested `dict[str, Any]` or `cast(Any, ...)`; do not add `# noqa: ANN401` there. Use a plain comment if the broad type is intentional.

NEVER silence a warning when the underlying type can be expressed.
