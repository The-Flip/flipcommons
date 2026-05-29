# TypeFixing

Status: DONE

Stable backend Python typing policy now lives in [Python.md](../../Python.md). This file is the historical execution plan for the type-smell cleanup.

## Background

The backend is in the process of eliminating `mypy-baseline.txt` entries. Most of that work has been mechanical — adding return annotations, typing management-command `handle()` methods, etc. But a second category keeps surfacing on review: annotations that satisfy mypy yet communicate nothing, because they reach for `Any` / `object` / untagged tuples when the real shape is already obvious from the body.

Examples that shipped, got reviewed, and had to be tightened in a follow-up PR:

- `build_edit_history(entity: Any)` where the body immediately calls `ContentType.get_for_model(entity)` and reads `entity.pk` — the author knew it was a `Model`, the annotation didn't say so.
- `ExtractionResult.match: dict[str, Any]` with a comment `# {"id": int, "name": str, "skip_locator": bool}` — the comment was doing the TypedDict's job.
- `discover_alias_types() -> tuple[tuple[type, str], ...]` — four call sites unpacking positional tuples where `AliasType(parent_model, claim_field)` would document itself.
- `list[tuple[str, str, str, str]]` in `export_entity_meta` — four same-typed fields, zero labels on what any position meant.
- `cast(Any, default_storage)` in `get_media_storage()` — active type erasure for every caller.
- Any use of `setattr` or `getattr`

These are not mypy bugs; they're design bugs that mypy can't detect because, from the type checker's perspective, a compliant annotation is a compliant annotation.

Today the only way these get found is by humans reading PRs. That doesn't scale — there are 788 baseline entries still to work through and the follow-up PR on the last type-annotation batch was the fourth in a row to find cases like the ones above. Each review round finds some and misses some; we never converge on "this module is done."

## Approach

Use ripgrep to find every instance of each smell, fix it, ship it. This is an execution plan, not a triage exercise — you are not producing a list for someone else to review. Apply the fix defined under each smell. The reviewer (human + AI) looks at the resulting PRs, not an intermediate candidate list.

Two smells need judgment: #1 ("is this one of the legitimate exception shapes?") and #5 ("are these tuple-shape occurrences semantically the same thing, or just happen to share a shape?"). The other four are mechanical.

The plan has three phases: **Phase 0** is a one-time infrastructure PR that flips ANN401 on globally and absorbs the current-state flood. **Phase 1** is the iterative chunk work — sessions pick a chunk, clear the six smells, flip the ratchet. **Phase 2** is the ratchet mechanics itself, invoked inside each chunk's final PR.

### Execution rules

**Pick a unit that fits in one session.** A unit is any chunk that the session can clear end-to-end and ratchet at the finish line — an app, a subdirectory within an app, or a single module. First session: pilot on something small (`apps/accounts/`, `apps/citation/`, or `apps/media/`) to calibrate. If the chosen chunk is too big to finish, drop to a smaller one on the next run. The plan is re-entrant: different sessions can pick different chunks; they add up.

**One chunk = one PR.** All six smells for the chunk land in a single PR, together with the Phase 2 ratchet edit. The PR's CI passing is the proof the chunk is clean.

**Shared helper fallout is allowed.** If tightening a helper in chunk A turns an untyped call in a directly-adjacent caller into a real mypy error, fix the caller in the same PR even if that caller lives just outside the nominal chunk. This is the same principle as the cross-chunk NamedTuple caller updates: don't leave the typed helper half-adopted. Keep the spillover narrow and on the same type flow; don't use it as an excuse to absorb unrelated cleanup.

**Size check before you start.** Before committing any work, run all six greps against the chunk and sum the hits across smells #1, #3, #4, #5, #6 (ignore #2 — it's cheap). If the total exceeds ~60 items, drop down to a subdirectory (e.g. `apps/catalog/resolve/` instead of `apps/catalog/`) before starting. This is the main knob for keeping the PR reviewable.

**If the PR is already oversized.** If you only discover size was a problem at PR time, split by subdirectory: each subdir becomes its own chunk with its own PR, and each PR's ratchet swap narrows the ignore glob one step (`apps/catalog/**` → add `apps/catalog/ingestion/**`, `apps/catalog/api/**`, etc. for the dirs still in progress; the cleaned subdir's glob is simply absent). Don't burn the work done — just recarve the chunk boundaries.

**Commit order within the PR.** Inside the single PR, commit in this order so reviewers can walk the history: structural rewrites first (smell #4, smell #5 — introducing NamedTuples and migrating call sites), then annotation tightenings (smells #1, #2, #3, #6), then the ratchet edit (the pyproject.toml change) as the closing commit. The order matters because smell #4 rewrites a function's return from `tuple[...]` to a NamedTuple, which _replaces_ the return annotation — if smell #3 tightened `-> Any` to `-> tuple[int, int, int]` first, that work gets thrown away when smell #4 overwrites it. (Call sites don't need re-tightening; NamedTuple supports positional unpack.) Smell #2 (`cast(Any, ...)`) is technically a call-site change rather than an annotation tightening, but it groups with the tightening commit for bundling purposes.

**Verification per PR.** Before opening, run `make lint && make test` and re-run the smell's grep scoped to the chunk's directory — the count should be at expected floor (zero, or the number of explicitly-accepted exceptions). Scoping means replacing the `backend/` path with the chunk path and keeping the same exclusion flags, e.g.:

```sh
rg -n --type py ':\s*(Any|object)\b' backend/apps/accounts/ \
  -g '!**/tests/**' -g '!**/test_*.py' -g '!**/migrations/**'
```

Should return zero hits, or only lines carrying `# noqa: ANN401` with a reason. If it returns unexplained hits, you're not done.

**Worktrees need real local deps for repo-wide verify.** If you're working in a git worktree, make sure the worktree's frontend has its own installed `node_modules` before relying on `make lint && make test`. Reusing another checkout's `node_modules` via symlink may be enough for lint, but Vitest/Vite module resolution can still break because package paths resolve back through the original checkout. Prefer a real install in the worktree (offline if the store is already populated).

**Skip nothing silently.** Only smells #1, #3, and #6 have legitimate exceptions. Mark skipped hits so future grep passes can tell "triaged, legitimate" from "untriaged":

- **Smells #1 and #3** — ANN401 fires on these. Add `# noqa: ANN401` with a one-line reason.
- **Smell #6** — ANN401 does _not_ fire on `dict[str, Any]` (nested `Any` isn't covered). Add a plain comment explaining the choice; don't add a noqa (RUF100 will flag it as unused).
- **Smell #2** has no legitimate exceptions. Every hit gets fixed.
- **Smells #4 and #5** either get rewritten or the shape is genuinely fine as a plain tuple and the smell doesn't fire for it.

**Promotion threshold for smell #1.** If the raw grep for smell #1 returns >100 hits in the chosen chunk, or you find yourself spending more than an hour deciding whether individual hits are legitimate, stop and build a narrow AST helper that filters the framework-boundary exception shapes and does attribute-profile matching. Below that, don't build the tool.

(The two numeric thresholds in this plan measure different things: the ~60-item size check above triggers a chunk-size drop before you start, combining hits across all smells; the 100-item smell-#1 threshold here triggers tool-building for smell #1 specifically. They're independent.)

### Phase 0: infrastructure setup (one-time)

Before any chunk work, one PR lands two repo-wide changes to `backend/pyproject.toml`:

**1. Turn ANN401 on globally.** The backend's `[tool.ruff.lint]` already has an explicit `select` list (`["E", "W", "F", "I", "N", "UP", "B", "C4", ...]`). Add `"ANN401"` to it — this is a list edit, not a replacement. The broad seed globs like `apps/accounts/**` would pattern-match migrations too, but ruff's top-level `exclude = [..., "*/migrations/*"]` drops those files before rule enforcement runs, so the ratchet swap doesn't need to carve migrations out. Only tests need re-adding at ratchet time.

**2. Seed `per-file-ignores` with every currently-dirty path.** Generate the seed list from the Phase 1 grep for smell #1 (`Any`/`object` params is the widest net). Group by top-level chunk — app or subdir — and emit one glob per chunk:

```toml
[tool.ruff.lint.per-file-ignores]
# Every chunk that currently contains Any — shrinks over time as chunks clean.
"apps/accounts/**" = ["ANN401"]
"apps/catalog/**" = ["ANN401"]
"apps/citation/**" = ["ANN401"]
"apps/core/**" = ["ANN401"]
"apps/media/**" = ["ANN401"]
"apps/provenance/**" = ["ANN401"]
# ...etc, one line per dirty chunk
```

**Glob root.** Ruff globs are relative to the directory containing `pyproject.toml`. The backend's `pyproject.toml` is at `backend/pyproject.toml`, so a glob like `apps/accounts/**` matches `backend/apps/accounts/**` when ruff is invoked against the backend tree. Don't prefix with `backend/`.

**Broad seed globs stay broad.** `apps/accounts/**` is broader than the Phase 1 greps, which exclude tests and migrations. That's intentional — at ratchet time (Phase 2) the chunk's ruff entry is _replaced_ with narrower ignores for the still-excluded subpaths (typically `apps/accounts/tests/**`), so tests stay grandfathered when the source is cleaned. See the ratchet template.

(Alternative absorption path: run `ruff check --add-noqa --select ANN401 backend/` to insert `# noqa: ANN401` at every existing violation site. Higher resolution — you see exactly which lines are grandfathered — but ~100–200 scattered `# noqa` comments clutter the codebase until they're removed. The seeded `per-file-ignores` approach is recommended because it matches the shape of the ratchet: chunks come off the list as they're cleaned, and the list shrinks visibly over time.)

No mypy change in Phase 0 or Phase 2 — see Phase 2 for why the ratchet is ruff-only.

### Phase 1: the smells

Run these from the repo root. Current counts against `main` in parentheses.

**1. `Any` / `object` parameters** (56 hits)

```sh
rg -n --type py ':\s*(Any|object)\b' backend/ \
  -g '!**/tests/**' -g '!**/test_*.py' -g '!**/migrations/**'
```

Regex catches `: Any`, `: Any | None`, and `**kwargs: Any`. It does _not_ catch `: Optional[Any]` (the `Optional[...]` wrapper breaks the `:\s*(Any|object)` anchor), but that form is empirically zero in the backend today and ANN401 catches it if reintroduced. For paranoia, add a second grep:

```sh
rg -n --type py 'Optional\[(Any|object)\]' backend/ \
  -g '!**/tests/**' -g '!**/test_*.py' -g '!**/migrations/**'
```

**Fix:** replace the annotation with the concrete type. Infer it from the body's attribute access against this profile table:

- `.pk`, `._meta`, `.save()`, `.DoesNotExist` → `django.db.models.Model`
- `.pk`, `.is_authenticated`, `.username`, `.is_superuser` → `User` / `AbstractBaseUser`
- `.GET`, `.POST`, `.META`, `.user`, `.session` → `HttpRequest`
- `.name`, `.app_label`, `.model_class()` → `ContentType`

If the body accesses attributes not in the table, infer the type directly — usually a specific model class is obvious from a `.objects.get(...)` call higher in the function, or from the single call site.

**Skip only these legitimate cases** (leave the `Any` annotation, add a `# noqa: ANN401` with a one-line reason):

The principle is "framework-owned callback surface, not application-owned data model." If a third-party framework defines an open-ended callback signature and your code is implementing that protocol rather than narrowing it, preserve the broad annotation instead of inventing a fake concrete type.

- `**kwargs: Any` / `**options: Any` in Django management-command `handle()` methods (argparse-driven)
- `**kwargs: Any` in framework callback hooks where the framework owns the keyword schema (for example Django signal receivers or auth-backend `authenticate(..., **credentials)`)
- Django-Ninja dispatch parameters where a schema validates the real shape at runtime
- pytest fixture parameters typed to accept whatever the test file passes in

**2. `cast(Any, …)`** (2 hits)

```sh
rg -n --type py 'cast\(\s*Any\s*,' backend/
```

**Fix:** replace `cast(Any, x)` with `cast(RealType, x)` or remove the cast entirely if the expression is already typed. No legitimate exceptions.

**3. `-> Any` return annotations** (8 hits)

```sh
rg -n --type py -e '-> Any\b' backend/ \
  -g '!**/tests/**' -g '!**/migrations/**'
```

**Fix:** read the function body and name the real return type. Examples to fix: `claims_prefetch() -> Any`, `_get_location_root(loc: Any) -> Any`, `_iter_concrete_subclasses(root: type[Any]) -> Any`. If the function genuinely returns a union, spell out the union. If it's genuinely dynamic (JSON parse result, eval), that's the rare legitimate case — leave a `# noqa: ANN401` with a reason.

**4. Heterogeneous tuples with ≥3 positional elements** (25 hits)

```sh
rg -n --type py 'tuple\[[^\]]*,[^\]]*,[^\]]*\]' backend/ \
  -g '!**/tests/**' -g '!**/migrations/**'
```

**Fix:** define a NamedTuple in the same module, replace the tuple annotation with it, and update the call sites to use attribute access (`.parent_model` instead of `result[0]`). Find call sites with `rg -n --type py 'FUNC_NAME\(' backend/` — note `\(` is required because `(` is a regex metacharacter. Read the assignment on each match (`a, b, c = FUNC_NAME(...)` or `for a, b, c in FUNC_NAME(...):`) to pick field names that match what callers are already calling the positions. For a known positional arity, grep directly: `rg -n --type py 'a, b, c = FUNC_NAME\('`.

**Cross-chunk callers come along.** If the rewritten function lives in chunk A but has callers in chunk B, the chunk A PR includes the caller-side edits in B. Acceptable because caller changes are mechanical (import + attribute access), not type-tightening that would belong to B's own session. The alternative — land the NamedTuple in A, defer B's caller updates to B's session — leaves the type in a half-adopted state and is worse.

Regex is deliberately flat — it misses nested shapes like `tuple[tuple[type, str], ...]`. Smell #5 catches those.

**5. Repeated tuple shapes across modules** (9 shapes with ≥3 occurrences)

```sh
rg -oN --type py --no-filename 'tuple\[[^\]]+\]' backend/ \
  -g '!**/tests/**' -g '!**/migrations/**' \
  | sort | uniq -c | sort -rn | awk '$1 >= 3'
```

Nine shapes exceed the ≥3 threshold; the top four are: `tuple[int, int]` ×22, `tuple[str, str]` ×17, `tuple[int, str]` ×13, `tuple[int, int, str]` ×6 (the last spanning `provenance/models/claim.py`, `catalog/resolve/_media.py`, `catalog/ingestion/apply.py`).

**Fix:** for each shape with ≥3 occurrences, define one NamedTuple in a shared location (typically `apps/<app>/types.py` if the uses are app-local, or `apps/core/types.py` if cross-app), import it everywhere the shape was used. Find all use sites with `rg -l --type py 'tuple\[int, int, str\]' backend/`. Skip shapes where the occurrences are semantically unrelated (e.g. two unrelated functions both happen to return `tuple[int, int]` for totally different reasons) — those get distinct NamedTuples, not a shared one.

**A type alias is not a fix.** `type EntityKey = tuple[int, int]` reads cleanly in signatures but leaves callers doing `key[0]`/`key[1]` — the label-less positional access is the actual smell, and the alias just renames the container. Only a NamedTuple (or equivalent structure with named fields) clears this smell. If the follow-up grep still shows bare-tuple indexing at call sites, the fix was cosmetic.

**Prefer NamedTuple over a parallel TypedDict ref.** When a TypedDict exists only as an entity reference whose keys exactly match a NamedTuple's fields (e.g. `{"content_type_id": int, "object_id": int}` alongside `EntityKey`), collapse them into the NamedTuple — it's hashable so it can double as a dict key, and eliminating the parallel types removes the "construct-a-dict-here, index-a-tuple-there" asymmetry at call sites.

**Cross-chunk ownership.** Cross-app NamedTuples live in `apps/core/types.py`. The first session to touch a cross-app shape creates the NamedTuple there and migrates its chunk's call sites; later chunks import from `apps/core/types.py` rather than redefining. Before creating a new NamedTuple there, read `apps/core/types.py` end-to-end — the intent is to catch a prior session that introduced the same shape under a different name (`ModelField` vs `FieldSpec` vs `AliasType` could all be `tuple[type, str]`). If you find an existing NamedTuple whose field types match the shape you were about to introduce, import it instead. If `apps/core/types.py` doesn't exist yet, your session is the first to need it — create it with a short module docstring ("cross-app shared types") and add your NamedTuple.

**6. `dict[str, Any|object]` in non-test signatures** (39 hits)

```sh
rg -n --type py 'dict\[str,\s*(Any|object)\]' backend/ \
  -g '!**/tests/**' -g '!**/test_*.py' -g '!**/migrations/**'
```

**Fix:** look at call sites passing dict literals. If the keys are consistent across callers, define a TypedDict and use it. If the dict is genuinely free-form (JSON request bodies accepted verbatim, `extra_data` payloads with no fixed schema), leave the annotation and add a plain comment explaining why. Don't use `# noqa: ANN401` — ANN401 doesn't fire on nested `Any` inside `dict[str, Any]`, so a noqa here would be unused and RUF100 would flag it.

### Phase 2: per-chunk ratchet

A one-shot audit converges on "this chunk is done" only until the next PR re-introduces an `Any`. The durable fix is to remove the chunk from ruff's ANN401 grandfathering so new violations in that chunk fail CI.

**Ruff-only ratchet.** The ratchet mechanism is a single edit: replace the chunk's broad `per-file-ignores` glob with a narrower test-only glob (or remove it entirely if tests are also clean). ANN401 is already globally on from Phase 0; the per-file ignore is the only thing suppressing it in the chunk.

**No mypy ratchet.** The six smells produce valid-but-weak annotations, not mypy errors. `dict[str, Any]` is fine mypy, `cast(Any, ...)` is fine mypy, `tuple[int, int, int]` is fine mypy. Mypy has its own separate backlog (captured in [`backend/mypy-baseline.txt`](../../backend/mypy-baseline.txt): `attr-defined`, `union-attr`, `no-any-return`, etc.) — those are real type errors, not smells. Conflating the two would balloon chunk scope onto every mypy error in the directory, not just the six smells this plan targets. Mypy-baseline cleanup is orthogonal adjacent work a session can opt into but is not part of this plan's required scope.

**If you do opt into mypy cleanup, sanity-check the baseline sync output.** After running the sync command, open [`backend/mypy-baseline.txt`](../../backend/mypy-baseline.txt) and confirm it is still one mypy error per line, with no summary/footer text like `Found 738 errors...` and no truncated lines. The sync tool only sees stdout; if mypy's output format changes or summary text leaks into the stream, you can end up with a malformed baseline file that fails the next lint run.

**Sync via `mypy`, not `dmypy`, and match the wrapper's `--ignore` set.** CI runs [`scripts/mypy`](../../scripts/mypy) (plain mypy), while the pre-commit hook runs [`scripts/dmypy`](../../scripts/dmypy) (the daemon). The two tools emit subtly different output — notably, `mypy` emits `See https://.../missing-imports` notes for every `import-untyped` error, while `dmypy` sometimes omits them (e.g. for function-scoped imports). The three install-hint notes that float around (`(or run "mypy --install-types" ...)`, `Hint: "python3 -m pip install types-*"`, `See https://.../missing-imports`) also flip on/off per-environment depending on which stub packages are already installed. `scripts/mypy` and `scripts/dmypy` filter all three via `--ignore`, so if you sync the baseline without the same ignores, dead install-hint entries will sit in `mypy-baseline.txt` and CI's filter will report them as `fixed` (non-zero exit). Always sync with:

```sh
uv run --directory backend mypy --config-file pyproject.toml . \
  | uv run --directory backend mypy-baseline sync \
      --ignore '.*--install-types.*' '.*pip install types-.*' '.*missing-imports.*'
```

Note: `mypy-baseline` accepts multiple patterns after a single `--ignore` flag, but silently keeps only the last when you repeat the flag. Pass all three patterns to one flag.

**What the ratchet actually locks in.** Honest accounting:

| Smell                             | Covered by ratchet? | Mechanism                                              |
| --------------------------------- | ------------------- | ------------------------------------------------------ |
| #1 `Any`/`object` params          | yes                 | ANN401 (also catches `Optional[Any]`)                  |
| #2 `cast(Any, ...)`               | **no**              | no ruff or mypy-strict rule flags this; PR review only |
| #3 `-> Any` returns               | yes                 | ANN401                                                 |
| #4 heterogeneous tuples           | **no**              | no rule flags tuple shape; PR review only              |
| #5 repeated tuple shapes          | **no**              | no rule flags shape repetition; PR review only         |
| #6 `dict[str, Any]` in signatures | **no**              | ANN401 doesn't fire on nested `Any`; PR review only    |

The ratchet strongly prevents reintroduction of smells #1 and #3 (the highest-volume categories). For smells #2, #4, #5, and #6 regressions, the line of defense remains human/AI review — which is fine because those categories are bounded and grow slowly.

**Legitimate `Any` uses in cleaned chunks** get a targeted `# noqa: ANN401` (on lines where ANN401 actually fires — i.e. top-level `Any` in a parameter or return annotation). Don't use `# noqa: ANN401` on `cast(Any, ...)` or `dict[str, Any]` — ANN401 doesn't fire there, and ruff's RUF100 (unused-noqa) will flag the dead suppression and fail CI. For those cases, use a plain comment explaining the decision.

### Ratchet PR template

The chunk's PR includes this diff to `backend/pyproject.toml` as its closing commit:

One edit in the closing commit: shrink the ruff ignore list in `backend/pyproject.toml`:

```diff
 [tool.ruff.lint.per-file-ignores]
-"apps/accounts/**" = ["ANN401"]
+"apps/accounts/tests/**" = ["ANN401"]  # tests stay grandfathered; source is clean
 "apps/catalog/ingestion/**" = ["ANN401"]
 "apps/provenance/**" = ["ANN401"]
 # ...other dirty chunks remain
```

Drop the replacement ignore entirely if the chunk's test files are also clean. The PR's CI run is the proof the chunk is clean — if `ruff check` fails after this change, the chunk isn't actually done and the PR can't merge.

**On test files.** Phase 1's greps exclude `**/tests/**` and `**/test_*.py` because most test-file `Any` usage is low-signal noise (fixture parameters, argparse kwargs). This is deliberate-for-triage, not a claim that tests can't benefit from tighter types. If a test helper has a clean structural win — a TypedDict for a shared fixture, a NamedTuple for a repeated tuple shape in conftest — include it in the chunk's structural-rewrite PR. It's additive work, just not driven by the grep.
