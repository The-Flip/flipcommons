# editors

This folder contains the section editors that make up a record's edit page —
each edits one section of one entity's claims. Shared editors (name, description,
aliases, media) sit at the root; everything specific to a single entity type
lives under `entity/`.

A section editor is more than a `.svelte` form: each entity bucket pairs its
editors with a `*-edit-sections.ts` spec (the section registry the edit routes
read) and, where it writes, a `save-*-claims.ts` (the claim-submit contract).
That spec / save-claims pairing — not the filename — is what makes a file part
of this subsystem.
