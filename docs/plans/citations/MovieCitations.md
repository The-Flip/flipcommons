# Movie Citations

Product spec and design justification for citing **movies** — feature films, documentaries, and other released audiovisual works — as evidence. The one question this document answers: **is a movie a new citation type, or is it a `video`?** The conclusion is that a movie is a `video`, and the rest of this document is the argument for why, the one small model change it forces, and what a movie adds that a born-digital video doesn't.

## Status: 📝 PROPOSED

The decision (movie = `video`) was settled while working the movie case through in [VideoCitations.md](VideoCitations.md#movies-audio-and-what-sequences-after); this document promotes that paragraph to a full justification and specs the change. The enabling model change is **F3** in [CitationSourceMisclassification.md](CitationSourceMisclassification.md). Not built yet.

## The question

A movie feels like it wants its own citation type. It has a year, a director, a runtime; it is a "film", not a "video"; the dropdown a contributor picks from would read more honestly with a `Movie` row than by asking them to file _Tommy_ under `Video`. So the instinct is: add `SourceType.MOVIE` beside book, magazine, web, video.

That instinct is wrong, and it is worth being precise about why, because the citation-type axis is the expensive one — a new type is a first-party product decision that ripples into the frontend, the codegen channel, the reader components, and the CHECK constraints ([CitationPluginSystem.md](CitationPluginSystem.md)). We should pay that cost only when a candidate **behaves** differently, not when it merely **reads** differently.

## The answer: a movie is a `video`

Our type axis encodes **behavior**, not **medium**. A `CitationTypeSpec` declares exactly four behavioral facts (`apps/citation/citation_types/citation_type_specs.py`):

- `flat_hierarchy` — how deep the source nests
- `parentless_abstract` — whether a parentless source is a container or citable evidence
- `child_skips_locator` — whether the cite picker prompts for a locator
- `locator` — the locator grammar (validate, normalize, deep-link)

Run a movie down that list and it is a video in every position:

| Behavioral fact                  | Video (born-digital)                          | Movie                                     | Same? |
| -------------------------------- | --------------------------------------------- | ----------------------------------------- | ----- |
| Locator semantics                | a **timestamp** — "start watching at 1:02:03" | a **timestamp** — the scene is at 1:02:03 | ✅    |
| Locator is the point of the cite | yes — evidence lives at a moment              | yes — evidence lives at a moment          | ✅    |
| Identity                         | **work-level** — the URL identifies the work  | **work-level** — the film is the work     | ✅    |
| Hierarchy                        | flat (platform → video) / work-level          | work-level                                | ✅    |
| Reader affordance                | jump-to-timestamp where the copy supports it  | same                                      | ✅    |

Everything that distinguishes a movie from a YouTube clip — a release year, a director, a distributor — is **metadata on the source row**, not behavior the citation system branches on. `CitationSource` already carries `year`/`month`/`day`, `author`, `publisher`, `description` for exactly this. A movie is a video with its year filled in.

Writing `movie.py` would produce a `CitationTypeSpec` **field-for-field identical** to `video.py`'s — same timestamp grammar, same work-level identity, same locator contract. A type whose only differentiator is the label it shows in a dropdown is not a behavioral type; it is a medium tag, and a medium tag belongs in **data**, not in the type axis. Compare: we don't have separate `hardcover` and `paperback` citation types — edition is data on a book.

### The type keeps the name `video`

`video` stays the wire value and the label. A contributor citing _Tommy_ and choosing "Video" is not confused, because a movie **is** video; movie-vs-video is a _medium_ distinction one level below the behavioral axis, and the behavioral axis is what the type is for.

## Prior art: nobody else types film separately either

Two reference systems that have lived with this question far longer both collapsed it:

- **Wikipedia** folded `{{cite film}}` into the general `{{cite AV media}}` template. Film is expressed as a `medium=` parameter — i.e. **data** — not as a distinct citation template. And its `time=` parameter is exactly our locator: "the time the event occurs in the source".
- **Wikidata** has **no citation types at all**. Typing lives on the _source item_ via P31 (`film` ⊂ `audiovisual work` ⊂ `work`); platform addresses are external-identifier properties (P1651 YouTube video ID and siblings); and each reference records the specific copy consulted as P854 (reference URL). The medium is a property of the work; the citation is type-agnostic.

Both put the film-ness on the **work** and keep the **citation** generic. That is the shape we already have: `source_type = video` is the generic citation behavior; the year/director/etc. on the `CitationSource` row are the work's film-ness.

## What a movie _is_, structurally: a parentless-citable video work

Here is the one place a movie genuinely differs from today's videos — and it is a difference in **abstractness**, which is already a behavioral fact we model, not a new axis.

Today every video source is either a **platform root** (YouTube — abstract, a container you never cite directly; recognition resolves a video URL to a child under it) or a **child** under such a root. `video`'s spec says `parentless_abstract=True`: a parentless video is assumed to be a platform.

A movie is the missing third shape: a **parentless video that is itself the evidence**. _Tommy_ is not a platform and not a child of one — it is a work, cited directly, the way a parentless **book** is the book itself. It has:

- **No canonical URL.** A film is available through many channels — Prime, Apple TV, physical media, a YouTube upload — so no single URL _is_ the work. This is the defining property. (Contrast a YouTube video, whose canonical URL identifies the upload.)
- **No recognition host, no identifier scheme.** Nothing to paste; you reach a movie by **searching** the source list, not by recognizing a URL. Its `identifier_key` is blank.
- **Only an access URL** — the specific copy consulted (an `amazon.com/gp/video/detail/…` link) — which is P854 "reference URL", **access, not identity**. We don't model access URLs yet ([CitationInstanceUrls.md](CitationInstanceUrls.md)); until we do, a seeded movie carries its metadata and no URL, and the timestamp locator alone tells the reader where to look.

The model change this forces is small and mirrors the book rule exactly: **relax `video`'s `parentless_abstract` so it is keyed on `identifier_key`** — set = platform root (abstract, as today); blank = a citable work (a movie). This is [F3 in CitationSourceMisclassification.md](CitationSourceMisclassification.md). A scheme-holding root stays abstract (a platform is always a container); a schemeless parentless video becomes citable evidence (a movie). No new type, no new locator grammar, no frontend module — one behavioral relaxation on the existing type.

## Why the streaming platforms are not schemes (and why that matters here)

The tempting alternative is a Prime Video or Apple TV **scheme** — recognize `amazon.com/gp/video/detail/<id>`, mint a video child, done. This is rejected, and the reason is the same reason a movie is a work and not a URL. The full argument is in [VideoCitations.md](VideoCitations.md)'s rejected-platforms section; the summary:

- A streaming URL is a **deliverer** address — the copy consulted — **not the identity** of the work. A Prime scheme would enshrine access as identity and **fragment one film into per-platform children** (a Prime _Tommy_, an Apple _Tommy_, a YouTube _Tommy_), when they are one work.
- The region-scoped paths (`tv.apple.com/us/…`) and the `amazon.com` retail collision are **symptoms** of that identity/access confusion, not the root cause.
- The shape that fits instead is the one above: the movie is a parentless-citable video work, the timestamp is the **work-level** locator (the lowest common denominator across every channel — exactly what "the type owns locator semantics" already encodes), and the streaming URL is a **declared access URL** — the "opaque deliverer" case the URL plan already names, recorded later as F1/F7 in [CitationSourceMisclassification.md](CitationSourceMisclassification.md).

So the movie decision and the "Amazon is not a video source" decision are the same decision viewed from two sides: **identity lives on the work, access lives on the instance.** A movie is the work; a streaming link is access to it.

## What about audio?

Recorded audio (a podcast, a commentary track) shares the timestamp locator, so the instinct to reuse `video` recurs. The call there is the opposite, and it is instructive for why: audio, when it earns a slot, gets **its own product-named type** — likely `podcast` — because podcasts _do_ diverge behaviorally (episodic show → episode nesting, the magazine shape, with an RSS/Apple/Spotify identifier story of their own). Audio would be a new type not for its medium but for its **behavior**. A movie would be a new type _only_ for its medium — which is the distinction this whole document rests on. (The one refactor audio triggers: lift the timestamp grammar out of `video.py` into a shared `citation_types/timestamps.py` so both types share one `LocatorContract`.)

## Decision summary

- **A movie is a `video`, not a new citation type.** The type axis encodes behavior; a movie behaves exactly like a video (timestamp locator, work-level identity). Its film-ness (year, director, distributor) is source-row metadata, not citation behavior.
- **The type keeps the wire value and label `video`.** A movie is video; the medium distinction lives in data, not the type name.
- **Prior art agrees.** Wikipedia folded `{{cite film}}` into `{{cite AV media}}` (film is `medium=` data); Wikidata types the work (P31), not the citation, and records the copy consulted as P854.
- **A movie enters as a parentless-citable video work** — the missing third video shape beside platform-root and child. One model change: relax `video`'s `parentless_abstract` to key on `identifier_key` (blank = movie, citable; set = platform, abstract), mirroring the book rule ([F3](CitationSourceMisclassification.md)).
- **Streaming platforms are not schemes.** A streaming URL is access, not identity; a scheme would fragment one film into per-platform children. The link is a future access URL on the instance, not the movie's identity.
- **Audio is different** — it earns its own behaviorally-distinct type (`podcast`) when demand appears; a movie does not, precisely because a movie is behaviorally a video.

## Implementation plan

The whole feature is one behavioral relaxation plus a seed. There is **no new type, no new locator grammar, no new column, no migration, no codegen run, and no frontend change** — the sections below say why for each. What changes is a single method's logic, one spec field, and a data patch.

### 1. The abstractness relaxation (backend, the whole code change)

Today abstractness is computed in `CitationSource.is_abstract` (`apps/citation/models.py:310-329`):

```python
return has_children or (self.is_root and citation_type_spec(self.source_type).parentless_abstract)
```

`parentless_abstract` is a plain per-type bool (`book=False`, `magazine=True`, `web=True`, `video=True`). The relaxation reinterprets that field and adds one universal rule, so nothing branches on `"video"` — it stays model-driven:

- **`parentless_abstract` now means "is a _schemeless_ parentless root of this type abstract?"** — i.e. when the parentless form is _not_ a platform root, is it still a container? Book `False` (the book is the work), magazine `True` (a publication), web `True` (a site), and **video flips `True → False`** (the schemeless parentless video is a **movie** — the work itself). This is the only edit to `video.py`.
- **A scheme-holding root (`identifier_key` set) is abstract universally**, added to `is_abstract`. A scheme root _is_ a platform/site container by definition — recognition resolves to its children, never the root — so this holds for every type and needs no per-type flag. It is what keeps the YouTube (and X) root abstract after video's field flips.

New body:

```python
def is_abstract(self, *, has_children: bool) -> bool:
    if has_children:
        return True
    if not self.is_root:
        return False
    # A scheme-holding root is a platform/site container — recognition
    # resolves to its children, never the root. Abstract regardless of type.
    if self.identifier_key:
        return True
    # A schemeless parentless root: abstract only when the type's schemeless
    # parentless form is a container (a magazine, a site) and not the work
    # itself (a book, a movie).
    return citation_type_spec(self.source_type).parentless_abstract
```

The behavior delta is **exactly one case**: a parentless `video` with a blank `identifier_key` (a movie) goes from abstract → citable. Every other row is unchanged — the YouTube root stays abstract via the `identifier_key` branch, schemeless web/magazine roots stay abstract via their unchanged field, book is untouched. Because `is_abstract` is a **display hint, not a write invariant** (its docstring), no constraint or write path needs touching; the flip simply routes the cite picker differently (§3).

### 2. Tests (TDD — failing test first, per CLAUDE.md)

- **Close the pre-existing gap**: `test_citation_type_registry.py::test_traits_per_type` parametrizes only book/magazine/web — add the `VIDEO` row (`flat=True, abstract=False, skips_locator=False` after the flip). It fails before the change, passes after.
- **`is_abstract` unit cases** (no DB — the method reads only `self` fields and takes `has_children`): a parentless video with `identifier_key="youtube"` is abstract; a parentless video with blank `identifier_key` (a movie) is **not** abstract; a movie _with_ children is abstract (the `has_children` short-circuit); a schemeless parentless web/magazine root stays abstract (no regression).
- **End-to-end cite-target** (extends `test_api.py::TestSearchComputedFields`, which already covers a web root): a seeded movie surfaces in `search_citation_sources` with `is_abstract=false`, and the frontend reducer's existing "not abstract → locator stage" path (`citation-types.test.ts`) already covers the routing, so a movie is directly citable with a timestamp locator.

### 3. Frontend: no change required

The cite picker already does the right thing once the flag flips. The reducer (`frontend/src/lib/components/input/citation/citation-types.ts:254`) routes an **abstract** source to the _identify_ stage (hunt for a child) and a **non-abstract** source straight to the _locator_ stage. A movie, now non-abstract, lands on the locator stage — which for a `video` source renders the timestamp prompt from the generated citation-type meta. No component, reducer, or codegen change; the abstractness that drives the routing is served per-row on `CitationSourceSearchSchema.is_abstract` (`apps/citation/schemas.py`), computed by the method we changed.

### 4. No migration, no codegen

`parentless_abstract` is read only by `is_abstract` — it is **not** a DB column, **not** in any CHECK constraint (those derive from `SourceType.values` and the scheme registry, not this field), and **not** exported by `export_citation_type_meta`. Flipping it and editing a pure Python method touches no schema and no generated file. The `year` a movie needs already exists on `CitationSource` (`models.py:128`).

### 5. Seed the popular pinball movies

The seed is the proof: a handful of real pinball films declared as parentless `video` works with a year and no `identifier_key`/`domains`/`links` (no access URL yet). My exploration confirmed such a row passes every gate — `validate_root_source` → `ensure_root_source` (`apps/citation/source_upsert.py`) and the model CHECKs — today; the relaxation is only what makes it _citable_ once stored.

A `sources:` patch entry (grammar in [DataPatches.md](../../DataPatches.md), parsed by `SourceNode` in `apps/citation/source_node.py`) for a movie — the shape is `name` + `source_type: video` + `year` + `description`, no `identifier_key`/`domains`/`links`:

```yaml
sources:
  - name: Tommy
    source_type: video
    year: 1975
    description: The Who's rock opera; its "Pinball Wizard" is the sport's signature anthem.
  - name: "Pinball: The Man Who Saved the Game"
    source_type: video
    year: 2022
    description: Dramatization of Roger Sharpe's 1976 demonstration that overturned New York's pinball ban.
```

(A director, if wanted, rides the existing `author` field — but see "Not in this document".)

#### Proposed seed list (expansive)

Deliberately broad — everything where pinball is the subject or a load-bearing element, to give the type a real workout. Grouped only for readability; all seed as `source_type: video`. Years marked _(verify)_ are ones I couldn't confirm to a release date and must be checked before ingest; the whole list is finalized with you before it ships.

**Documentaries — pinball as the subject**

| Title                                                      | Year            | What it is                                                   |
| ---------------------------------------------------------- | --------------- | ------------------------------------------------------------ |
| Pleasure Machines: The History of Pinball                  | 1998 _(verify)_ | Early broadcast history-of-pinball documentary.              |
| Tilt: The Battle to Save Pinball                           | 2006            | Williams' Pinball 2000 gambit and the industry's near-death. |
| Pinball Passion                                            | 2008            | Collector/culture portrait.                                  |
| Special When Lit                                           | 2009            | Pinball's rise, fall and revival, ending at PAPA 8.          |
| Wizard Mode                                                | 2016            | Autistic champion Robert Gagno's competitive run.            |
| Shoot Again: The Resurgence of Pinball                     | 2017 _(verify)_ | The modern comeback wave.                                    |
| The History of Pinball                                     | 2018 _(verify)_ | Survey documentary.                                          |
| Things That Go Bump in the Night: The Spooky Pinball Story | _(verify)_      | Portrait of boutique maker Spooky Pinball.                   |
| A World Under Glass                                        | _(verify)_      | Design/artistry-focused documentary.                         |
| Ball Runnings: A Pinball Story                             | _(verify)_      | Competitive-scene documentary.                               |
| Road to Pinball (a.k.a. Gladbeck Freaks Out)               | _(verify)_      | European scene documentary.                                  |
| Token Taverns                                              | _(verify)_      | Barcade/arcade-culture documentary touching pinball.         |
| Pinball: The Man Who Saved the Game                        | 2022            | Dramatized Roger Sharpe / 1976 NYC ban story.                |

**Narrative films — pinball central or iconic**

| Title                                  | Year | What it is                                                  |
| -------------------------------------- | ---- | ----------------------------------------------------------- |
| Tommy                                  | 1975 | Ken Russell's Who rock opera; the "Pinball Wizard" ur-text. |
| Tilt                                   | 1979 | Brooke Shields as a teen pinball hustler.                   |
| Pinball Summer (a.k.a. Pick-Up Summer) | 1980 | Canadian teen film climaxing in a pinball tournament.       |

Sources for the list: [Pinball Passion documentaries list (Letterboxd)](https://letterboxd.com/lroy/list/pinball-passion-documentaries-about-the-wonderful/), [Tilt (1979) — Wikipedia](<https://en.wikipedia.org/wiki/Tilt_(1979_film)>), [Pinball Summer — Canuxploitation](https://www.canuxploitation.com/review/pinballsummer.htm), [TILT: The Battle to Save Pinball — Netflix](https://www.netflix.com/title/70103653).

**Where it lands.** The real `NNNN-slug.yaml` patches live in the sister **flippatch** repo and are pulled from R2 (`make pull-patches`); they are not committed here. So the seed is delivered two ways: (a) the drafted patch YAML above, ready to drop into flippatch as the next-numbered patch, and (b) a backend test in this repo that declares the same movies through the upsert path and asserts each is stored, surfaces in cite-target search as non-abstract, and accepts a timestamp-locator citation — the in-repo proof that "prove or disprove the video citation type" asks for.

### 6. Ordering

The relaxation (§1) is self-contained and ships first; it is inert until a movie exists, so it is safe to deploy ahead of any data. The flippatch seed (§5) is authored against the deployed relaxation, mirroring the deploy-before-publish rule the video work already followed. No access-URL dependency: a movie is fully usable with its timestamp locator alone (§below).

## Not in this document

- **Access URLs / deliverer-host recognition.** Additive and sequenced after ([CitationInstanceUrls.md](CitationInstanceUrls.md), F1/F7). A movie is usable before they land — its timestamp locator stands alone, and the eventual access URL attaches to the citing _instance_, not the movie.
- **Movie-specific metadata beyond what `CitationSource` already carries.** Year/author/publisher/description exist today; a dedicated director role or runtime, if wanted, is a later source-schema question, not a citation-type one.
- **A non-URL path to mint video _children_.** Movies are cited as parentless works, so they need none; this is orthogonal and unbuilt.
