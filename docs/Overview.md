# Overview

## What

This project is an interactive, collaborative database of pinball knowledge. It aims to be an authoritative, easy-to-use repository of all the machines, manufacturers and people involved in pinball.

## Why

[The Flip](https://www.theflip.museum/), Chicago's playable pinball museum, wants a database of pinball machines.

Creating exhibits, both physcial and digital, relies on having a complete and accurate corpus of pinball knowledge.

As a nonprofit and a dedicated proponent of open source, The Flip wants to establish a corpus of pinball information that is:

- **Easy to use**
  - easy to explore
  - easy to edit and contribute to
  - easy to extract information out of
- **Accurate**
  - structured in a way that helps enforce data accuracy and effective dispute resolution.
- **Open**
  - As much as possible, have permissive licensing, ideally public domain. We're still working through exactly what's possible here.

## Who It Serves

- Museum staff and curators
- Pinball players and collectors
- Researchers and historians
- Contributors and editors
- Downstream users of open data

## What Makes This Project Different

- a domain model that matches how people actually think about pinball
- provenance and dispute resolution
- openness and extractability
- support for both casual exploration and serious research
- editorial curation without losing source history

## Why Provenance Is A Differentiator

Most databases collapse every question down to a single stored answer. That makes the data easy to display, but it hides where the answer came from, makes disagreements hard to inspect, and makes later correction or comparison much harder.

This project treats [provenance](Provenance.md) as part of the product, not just as backend bookkeeping.

- every important fact can carry attribution: who said it, where it came from, and when it entered the system
- conflicting claims from different sources can coexist instead of forcing the system to pretend there was never a dispute
- the product can resolve those conflicts deterministically while still preserving the underlying evidence
- editors and researchers can inspect the history of a fact instead of trusting an opaque final value
- adding a new source does not require rethinking the whole data model for every field

This matters for pinball because the subject is full of messy history, conflicting sources, changing corporate identities, incomplete credits, regional variations, and editorial judgment calls. A provenance-aware system is better suited to that reality than a database that only stores one decontextualized answer per field.

## Why Openness Is A Differentiator

This project is being built as an open system, not a walled garden.

- the codebase is open source
- the project is intended to make pinball knowledge easier to inspect, reuse, and build on
- structured data is easier to extract and analyze than information trapped in ad hoc pages or opaque software
- APIs and exports make the data more useful to museums, researchers, hobbyists, and downstream tools
- provenance and licensing make it easier to understand what can be reused, under what terms, and where it came from

This does not mean every piece of information in the project is automatically public domain or free of constraints. Some data originates from outside sources with their own licensing limits, and the project is still working through what the most permissive responsible approach can be in each area.

But openness is still a core differentiator. The goal is to make pinball knowledge more available, more legible, and more reusable than systems where the data is difficult to access, difficult to verify, or effectively locked away.

## Why The Domain Model Is A Differentiator

This project treats the structure of pinball knowledge as the most critical part of the product, via a rich [domain model](DomainModel.md),

- games are modeled at multiple levels, including Titles, Models, variants, remakes, and conversions
- who built a machine is not treated as one flat name field; manufacturers, corporate entities, and hardware systems can each be represented precisely
- people, credits, taxonomy, and other descriptive dimensions are treated as first-class parts of the domain rather than loose free-form notes
- the same underlying structure supports both a more approachable Title-based user experience and deeper exploration across many dimensions

Most pinball sites are built by and for collectors and are oriented around the concept of a model. That works for learning all about that model, but it tends to flatten the domain and leave important distinctions implicit, inconsistent, or missing entirely.

This is important because the public usually thinks in terms of titles, not specific moels within a title, while researchers and serious enthusiasts often need much more precision than a simple model lists can provide. By modeling the pinball world with more care, the site can be easier to browse, more flexible to explore, and more accurate than systems that rely more heavily on free-form or flattened data.

## Read Next

[DomainModel.md](DomainModel.md)
[Provenance.md](Provenance.md)
