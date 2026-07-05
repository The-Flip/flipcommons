# Citations Design

This document describes the high-level design for this project citations. It is intentionally about product shape and system boundaries, not implementation detail.

## Goals

The citation system should do three things at once:

- make evidence visible to readers
- keep citation authoring cheap for contributors
- accumulate reusable source infrastructure over time

The design therefore aims for Wikipedia's verification loop without Wikipedia's citation bureaucracy.

## Basic Authoring Model

Long-form markdown content uses inline citation markers:

```markdown
The production run was 4,000 units.[[cite]]
```

`12345` is a `Citation Instance`. The marker means "this source supports the nearby claim," usually the preceding sentence or clause. This project uses point citations rather than text ranges.

The existing `[[` autocomplete is the front door for citation authoring. Contributors do not choose a separate citation mode first.

## Contributor Flow

The intended flow is:

1. Start from one input that accepts either search text or pasted evidence.
2. Search for an existing citation source first.
3. If no strong match exists and the input looks like evidence, try to build a draft source automatically.
4. Let the user confirm or edit the draft, or quick-create manually.
5. Add an optional locator when the source type benefits from one.
6. Insert the citation marker.

Examples of evidence-like input:

- book title or author search
- ISBN
- DOI
- known-site URL such as an IPDB page

The system should optimize for reuse, but quick creation must stay close at hand. Citation authoring should never turn into a mandatory library-catalog workflow.

## Data Model

The model has three core entities:

- `Citation Source`: the work or evidence object being cited
- `Citation Instance`: one use of that source, usually with a locator
- `Citation Source Link`: one way to inspect that source

```text
Markdown or scalar claim
  └── Citation Instance
        ├── locator
        └── Citation Source
              └── Citation Source Link(s)
```

### Citation Source

A citation source is a shared record. If multiple pages cite the same book or article, they should normally point at the same source.

Sources may be hierarchical when the domain needs it:

- work -> edition
- publication -> issue -> article
- documentation set -> specific manual

The hierarchy represents source identity. Locators such as page numbers, timestamps, sections, and URL fragments stay on the citation instance.

Children do not inherit fields from parents. Prefill is fine in the UI; inheritance in the data model is not.

### Citation Instance

A citation instance is a single use of a source in a specific place.

- Markdown citations point to a citation instance inline.
- Scalar claims can attach citation instances through the edit form.

Instances are **immutable**: changing a locator produces a new citation instance plus an ordinary edit, not mutate history in place.

### Citation Source Link

Source links are reader-facing access points:

- canonical URLs
- archive URLs
- uploaded scans
- museum-hosted copies

They are links to inspect a source, not separate sources themselves.

## Source Typing

Citation source types are pragmatic product categories, not a grand bibliography ontology. Their job is to drive:

- search behavior
- edit fields
- locator prompts and validation
- reader rendering

The taxonomy should stay small and expand only when a new type clearly needs distinct behavior. A broad fallback type remains important.

Source types — and the per-platform identifier schemes under them (IPDB, YouTube, …) — are implemented as two plugin frameworks; their contracts, module walls and testing story are specified in [CitationPluginSystem.md](CitationPluginSystem.md).

## Search, Creation, and Extraction

The system should always try to reuse an existing source first. When that fails and the input looks like evidence rather than ordinary text, this project can help create a new source draft automatically.

That extraction layer should follow a simple principle:

- use known-source and known-site extractors where possible
- keep a generic fallback for weaker cases
- produce a draft for confirmation, not a silent auto-create

This keeps extraction useful without making contributors trust opaque automation.

## Pre-population and Reuse

For heavily reused source families, this project should pre-populate citation sources where practical. Pre-population improves autocomplete quality, reduces duplicate creation, and makes shared-source reuse feel natural from the start.

Shared sources still need pragmatic governance:

- reuse should be encouraged, not forced
- duplicate cleanup can be editorial work after the fact
- improving a shared source should benefit every citation that points at it

## Reader Experience

On read:

- inline citations render as superscript references
- the page shows a references section when citations exist
- each entry shows the source, locator, and any useful access links
- scalar and inline citations should appear as one coherent evidence surface

Pages with no citations are allowed. Citations improve trust and maintenance, but they are not a hard prerequisite for contribution.

## Architecture Notes

At the system level:

- citations live in their own Django app
- citation authoring integrates with the existing `[[` autocomplete workflow
- extraction belongs on the backend, where server-side HTTP, rate limiting, and external integrations live
- the citation model is shared across markdown content and scalar claims
- per-type and per-platform knowledge lives behind two plugin frameworks — see [CitationPluginSystem.md](CitationPluginSystem.md)

Implementation details such as reducer structure, refactor steps, or extractor module layout are intentionally out of scope for this document.
