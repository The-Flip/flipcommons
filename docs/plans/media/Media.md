# Media Support Plan

This document outlines photo and video upload and storage support for this project. Decisions are informed by reviewing the Flipfix sister project's production media system (which AIs are encouraged to inspect at ~/dev/flipfix/) and adapting its patterns to this project's claims-based architecture. The database will be reset; no migration/backfill is needed.

## Goals

- Allow this project users to upload images (initial PR) and video (follow-up) for MachineModel (initial PR) then all catalog entity types (follow-up).
- Keep third-party media external. OPDB, IPDB, Fandom, Wikidata images stay where they are (`extra_data["opdb.images"]`, etc.). Never copy external images into this project storage.
- Keep catalog truth claims-based. Media attachments, categories, and primary flags go through provenance.
- Separate catalog truth from storage infrastructure. Binary files, renditions, storage keys are infrastructure.
- Store relative object keys, not origin-specific URLs. CDN adoption becomes a config change.
- Keep the initial PR small: machine model images only.

## Non-Goals For Initial PR

- No support for video upload.
- No support for media on any catalog entity other than MachineModel.
- No CDN cutover.
- No presigned direct-to-S3 uploads. This will be added in video follow-up.
- No async task queue. This will be added when video transcoding requires it.
- No sha256 dedupe. This is a potential follow-up.

## Ownership Boundary

The media system is for only for media that this project has a clear license to display, whether end users have uploaded it (and granted this project license to use it), or the images are actually owned by The Flip museum, which owns this project.

- Uploaded media goes into `MediaAsset` + `MediaRendition`.
- Renditions we generate go into our storage.
- This project serves URLs for those files.

Third-party media stays outside:

- OPDB images stay as OPDB image metadata in `extra_data`.
- IPDB images stay as IPDB image metadata in `extra_data`.
- Fandom/Wikidata images stay as image metadata in `extra_data`.

This project will not download, transcode, re-host, proxy or pretend to own third-party files. There's legal issues with doing so.

UI and APIs prefer uploaded media first, then fall back to third-party referenced media.

## App Structure

All media models, APIs, and processing live in a new **`media` app** (`backend/apps/media/`). Media is a distinct domain — storage infrastructure, file processing, upload endpoints — and is big enough to warrant its own app rather than being folded into `catalog` or `core`.

Wiring between apps:

- **`media` app owns**: `MediaAsset`, `MediaRendition`, `EntityMedia`, image processing module, upload API endpoint.
- **`catalog` app owns**: `media_attachment` claim namespace registration (in `catalog/claims.py`, alongside credits/themes/etc.) and media claim resolution logic (in `catalog/resolve/`, since it already orchestrates all relationship resolution).
- **`EntityMedia`** uses a GenericFK to target catalog entities, so the `media` app has no import dependency on catalog models.

This mirrors how `provenance` works today — provenance owns the Claim model, catalog registers namespaces and runs resolution. Same pattern: media owns the storage/attachment models, catalog registers the claim namespace and resolves them.

## Data Model

### Three-Layer Architecture

1. **`MediaAsset`** — One logical uploaded media item (infrastructure, not claim-resolved).
2. **`MediaRendition`** — One physical stored file for that asset: original, thumbnail, display-size, and future video renditions (infrastructure, not claim-resolved).
3. **`EntityMedia`** — The resolved catalog attachment row linking a catalog entity to a media asset with category and primary metadata (catalog truth, claim-resolved).

This separation matters:

- `MediaAsset` and `MediaRendition` are infrastructure records, not catalog claims.
- `EntityMedia` is catalog truth and is materialized from claims.
- Third-party media references remain in claim-backed `extra_data`, not in `MediaAsset`.

### `MediaAsset`

One logical uploaded media item. Infrastructure, not a catalog claim. Tracks the uploaded file's metadata (`kind`, `original_filename`, `mime_type`, `byte_size`, dimensions), lifecycle `status` (`ready`/`processing`/`failed`), and `uploaded_by` (`on_delete=PROTECT`). Identified by `uuid`. For images, assets go straight to `ready` or `failed` (synchronous processing). The `processing` status is reserved for video (follow-up).

Notes:

- Not a catalog claim. Pure infrastructure.
- `uploaded_by` is required (not nullable, `on_delete=PROTECT`). Every asset is a user upload.
- `duration_seconds` is deferred to the video follow-up (Follow-Up 1), along with its constraints.
- The `status` field exists for video support later. For images, assets go straight to `ready` or `failed` (synchronous processing). The `processing` status is reserved for video.
- No `sha256` field in the initial implementation. Dedupe is a potential far-future follow-up.

### `MediaRendition`

One physical stored file for a `MediaAsset`. Each image upload produces three renditions: `original`, `thumb`, `display`. The `rendition_type` field is constrained to these values at the DB level — adding video types (`poster`, `mp4`, etc.) requires a migration.

Notes:

- No `storage_key` field — storage paths are derived at runtime by `build_storage_key()` (Phase 3) from `asset.uuid` + `rendition_type`. The model layer knows nothing about the storage layer.
- Shipping the rendition table now means video support only needs to add new rows, not new columns. The `rendition_type` CHECK constraint will need a migration to add `poster`, `mp4`, etc. — intentionally strict per `docs/DataModeling.md` ("start tight, relax later").
- For images, every successful upload creates exactly three renditions: `original`, `thumb`, `display`.

### `EntityMedia`

Resolved catalog attachment linking an entity to a `MediaAsset` via GenericFK. Carries `category` (entity-type-specific vocabulary, nullable) and `is_primary` flag.

Key constraints: one attachment per entity-asset pair; at most one primary per entity per category; at most one uncategorized primary per entity (separate constraint needed because PostgreSQL treats `NULL != NULL` in unique indexes).

Notes:

- `EntityMedia` is materialized from claims, not hand-edited.
- Application-level validation (Phase 4): `category` must be in the allowed set for the entity type (`MEDIA_CATEGORIES` registry); `asset.kind` must be compatible with the category.

### Implementation details

All three models, their fields, constraints, and tests are in `backend/apps/media/`. See `models.py` for the authoritative schema. See `tests/test_db_constraints.py` for DB constraint coverage.

## Claims Design

Media attachment facts go through provenance. This follows the existing relationship-claim pattern in `catalog/claims.py`.

### Claim Shape

Add a new relationship namespace `media_attachment`. The claim identity is the `MediaAsset` PK. The value dict contains:

```python
{
    "media_asset": <asset_pk>,
    "category": "backglass",       # nullable
    "is_primary": True,
    "exists": True,
}
```

The `claim_key` encodes the identity: `media_attachment|media_asset:<pk>`.

### Resolution

Resolution works in two stages:

1. **Per-attachment**: Resolve the winning claim per attachment identity (standard claim resolution — highest priority, most recent).
2. **Primary enforcement**: Within the resolved set, enforce primary constraints deterministically. If two resolved attachments both claim `is_primary=true` for the same `(entity, category)`, pick the highest-priority winner for that category and materialize the others as non-primary.

This keeps the claims model coherent without treating primary selection as a separate mutable side channel.

### Registration

Register the namespace in `catalog/claims.py` alongside existing relationship namespaces:

```python
# In ENTITY_REF_TARGETS or a similar registration:
"media_attachment": [RefKey("media_asset", MediaAsset)],
```

And call `register_relationship_targets()` from `CatalogConfig.ready()` as usual.

## Category Registry

Image categories are entity-type-specific, not a global enum.

Initial implementation covers only `MachineModel`:

- `backglass`, `playfield`, `cabinet`, `other`

This mirrors OPDB's useful structure. The constraint is "at most one primary image per `(model, category)`".

Follow-up category sets (guesses, not commitments):

- `Manufacturer`: `logo`, `building`, `product`, `other`
- `CorporateEntity`: `logo`, `building`, `document`, `other`
- `Person`: `portrait`, `signature`, `other`
- `Title`: `logo`, `hero`, `other`
- Other entity types as needed.

Implementation: a `MEDIA_CATEGORIES` class variable on the `MediaSupported` mixin (in `core/models.py`). Each model sets its own list of allowed category strings (e.g. `MEDIA_CATEGORIES = ["backglass", "playfield", "cabinet", "other"]`). The upload endpoint reads `model_class.MEDIA_CATEGORIES` directly — no separate registry. Validated at upload time (Phase 3) and at claim assertion time (Phase 4) — reject unknown categories immediately, don't let them into the claims table.

## Upload Flow (Images)

Upload through Django, not presigned URLs. For images (typically 1-10MB), this is one round trip and avoids the complexity of presigned URL flows, S3 CORS configuration, and partial-upload error handling. Since we use django-storages with S3 from day one, the files end up in S3 regardless — switching to presigned URLs later changes the upload _path_ but not where files are stored. No migration needed.

Upload and attach happen in a single request. The user is always uploading _to_ a specific entity with a specific category — there's no use case for uploading an image without immediately attaching it. Combining them avoids orphaned assets and simplifies the UX. Each HTTP request handles one file; the frontend sends parallel requests when the user selects multiple files.

### Flow

1. **Client** POSTs multipart form to `POST /api/media/upload/` with one image file, target entity (`entity_type` + `slug`, e.g. `"machine-model"` + `"eight-ball"`), category, and is_primary flag. When the user selects multiple files, the frontend sends one request per file concurrently.
2. **Backend** validates the file (type, size, decodability) and the attachment metadata (valid entity, valid category for entity type).
3. **Backend** processes the image synchronously: generates `thumb` and `display` renditions using Pillow (EXIF transpose, LANCZOS resize, WebP output).
4. **Backend** uploads all three files (original, thumb, display) to storage via django-storages.
5. **Backend** creates `MediaAsset` (status=`ready`) + 3 `MediaRendition` rows in a single database transaction. (Phase 3 stops here; Phase 4 adds claim creation inside this transaction.)
6. **Resolution** materializes `EntityMedia` (Phase 4).
7. **Backend** returns the asset UUID, rendition URLs, and attachment metadata.

Steps 1-7 are one synchronous HTTP request. No task queue, no polling, no "pending" state for images.

### Atomicity and Failure Handling

The upload flow must not leave orphaned state on failure:

- **Processing failure** (Pillow can't generate renditions): return error, nothing written to S3 or DB.
- **S3 write failure** (one of the three uploads fails): clean up any S3 objects already written, return error, nothing written to DB.
- **DB write failure** (transaction fails after S3 uploads succeed): clean up all S3 objects. DB transaction rollback handles the rows.

The key invariant: **DB rows are only created after all S3 objects are successfully written.** This means orphaned DB rows can't exist. Orphaned S3 objects (written but DB transaction failed) are cleaned up in the error handler. A periodic cleanup job for orphaned S3 objects is not needed in the initial implementation but is a reasonable follow-up if operational experience shows leakage.

### Why Synchronous Processing For Images

Flipfix processes images in `model.save()` synchronously and it works well in production. For thumbnail + display generation, Pillow processing takes under a second. Async processing would add a task queue dependency, status polling UI, and "pending" states — unnecessary complexity for images.

Async processing is reserved for video transcoding (follow-up PR), where it genuinely matters.

### Upload Validation

Strict validation on upload — reject early, reject clearly:

- **Authentication**: user must be logged in. Anonymous uploads are never allowed.
- **File presence**: request must contain exactly one file. Multi-file selection is a frontend concern — the client sends one request per file.
- **File extension**: must be in `ALLOWED_IMAGE_EXTENSIONS` (see Accepted Image Formats below). Reject unknown extensions even if the content looks valid — defense in depth.
- **Pillow decodability**: `Image.open()` must succeed. This is the real validation — catches corrupt files, truncated uploads, and non-images regardless of extension or content-type header.
- **File size**: configurable max (e.g. 20MB for images). Enforced both in Django's `DATA_UPLOAD_MAX_MEMORY_SIZE` and explicitly in the view. Return a clear error, not a generic 413.
- **Dimensions after decode**: reject degenerate images (0×0, 1×1). Set a reasonable max dimension (e.g. 20000×20000) to prevent memory bombs during processing.
- **MIME type derivation**: the Pillow-detected format is the canonical source of truth for the persisted `mime_type` on `MediaAsset` and `MediaRendition`. Client-provided content-type headers and file extensions are used for initial filtering only, never persisted.

### Accepted Image Formats

Defined once in the media app's constants module, matching flipfix's proven set:

```python
ALLOWED_IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp",  # Web-native
    ".heic", ".heif",                           # iPhone photos
    ".avif",                                    # Modern compression
    ".bmp",                                     # Legacy, converted to JPEG
}
```

| Upload format            | Preserved or converted | Output format     | Notes                                         |
| ------------------------ | ---------------------- | ----------------- | --------------------------------------------- |
| JPEG (.jpg, .jpeg)       | Preserved              | JPEG (quality=85) | Most common upload format                     |
| PNG                      | Preserved              | PNG               | Transparency preserved                        |
| WebP                     | Preserved              | WebP (quality=80) |                                               |
| AVIF                     | Preserved              | AVIF (quality=63) |                                               |
| HEIC/HEIF (.heic, .heif) | Converted              | JPEG              | iPhone default format; requires `pillow-heif` |
| GIF                      | Converted              | JPEG              | Static frame only; animated GIF not supported |
| BMP                      | Converted              | JPEG              | Legacy format                                 |

Renditions (thumb, display) are always WebP regardless of original format.

HEIC support requires `pillow-heif`, a Pillow plugin that registers HEIC/HEIF format handlers. This is the same approach flipfix uses in production.

## Image Processing

Adapted from flipfix's `core/image_processing.py` — a production-proven Pillow pipeline.

### Processing Steps

1. Validate image type and decodability (Pillow `Image.open()`).
2. EXIF orientation correction (`ImageOps.exif_transpose()`).
3. Extract dimensions, mime type, byte size.
4. Generate two renditions:
   - **`thumb`**: max 400px longest side, WebP output. For grid/list views.
   - **`display`**: max 1600px longest side, WebP output. For detail pages.
5. Save original in uploaded format, renditions in WebP.

### Format Handling (from flipfix)

- **Original**: web-native formats preserved as-is; non-web formats (HEIC/HEIF, BMP, GIF) converted to JPEG. PNG with transparency stays PNG regardless. See the Accepted Image Formats table for the full mapping.
- **Renditions** (thumb, display): always WebP output.
- LANCZOS resampling for resize.
- Pillow `optimize` flag for JPEG/PNG.

### Dimensions

- `THUMB_MAX_DIMENSION = 400` (smaller than flipfix's 800 — this project grid items are smaller)
- `DISPLAY_MAX_DIMENSION = 1600` (smaller than flipfix's 2400 — web display, not print)

These can be tuned after seeing real usage.

## Storage

### S3-compatible object storage + CDN

Use S3-compatible object storage as the backend, accessed through `django-storages`. Production uses **iDrive e2** for the bucket, with **Bunny CDN** in front at `media.flipcommons.org`.

Architecture:

- **Private origin.** The media bucket is private. The CDN authenticates to the origin with S3 access key + secret. Nothing in the bucket is publicly readable directly; clients must come through the CDN.
- **Custom domain serving.** Public URLs are `https://media.flipcommons.org/<storage-key>`. Django is not in the serving path.
- **US-Central origin proximity.** The bucket lives in iDrive's Chicago datacenter, close to the museum's location and the CDN's Chicago PoP. This location was chosen so that cold reads to Chicago users are fast.
- **Provider-neutral wiring.** `MEDIA_STORAGE_BUCKET`, `MEDIA_STORAGE_ENDPOINT`, `MEDIA_STORAGE_REGION`, `MEDIA_STORAGE_ACCESS_KEY`, `MEDIA_STORAGE_SECRET_KEY`, `MEDIA_PUBLIC_BASE_URL`. Swapping to another S3-compatible vendor (Wasabi, Backblaze B2, etc.) is an env-var change plus a one-time bucket copy. Nothing in the application code or storage keys names a vendor.
- **Hosting-independent.** Object storage is durable and decoupled from Railway. If we change app hosting, media doesn't move.

### Cost Expectations

Rough order-of-magnitude estimate at near-term scale. Pricing varies by provider; verify current numbers before relying on these.

Assumptions:

- `5,000` uploaded images.
- Each upload creates `3` stored objects: `original`, `thumb`, `display`.
- `60` image reads per hour on average.
- Storage dominates cost; request volume and egress at this scale do not.

Estimated monthly storage cost at `5,000` uploaded images, assuming pay-per-GB pricing in the $0.004–$0.015/GB-month range typical of low-cost S3-compatible providers:

| Average stored size per uploaded image set (`original` + `thumb` + `display`) | Total stored | Estimated monthly cost |
| ----------------------------------------------------------------------------- | ------------ | ---------------------- |
| `1.4 MB`                                                                      | `~7.0 GB`    | `~$0.05`               |
| `3.4 MB`                                                                      | `~16.8 GB`   | `~$0.10`               |
| `5.4 MB`                                                                      | `~26.5 GB`   | `~$0.20`               |
| `10.4 MB`                                                                     | `~50.9 GB`   | `~$0.40`               |

Practical takeaway:

- For the first few thousand images, total monthly cost is well under a dollar.
- Read traffic at this scale is negligible against typical free tiers and per-request pricing.
- The real long-term cost driver is total stored bytes, especially large originals or future video assets, not image serving.

### Key Generation

Storage keys are derived by a `build_storage_key()` utility function (built in Phase 3, not on the model) from the asset UUID and rendition type. The storage backend stores the file at whatever key this project provides — it has no say in naming. The storage prefix and rendition-to-filename mapping live in the media app's storage module, not on the ORM model.

Format: `catalog-media/{asset_uuid}/{rendition_segment}`

Where `rendition_segment` depends on the rendition type:

| Rendition type | `rendition_segment`          | Example                                        |
| -------------- | ---------------------------- | ---------------------------------------------- |
| `original`     | `original/{stored_filename}` | `catalog-media/abc-123/original/backglass.jpg` |
| `thumb`        | `thumb.webp`                 | `catalog-media/abc-123/thumb.webp`             |
| `display`      | `display.webp`               | `catalog-media/abc-123/display.webp`           |

`stored_filename` is the uploaded filename with the extension replaced by the actual output format when `process_original()` converts it (e.g., `backglass.bmp` → `backglass.jpg`). When the format is preserved, the filename is unchanged. `MediaAsset.original_filename` always stores the user's uploaded filename (for display/audit); the storage key reflects the actual stored format.

The `catalog-media/` prefix is defined in the media app's storage module, not a DB constraint. This keeps the storage location configurable without schema changes.

The asset UUID guarantees uniqueness across uploads. Rendition types other than `original` have fixed filenames since the format is always WebP.

Future video rendition types (follow-up):

| Rendition type | `rendition_segment`               |
| -------------- | --------------------------------- |
| `poster`       | `poster.webp`                     |
| `mp4`          | `master.mp4`                      |
| `hls_playlist` | `hls/master.m3u8`                 |
| `hls_segment`  | `hls/{resolution}/segment-{n}.ts` |

### URL Generation

- Storage keys are computed at runtime by `build_storage_key()` — nothing stored in the database.
- Public URL = `settings.MEDIA_PUBLIC_BASE_URL + build_storage_key(...)`.
- `MEDIA_PUBLIC_BASE_URL` points at `media.flipcommons.org`, which the CDN serves from the private bucket.

### Local Development

Use MinIO (S3-compatible, runs in Docker) or Django's default `FileSystemStorage` with a local `MEDIA_ROOT`. The storage key pattern is the same either way — only the backend differs.

## Serving

Django is not the hot-path media file server.

### API Response Shape

APIs return media metadata plus public URLs for ready renditions:

```json
{
  "uploaded_media": [
    {
      "asset_uuid": "abc-123",
      "kind": "image",
      "category": "backglass",
      "is_primary": true,
      "renditions": {
        "thumb": "https://media.flipcommons.org/catalog-media/abc-123/thumb.webp",
        "display": "https://media.flipcommons.org/catalog-media/abc-123/display.webp",
        "original": "https://media.flipcommons.org/catalog-media/abc-123/original/backglass.jpg"
      }
    }
  ],
  "hero_image_url": "...",
  "thumbnail_url": "..."
}
```

### Fallback Policy

Uploaded media from `EntityMedia` is always displayed — no license gating. Licensing for user-generated content is deferred until the legal picture is clearer; claims are created with `license=None`. A future UGC license can be added without migration (see Follow-Up 5).

1. Prefer uploaded media from `EntityMedia` (always shown).
2. If no uploaded media exists for the needed slot, fall back to third-party referenced media from `extra_data` (`opdb.images`, `ipdb.image_urls`). The existing Constance display threshold applies to third-party media only.

The existing `_extract_image_urls()` helper in `catalog/api/helpers.py` handles the fallback. Phase 5 adds an `if EntityMedia` check before falling through to the license-filtered third-party path.

### Ordering

API responses return media in deterministic order: primary first, then by `created_at` ascending. This applies both to the `uploaded_media` list in entity detail responses and to any future media listing endpoint. Pagination is not needed in the initial implementation — MachineModel images will be single-digit counts per entity.

## Authorization

For the initial implementation, media follows the same rules as all other claim types:

- **Upload**: any authenticated user. Anonymous uploads are never allowed.
- **Attach / detach / set primary / change category**: any authenticated user, same as credits, themes, and other claim types. Claims go through provenance, and resolution picks winners by priority.
- **Delete underlying asset**: only the original uploader or staff can delete a `MediaAsset`. Deletion is only allowed when the asset has no active attachment claims on any entity (see Deletion Policy below).

The broader user-role/permission landscape (tiered permissions, who can retract whose claims, moderation workflows) is a cross-cutting concern that applies to all claim types, not just media. That is a separate follow-up discussion.

## Rate Limits

Basic per-user upload rate limiting to protect storage costs and moderation workload:

- Per-user upload limit: `MAX_UPLOADS_PER_HOUR = 60`, defined once in the media app's constants module.
- Enforced at the upload endpoint. Return 429 with a clear error message including when the user can retry.
- Implementation: Django cache-based rate limiting (no new infrastructure).

Per-entity attachment limits and more sophisticated quota systems are deferred until real usage patterns emerge.

## Deletion Policy

Media deletion has two distinct operations:

### Detach (deactivate attachment claim)

Deactivating a `media_attachment` claim removes the `EntityMedia` row on next resolution. The underlying `MediaAsset` and its S3 files are **not** deleted — the asset may be attached to other entities, and the claim history is preserved in provenance.

### Delete asset

Deleting a `MediaAsset` is a hard delete that removes:

1. All `MediaRendition` rows (CASCADE).
2. All S3 objects for those renditions.
3. The `MediaAsset` row itself.

Preconditions for asset deletion:

- The asset must have **no active attachment claims** on any entity. If active claims exist, the delete request is rejected with an error listing the entities.
- Only the original uploader or staff can delete.

There is no soft-delete or tombstone for `MediaAsset`. Assets are infrastructure, not catalog truth — provenance is preserved in the claim history (deactivated claims remain in the database), not in the asset row.

## Frontend Architecture

### Component Decomposition

All media UI is built as decomposed SvelteKit components with logic extracted to TypeScript files for testability. Interaction patterns are adapted from flipfix (upload -> poll -> update) but implemented in Svelte 5 runes mode.

#### TypeScript Modules (logic, testable without DOM)

- **`media-upload.ts`** — Upload state machine for multi-file uploads: per-file validation, per-file progress tracking, batch API calls. Exports reactive state (file list with individual statuses) and action functions.
- **`media-api.ts`** — API client functions for media endpoints (upload, delete).

Types for media API responses come from the existing OpenAPI-generated `schema.d.ts` via `make codegen`.

#### Svelte Components (thin UI wrappers)

- **`MediaUploadButton.svelte`** — Paperclip icon button that opens the native file picker with `<input multiple>` for multi-file selection. Includes category selection. Calls into `media-upload.ts`. One request per file.
- **`MediaGrid.svelte`** — Grid of media items with delete and set-primary actions.
- **`MediaCard.svelte`** — Single media item card (thumbnail, category badge, primary indicator).
- **`HeroImage.svelte`** — Detail page hero image with uploaded-first/external-fallback logic.

#### Interaction Flow (Image Upload)

1. User selects category and clicks the paperclip button to open the native file picker, which allows selecting multiple files at once (`<input multiple>`).
2. `media-upload.ts` validates each file client-side (type, size). Invalid files are rejected with per-file error messages before any network requests.
3. `media-upload.ts` sends one `POST /api/media/upload/` request per valid file concurrently, each with the target entity, category, and primary flag. Per-file progress is tracked independently.
4. `MediaGrid` updates as each upload completes. Partial failures (some files succeed, some fail) show per-file status so the user knows which files need to be re-uploaded.

## Testing Strategy

### Patterns Adapted From Flipfix

#### Test Utilities

- **`TemporaryMediaMixin`** — Creates a temp directory for `MEDIA_ROOT`, cleans up after test class. Adapted from flipfix's `core/test_utils.py`.
- **`create_uploaded_image()`** — Creates a PIL Image as a `BytesIO` with `.name` attribute, suitable for Django upload testing. Directly from flipfix.
- **`MINIMAL_PNG`** — Minimal valid PNG bytes for tests that need valid image data without Pillow.

#### Backend Tests

- **Image processing unit tests**: Resize, EXIF transpose, format conversion, transparency handling. Test the processing module in isolation (no Django models).
- **Upload API tests**: POST valid/invalid files, check MediaAsset + MediaRendition creation, verify S3 storage keys.
- **Claim + resolution tests**: Assert media attachment claims, resolve, verify EntityMedia rows. Test primary constraint enforcement.
- **API response tests**: Verify uploaded-first fallback to external. Verify rendition URLs in response.
- **File validation tests**: Rejected file types, oversized files, corrupt files.

#### Frontend Tests

- **TypeScript module tests** (vitest): Test `media-upload.ts` state machine, `media-api.ts` API calls (mocked fetch), validation logic. These are the high-value tests — logic without DOM.
- **Component tests** (vitest + testing-library): Basic render tests for `MediaGrid`, `MediaCard`. Not exhaustive — the logic is in the TypeScript modules.

### Mocking Strategy

- **S3 storage**: Use `django.core.files.storage.InMemoryStorage` or `TemporaryMediaMixin` with `FileSystemStorage` in tests. Never hit real S3.
- **Image processing**: Test the processing module with real Pillow (it's fast). Don't mock Pillow.
- **API calls in frontend**: Mock `fetch` in vitest for `media-api.ts` tests.

## Django Configuration

### New Dependencies

- `django-storages[s3]` — S3 storage backend.
- `Pillow` — Image processing (may already be present).
- `pillow-heif` — HEIC/HEIF support for Pillow (iPhone photos). Registers format handlers on import.
- `boto3` — S3 client (pulled in by django-storages).

### Settings

```python
# Storage — S3-compatible file storage provider
MEDIA_PUBLIC_BASE_URL = os.environ.get("MEDIA_PUBLIC_BASE_URL", "/media/")

if os.environ.get("MEDIA_STORAGE_BUCKET"):
    # Production: S3-compatible provider (configured via env vars)
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    }
    AWS_STORAGE_BUCKET_NAME = os.environ["MEDIA_STORAGE_BUCKET"]
    AWS_S3_REGION_NAME = os.environ.get("MEDIA_STORAGE_REGION", "auto")
    AWS_S3_ENDPOINT_URL = os.environ["MEDIA_STORAGE_ENDPOINT"]
    AWS_ACCESS_KEY_ID = os.environ["MEDIA_STORAGE_ACCESS_KEY"]
    AWS_SECRET_ACCESS_KEY = os.environ["MEDIA_STORAGE_SECRET_KEY"]
else:
    # Local dev: filesystem storage
    STORAGES["default"] = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    }
    MEDIA_ROOT = BASE_DIR / "media"
```

## Implementation Phases

The work is broken into reviewable phases. Each phase is one or more commits with a pause for review before proceeding.

After each phase, we review what we learned during implementation and update the remaining phases in this plan accordingly. Plans don't survive contact with code — early phases will surface questions and constraints that affect later phases.

### Phase 1: Models + Constraints + Migration — DONE

All three models live in `backend/apps/media/models.py` with a bunch of DB-level constraints and read-only admin. Things later phases should know:

- `MediaRendition` has a `RenditionType` TextChoices enum (`original`, `thumb`, `display`) with a CHECK constraint. Adding video rendition types (`poster`, `mp4`, etc.) requires a migration to relax this constraint.
- `MediaRendition` has no `storage_key` field. Storage paths are derived at runtime from `asset.uuid` + `rendition_type` by a `build_storage_key()` utility (built in Phase 3).
- `MediaRendition` is identified by `uuid` (not a storage path). URLs are computed, not stored.
- `EntityMedia.object_id` is `PositiveBigIntegerField` (matches `BigAutoField` PKs). So is `Claim.object_id` (updated in this phase).
- `uploaded_by` uses `on_delete=PROTECT`. Asset deletion must be handled explicitly.
- Since `MediaRendition` has no `storage_key` field, storage key validation (including whitespace) lives in the `build_storage_key()` utility (Phase 3), not in model constraints.

### Phase 2: Image Processing Module + Tests — DONE

Pure library code in `backend/apps/media/processing.py` and `constants.py`. Things later phases should know:

- `process_original(data: bytes)` takes only bytes — no filename parameter. The output extension comes from `ProcessedImage.format_ext`; the filename stem is the caller's concern when building storage keys.
- `generate_rendition` handles mode conversion (CMYK, palette → RGB) before WebP encoding. Phase 3 doesn't need to worry about incompatible color modes.
- `validate_image` checks dimensions from the header before `.load()` to avoid allocating memory for oversized images. Follow this open-then-check-then-decode pattern.
- `ImageOps.contain()` upscales small images by default. `generate_rendition` guards against this — only calls `contain()` when a dimension exceeds the max.
- `check_codec_support()` returns a dict of codec availability (`heic`, `heif`, `avif`). Phase 3's upload endpoint should call this for pre-flight checks on codec-dependent extensions.
- pillow-heif is registered in `MediaConfig.ready()` along with an AVIF availability check. Both log warnings at startup if unavailable.

### Phase 3: Storage Config + Upload API + Tests — DONE

Storage infrastructure in `backend/apps/media/storage.py`, upload endpoint in `backend/apps/media/api.py`, S3-compatible storage config in `backend/config/settings.py`. Things later phases should know:

- The upload endpoint accepts `entity_type` (kebab-case, e.g. `"machine-model"`) + `slug`, not Django ContentType PKs. Entity type resolution strips hyphens and looks up via `ContentType.objects.get(model=...)` — no registry or map. Any model inheriting `MediaSupported` is automatically a valid target.
- Category validation reads `model_class.MEDIA_CATEGORIES` (a `ClassVar[list[str]]` on the `MediaSupported` mixin in `core/models.py`). Each model declares its own allowed categories. No central registry — adding media categories to a new entity means setting `MEDIA_CATEGORIES` on its class.
- The endpoint creates `MediaAsset` + 3 `MediaRendition` rows but does **not** create `EntityMedia` or claims. Validated attachment metadata (`entity_type`, `slug`, `category`, `is_primary`) is echoed in the response. Phase 4 adds claim creation inside the upload endpoint's existing DB transaction.
- `MediaAsset.mime_type` and `MediaAsset.byte_size` both describe the stored original (after format conversion), not the raw upload. For a BMP upload converted to JPEG, `mime_type` = `"image/jpeg"` and `byte_size` = the JPEG size. The raw upload filename is preserved in `MediaAsset.original_filename`.
- `build_storage_key()` derives paths from `asset.uuid` + `rendition_type`. It verifies the storage backend used the exact key requested (detects silent renames by S3Boto3Storage). Storage keys use sanitized ASCII filenames — the user's original filename is preserved on the asset, not in the storage path.
- Storage config uses provider-neutral env vars (`MEDIA_STORAGE_BUCKET`, `MEDIA_STORAGE_ENDPOINT`, etc.). Falls back to `FileSystemStorage` when no bucket is configured. Tests use `InMemoryStorage`.
- Local dev `FileSystemStorage` writes to `MEDIA_ROOT` but Django doesn't serve those files — no media URL route exists yet. Phase 5 adds `static(MEDIA_URL, ...)` URL wiring.
- Rate limiting is best-effort (file-based cache, per user ID, `MAX_UPLOADS_PER_HOUR`). Only successful uploads consume quota — failed validation doesn't count. Not atomic under concurrent requests; acceptable for an abuse-prevention guardrail.

### Phase 4: Claims Namespace + Resolver + Wire Into Upload + Tests — DONE

`media_attachment` claim namespace in `catalog/claims.py`, generic resolver in `catalog/resolve/_media.py`, wired into upload endpoint, `resolve_model()`, and `resolve_machine_models()`. Things later phases should know:

- Category validation lives in `build_media_attachment_claim()` in `catalog/claims.py`. Phase 3's `_validate_category()` was deleted — the helper is now the single validation point. It raises `ValueError`; the upload endpoint catches and converts to `HttpError(400)`.
- No license on claims or `EntityMedia` — deferred until the legal picture for user-generated content is clearer. Claims are created with `license=None`. Phase 5 should always display uploaded media from `EntityMedia` regardless of the Constance license threshold.
- The resolver is generic across entity types (operates on ContentType, not hardcoded to MachineModel). Adding media to a new entity type requires only inheriting `MediaSupported` and setting `MEDIA_CATEGORIES` — no resolver changes.
- The resolver is integrated into `resolve_model()` (single-entity, after other relationships) and `resolve_machine_models()` (bulk orchestration). Any code path that calls `resolve_model()` automatically resolves media.
- Primary enforcement: within each `(entity, category)` group, highest priority wins; ties broken by most recent `created_at` (last-upload-wins when all claims are same priority).
- **Known race**: Concurrent uploads targeting the same `(entity, category)` with `is_primary=True` can both try to create a primary `EntityMedia` row. The second to commit hits the partial unique index and gets a 500. Narrow (requires two simultaneous primary uploads to the same slot), retryable, not worth fixing for the initial PR. If it becomes a real problem, add `SELECT FOR UPDATE` on the target entity's `EntityMedia` rows before resolving.

### Phase 5: API Response Changes + Tests — DONE

Uploaded-first fallback in `thumbnail_url` / `hero_image_url`, local dev media serving, tests. Things later phases should know:

- `thumbnail_url`, `hero_image_url`, and `image_attribution` use uploaded-first fallback. Detail response also includes `uploaded_media: list[{asset_uuid, category, is_primary, renditions: {thumb, display}}]` with all ready `EntityMedia` rows.
- `_uploaded_image_urls()` in `catalog/api/helpers.py` picks backglass first, then any primary. Category priority is hardcoded, not configurable per entity type.
- `_extract_image_urls()` and `_extract_image_attribution()` gained a `primary_media` keyword param (defaults to `None` for backward compatibility). Existing callers outside the two serializers are unaffected.
- `MachineModel` now has `entity_media = GenericRelation("media.EntityMedia")`. Other entity types that gain media support will need the same GenericRelation.
- The list queryset prefetches `entity_media` filtered to `is_primary=True, asset__status="ready"` with `to_attr="primary_media"`. The detail queryset prefetches all ready media (`to_attr="all_media"`) and derives `primary_media` in Python.
- `MEDIA_URL = MEDIA_PUBLIC_BASE_URL` is set in settings. `static(MEDIA_URL, ...)` is wired in `urls.py` behind `DEBUG`.
- Rendition URL construction only needs `asset.uuid` for thumb/display (fixed filenames). The original rendition URL is **not exposed** — it would require the stored filename, which is derived at upload time but not persisted on `MediaRendition`. If a download link is needed later, either add `stored_filename` to `MediaRendition` or reconstruct from `MediaAsset.original_filename` + `mime_type`.

### Phase 6: Frontend Components

Run `make codegen` to generate frontend types from the updated detail schema.

- `MediaUploadButton.svelte`, `MediaGrid.svelte`, `MediaCard.svelte`, `HeroImage.svelte`.
- `media-upload.ts`, `media-api.ts` TypeScript modules.
- Frontend tests: TypeScript module tests (vitest).

### Excluded From All Phases

- Videos.
- Non-MachineModel entity media UIs.
- Presigned direct-to-S3 uploads.
- CDN setup.
- Import migration from `extra_data` media.
- sha256 dedupe.
- Async task queue.

## Follow-Up Work

### Follow-Up: Other Entity Types

- Manufacturer, CorporateEntity, Person, Title, Series, Franchise, System, Location media UIs.
- Entity-specific category registries.

### Follow-Up: Video Support

Schema additions (migration required):

- Add `duration_seconds` (PositiveIntegerField, nullable) to `MediaAsset`.
- Add constraints: `duration_seconds > 0` when set; when `kind = 'image'`, `duration_seconds` must be null.

Infrastructure:

- Presigned direct-to-S3 uploads (needed for large video files — no migration, same S3 bucket).
- Async task queue (evaluate options: Celery, django-q2, or lighter-weight).
- Video transcoding worker: poster frame + MP4 fallback (adapted from flipfix's `core/transcoding.py`).
- Full status state machine: `pending` -> `processing` -> `ready` / `failed`.
- Frontend polling pattern activation in `media-upload.ts`.
- `VideoPlayer.svelte` component with transcode state handling (adapted from flipfix's video player patterns).
- HLS adaptive streaming only if demand justifies operational cost.

### Follow-Up: External Reference Cleanup

- Normalize third-party media reference shapes across OPDB/IPDB/Fandom/Wikidata.
- Centralize "uploaded first, external fallback second" media selection in one helper.

### Follow-Up: User Roles and Permissions

- Design a cross-cutting user-role/permission model that applies to all claim types (not just media).
- Topics: tiered permissions, who can retract whose claims, moderation workflows, promotion paths.
- This is a broader product decision that should be considered as a whole rather than decided piecemeal per feature.

### Follow-Up: Dedupe

- Add `sha256` field to `MediaAsset`.
- Compute hash on upload, check for existing asset.
- Decide UX: block duplicate, reuse existing asset, or warn.

## Key Design Decisions

| Decision              | Choice                                    | Rationale                                                                                                                                          |
| --------------------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Upload path           | Django relay                              | One round trip, simpler than presigned URLs. Fine for images (1-10MB). Switch to presigned for video — no migration since files are already in S3. |
| Upload + attach       | Combined endpoint                         | One request uploads, processes, and attaches. Avoids orphaned assets and simplifies UX.                                                            |
| Image processing      | Synchronous in upload request             | Under 1 second for thumb + display. Avoids task queue dependency. Flipfix proves this works in production.                                         |
| Rendition storage     | `MediaRendition` table                    | Small overhead now, avoids migration when video adds poster/mp4/hls roles.                                                                         |
| Status field          | Present but minimal                       | `ready`/`failed` for images. Full state machine activated for video follow-up.                                                                     |
| sha256 dedupe         | Deferred (far future)                     | Adds complexity without clear near-term value.                                                                                                     |
| Task queue            | Deferred (video follow-up)                | No async work needed. Evaluate options when video lands.                                                                                           |
| Rendition format      | WebP                                      | Good compression, universal browser support. AVIF deferred.                                                                                        |
| Storage + CDN         | S3-compatible private bucket + CDN        | Bucket private; CDN authenticates via S3 keys. Public URLs at `media.flipcommons.org`. Provider-neutral env vars.                                  |
| Third-party media     | Stays in `extra_data`                     | Not temporary — permanent fallback layer. API reads both uploaded and external.                                                                    |
| Category vocabulary   | Per-entity-type registry                  | Not a global enum. `MachineModel` gets `backglass`/`playfield`/`cabinet`/`other`.                                                                  |
| Frontend architecture | Logic in TypeScript, thin Svelte wrappers | Testable without DOM. Follows flipfix's interaction patterns in Svelte 5 runes.                                                                    |
