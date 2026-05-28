# Media App Typing

This is step 11 of [MypyFixing.md](MypyFixing.md).

Goal: improve the Python type surface area of the Media app. Same up-front-design discipline as Step 10 (ResolveHardening) — every helper signature, endpoint return type, and schema boundary decided here, before any code change. Avoids the gradual dict-return reverse-engineering that slowed Steps 1–7.

Same execution pattern as Step 2: helpers first, endpoints after, `make codegen` + frontend typecheck between batches.

## Scope

~39 baseline entries:

- [media/admin.py](../../../backend/apps/media/admin.py) (12)
- [media/api.py](../../../backend/apps/media/api.py) (9)
- [media/apps.py](../../../backend/apps/media/apps.py) (8)
- [media/processing.py](../../../backend/apps/media/processing.py) (6)
- [media/tests/test_helpers.py](../../../backend/apps/media/tests/test_helpers.py) (2), [test_processing.py](../../../backend/apps/media/tests/test_processing.py) (1), [test_upload_api.py](../../../backend/apps/media/tests/test_upload_api.py) (1)

Out of scope:

- [media/schemas.py](../../../backend/apps/media/schemas.py) (`UploadedMediaSchema` / `MediaRenditionsSchema`) — already typed; consumed by catalog endpoints (Step 7).
- [media/models.py](../../../backend/apps/media/models.py), [media/storage.py](../../../backend/apps/media/storage.py), [media/helpers.py](../../../backend/apps/media/helpers.py), [media/constants.py](../../../backend/apps/media/constants.py) — already clean.

## Up-front type catalog

### `media/processing.py`

Already returns named dataclasses (`ImageInfo`, `ProcessedImage`). The 6 baseline entries are local-variable issues, not signature issues.

- `_encode(image, fmt)`: `save_kwargs: dict[str, Any]` — Pillow's `image.save(**kwargs)` is genuinely heterogeneous (`format: str`, `quality: int`, `optimize: bool`). Idiom #3 ("3rd-party API constraint"). One-line comment naming the Pillow API.
- `process_original` / `generate_rendition`: 5× `Image` vs `ImageFile` assignment errors. `Image.open(...)` returns `ImageFile.ImageFile`; `ImageOps.exif_transpose(...)` and `image.convert(...)` return `Image.Image`. Fix: type the binding once as `Image.Image` and rebind through that typed local. No semantic change.

No new exported types.

### `media/apps.py`

Trivial. `def ready(self) -> None`, `def _register_heif() -> None`, `def _check_avif() -> None`. No exported types.

### `media/admin.py`

Standard Django admin annotations. No exported types.

- `class MediaRenditionInline(admin.TabularInline[MediaRendition, MediaAsset])` — django-stubs declares `TabularInline(InlineModelAdmin[_ChildModelT, _ParentModelT])`, so both child and parent are required. The inline is mounted under `MediaAssetAdmin`, hence `MediaAsset` for the parent slot.
- `class MediaAssetAdmin(admin.ModelAdmin[MediaAsset])`
- `class MediaRenditionAdmin(admin.ModelAdmin[MediaRendition])`
- `has_add_permission(self, request: HttpRequest, obj: Any = None) -> bool` (and the `change`/`delete` siblings).

`obj` parameter type follows django-stubs's `ModelAdmin.has_*_permission` signature; if django-stubs declares a tighter type, defer to it.

### `media/api.py` — endpoint signatures

All three endpoints currently have untyped `request` and untyped form/body params.

```python
def upload_media(
    request: HttpRequest,
    file: File[UploadedFile],
    entity_type: Form[str],
    slug: Form[str],
    category: Form[str | None] = None,
    is_primary: Form[bool] = False,
) -> UploadOut: ...

def detach_media(request: HttpRequest, body: MediaAssetRefIn) -> Status[None]: ...

def set_primary(request: HttpRequest, body: MediaAssetRefIn) -> Status[None]: ...
```

`Status` is `Generic[T]` ([ninja/responses.py:25](../../../backend/.venv/lib/python3.14/site-packages/ninja/responses.py)) — `class Status(Generic[T]): __init__(self, status_code: int, value: T)`. `Status[None]` is the correct return type for `Status(200, None)`. Verified pre-implementation; no fallback needed.

Error responses (`HttpError`) stay as-is — these are operational errors (rate limit, format unsupported, storage failure), not the structured 422/blocked responses Step 3.2 introduced for delete/restore. No frontend classifier depends on shape.

### `media/api.py` — module-local helpers

```python
def _delete_media_storage_after_commit(storage_keys: list[str]) -> None: ...   # already typed
def _check_rate_limit(user_id: int) -> None: ...                                # already typed
def _incr_rate_limit(user_id: int) -> None: ...                                 # already typed

def _authed_user(request: HttpRequest) -> User: ...                             # NEW
def _resolve_entity(entity_type: str, slug: str) -> tuple[ContentType, MediaSupported]: ...  # NEW signature
```

`_authed_user`: mirror the [citation/api.py](../../../backend/apps/citation/api.py) pattern from Step 8 — narrow `request.user: User | AnonymousUser` to `User` via `assert not isinstance(request.user, AnonymousUser)`. Two copies (citation + media) is fine for now — each app owns its narrowing. Docstring cross-references the citation twin and notes that [UserModel.md](UserModel.md) consolidation should collapse both into a shared helper, alongside the cast that will be needed when a custom User model lands.

`_resolve_entity`: returns `tuple[ContentType, MediaSupported]`. The current `model_class.objects` access raises `attr-defined` because `type[<LinkableModel & MediaSupported>]` doesn't carry the manager protocol. Fix per the introspection idiom: `model_class._default_manager.filter(slug=slug).first()`. No `cast`.

### `media/api.py` — `transaction.on_commit` callback

Line 346:

```python
transaction.on_commit(
    lambda keys=storage_keys: _delete_media_storage_after_commit(keys)
)
```

`Cannot infer type of lambda` (default-arg-captured lambda; same shape as the deferred [taxonomy.py](../../../backend/apps/catalog/api/taxonomy.py) entries). Replace with `functools.partial(_delete_media_storage_after_commit, storage_keys)` — same semantics (snapshot of the list at registration time), no lambda inference issue, no `# type: ignore`.

### `media/tests/*`

- `test_helpers.py`: `pm.all_media = []` and `pm.primary_media = []` trigger `attr-defined`. Use `setattr(pm, "all_media", [])` — the `getattr`-fronted prefetch-attached-attr idiom isn't typed at class level on any entity model and shouldn't be (the attr exists only on prefetched querysets, not on bare model instances).
- `test_processing.py`: `dict[str, Any]` type-arg fix on the one offending dict literal.
- `test_upload_api.py`: `file.read = lambda *a, **kw: ...` triggers `method-assign`. Use `monkeypatch.setattr(file, "read", lambda *a, **kw: ...)`.

## Steps

### Step 11.1: callees — `apps.py`, `admin.py`, `processing.py`

Pure annotation work. No public-API change.

- [apps.py](../../../backend/apps/media/apps.py): `-> None` on three functions.
- [admin.py](../../../backend/apps/media/admin.py): generic params on the three admin classes; `has_*_permission` annotations.
- [processing.py](../../../backend/apps/media/processing.py): `dict[str, Any]` for `save_kwargs`; `Image.Image` typed local in `process_original` / `generate_rendition`.

`./scripts/mypy` after each file. No `make codegen` needed (no schema changes).

### Step 11.2: `media/api.py`

Helpers first within the file, then endpoints:

1. Add `_authed_user`. Replace `request.user.id` / `request.user` reads in the three endpoints with `_authed_user(request)`.
2. Tighten `_resolve_entity` signature; switch to `_default_manager`.
3. Replace the `on_commit` lambda with `functools.partial`.
4. Annotate **one** endpoint first (`upload_media`) with `request: HttpRequest` + return type. Run `./scripts/mypy` to confirm `django_auth` doesn't trip the annotation. Catalog Step 5 already validated this combo, so expect clean — but verify before fanning out. Then annotate the other two.

**`make codegen` gate.** After step 4, regenerate `frontend/src/lib/api/schema.d.ts`. Annotations should not change the OpenAPI shape — Ninja already inferred endpoint return types from `response=`. **If the diff is non-zero, STOP** and reconcile before proceeding to tests: a non-zero diff means either (a) Ninja inferred a Form param default differently when typed, or (b) the `Status[None]` return annotation surfaces a 200 schema change. Either way, the frontend would break silently if we shipped tests on top.

Then frontend typecheck.

### Step 11.3: tests

`test_helpers.py` (`setattr`), `test_processing.py` (`dict[str, Any]`), `test_upload_api.py` (`monkeypatch.setattr`).

### Step 11.4: baseline sync

`./scripts/mypy-baseline-sync` once `./scripts/mypy` shows `new: 0`. The wrapper clears `backend/.mypy_cache` and filters unstable `--install-types` notes — the raw `mypy-baseline sync` command would produce a warm-cache baseline that disagrees with CI (see the script header for the PR #233 incident). Expected: 261 → ~222.

**Caveat on the delta.** ~39 entries clear from this app's files, but tighter signatures may surface new errors in callers (e.g. tightening `_resolve_entity`'s return from implicit `Any` to `tuple[ContentType, MediaSupported]` could fire in any caller that was relying on `Any`-flow into a non-`MediaSupported`-shaped use). No callers exist outside this file today, but the same caveat applies to `process_original` / `generate_rendition` if their `Image.Image`-typed locals leak into return-shape changes (they shouldn't — the dataclass return wraps them). If the delta is materially worse than ~222, the plan is to investigate before syncing the baseline, not to grandfather new entries in.

## Open questions

Decision points where I lean one way but want explicit confirmation before writing code.

### Q1. `_resolve_entity` manager access — `_default_manager` vs `cast(type[Model], model_class).objects`

The `attr-defined` error fires because `type[<LinkableModel & MediaSupported>]` is the intersection type django-stubs computes for `get_linkable_model(...)` filtered by `issubclass(..., MediaSupported)`, and neither mixin declares `.objects`.

- **Lean: `_default_manager`.** Already the project's introspection-idiom convention (Step 6 used it in `apps/core/models.unique_slug`; Step 4 used it generally). One-line change, no `cast`.
- **Risk:** if any concrete catalog model overrides `objects` with a custom manager whose extra methods this code path calls, `_default_manager` won't expose them. Current usage is `.filter(slug=...).first()` only — safe.

### Q2. `transaction.on_commit` callback — `functools.partial`

Decided: replace the default-arg-captured lambda with `functools.partial(_delete_media_storage_after_commit, storage_keys)`. Same semantics (eager capture of `storage_keys`), no `# type: ignore`, no lambda inference issue. The single lambda in this file isn't a "codebase convention" worth preserving.

### Q3. `all_media` / `primary_media` test attr — `setattr` vs class-level annotation

Two ways to silence `attr-defined` on `pm.all_media = []`:

- **`setattr(pm, "all_media", [])`** — localized to the test, no model surface change. Magic string is fine: the helpers already use `getattr(entity, "all_media", None)` so the contract is already string-keyed.
- **Class-level `all_media: list[EntityMedia]` on every `MediaSupported` subclass** — types the prefetch-attached attr at the model. But: (a) it lies — bare model instances don't have the attr, only prefetched ones do; (b) `MediaSupported` is a mixin without a Django field for `all_media`, so this would be a phantom annotation; (c) every entity class would need it (Title, MachineModel, Manufacturer, Person, …).

- **Lean: `setattr`.** The annotation route encodes a runtime fiction.

### Q4. `save_kwargs: dict[str, Any]` vs split kwargs at call site

Pillow's `image.save(**kwargs)` accepts a wide-open kwargs space. Inlining the call:

```python
if fmt.optimize and fmt.quality is not None:
    image.save(buf, format=encoded_format, quality=fmt.quality, optimize=True)
elif fmt.optimize:
    image.save(buf, format=encoded_format, optimize=True)
elif fmt.quality is not None:
    image.save(buf, format=encoded_format, quality=fmt.quality)
else:
    image.save(buf, format=encoded_format)
```

- **Lean: keep `dict[str, Any]`** with a one-line comment naming Pillow's API as the constraint (idiom #3). The branched form bloats the function for no type-safety win — Pillow's `.save` stub is itself loose.

### Q5. Endpoint return type for 200-with-no-body — `Status[None]`

Decided. Verified pre-write: `class Status(Generic[T])` in [ninja/responses.py:25](../../../backend/.venv/lib/python3.14/site-packages/ninja/responses.py). Use `-> Status[None]` directly. No `tuple[int, None]` fallback needed.

### Q6. `HttpError` vs typed 4xx error unions

Step 3.2 introduced `SoftDeleteBlockedSchema | AlreadyDeletedSchema` etc. for delete/restore endpoints because the frontend's `delete-flow.ts` classifier dispatches on response shape. The media endpoints raise `HttpError` for: rate-limit (429), format-unsupported (400), file-too-large (400), entity-unknown (400/404), claim-validation-failed (400), processing-failed (400), storage-failed (500), DB-failed (500), asset-not-found (404).

- **Lean: keep `HttpError`.** No frontend classifier depends on body shape; `{"detail": "..."}` is sufficient. Migration would be schema work without a reasoning win.
- **Counter:** if upload UX gains shape-dependent error handling later (e.g. distinguishing rate-limit from format-unsupported by structured field instead of HTTP status), this would become Step 3.2-style work. Defer until that need exists.
