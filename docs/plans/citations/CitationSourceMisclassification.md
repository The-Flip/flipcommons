# Citation Source Misclassification and Deliverer Hosts

Future product plan for keeping citation-source classification clean — the Amazon book/movie mis-filed-as-web problem. Nothing here is built. The full version depends on instance access URLs ([CitationInstanceUrls.md](CitationInstanceUrls.md)) landing, but two guardrails are doable earlier. The plugin architecture this builds on is in [CitationPluginSystem.md](CitationPluginSystem.md).

## Core insight

Amazon is a **deliverer**, not a scheme and not a web root — an Amazon URL is the copy consulted (access), not the identity of the work. Minting a web child for it _fabricates identity_ and fragments one work into per-platform children. The rejected-platform reasoning is recorded in [VideoCitations.md](VideoCitations.md)'s rejected-platforms section.

## Work items

- **F1. Access-only / deliverer host recognizer** — the "fourth recognizer verb": declared hosts whose recognition outcome is "record this URL as access; identify the work separately." (post-access-URLs)
- **F2. Interactive-path guardrail (near-term, cheap).** A deliverer-host denylist in the web-create stage that replaces "Create site" with "cite the book/video itself" and hands off to the authored-work form. Converts the highest-volume misclassification into a teaching moment. The patch path is already protected (won't mint parentless web roots); the interactive path is the hole.
- **F3. Relax video `parentless_abstract` keyed on `identifier_key`** (set = platform root, abstract; blank = citable work) — the parentless-citable video work = movie shape, mirroring the book rule.
- **F4. Amazon book auto-classify (near-term).** `/dp/` ASIN is the ISBN-10 for books → route through the existing Open Library extraction to prefill a book draft — a fully automatic correct outcome for the single most likely paste.
- **F5. Provisional interactively-minted roots.** A gardening/review view ("roots created interactively, newest first"); attribution (`created_by`) already exists. Reframes the goal from prevent-all (impossible) to make-visible-and-cheap-to-repair.
- **F6. Source merge tool.** Repoint `CitationInstance` rows (PROTECT blocks deletion while cited), move links/domains, absorb the duplicate — the "citation gardening" the upsert warnings already reference as the merge backlog.
- **F7. Thread the pasted URL through as future `access_url`.** The paste flow already holds the exact string (`?t=` and all) and currently discards it after extracting identifier + hint; thread it when instance URLs land.

## Sequencing

**F2/F4** can ship as near-term guardrails independent of the rest; the structural pieces (F1/F3/F5/F6/F7) sequence after instance access URLs.
