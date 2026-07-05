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

`video` stays the wire value and the label. It passes the plain-language dropdown test — a contributor citing _Tommy_ choosing "Video" is not confused, because a movie **is** video — and renaming it to something more taxonomically precise (`audiovisual`) buys precision no reader consumes while churning the enum, the CHECK constraints, and every stored row. Movie-vs-video is a _medium_ distinction one level below the behavioral axis, and the behavioral axis is what the type is for.

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
- **The type keeps the wire value and label `video`.** Passes the dropdown test; a rename buys unconsumed precision.
- **Prior art agrees.** Wikipedia folded `{{cite film}}` into `{{cite AV media}}` (film is `medium=` data); Wikidata types the work (P31), not the citation, and records the copy consulted as P854.
- **A movie enters as a parentless-citable video work** — the missing third video shape beside platform-root and child. One model change: relax `video`'s `parentless_abstract` to key on `identifier_key` (blank = movie, citable; set = platform, abstract), mirroring the book rule ([F3](CitationSourceMisclassification.md)).
- **Streaming platforms are not schemes.** A streaming URL is access, not identity; a scheme would fragment one film into per-platform children. The link is a future access URL on the instance, not the movie's identity.
- **Audio is different** — it earns its own behaviorally-distinct type (`podcast`) when demand appears; a movie does not, precisely because a movie is behaviorally a video.

## Not in this document

- **Seeding the popular pinball movies.** The proof-of-concept seed (a data patch declaring parentless `video` works with years) is specced and delivered separately; this document only justifies the type decision it rests on.
- **Access URLs / deliverer-host recognition.** Additive and sequenced after ([CitationInstanceUrls.md](CitationInstanceUrls.md), F1/F7). A movie is usable before they land — its timestamp locator stands alone.
- **Movie-specific metadata beyond what `CitationSource` already carries.** Year/author/publisher/description exist today; a director role or runtime, if wanted, is a later source-schema question, not a citation-type one.
