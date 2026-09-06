# Personas

This doc names the kinds of people who use the system.

These are not roles in the authorizations; instead, auth uses [Activities](Authz.md).

The core user is someone driven by curiosity and love of the subject, not by a transactional need like pricing a machine or managing a route — they're here because pinball history is interesting and they want to go deeper. The tagline of The Flip museum is "Preserving the love of pinball for future generations" and this project is a plank of that.

## The Personas

### Reader

People who come to read. They browse pages, look up models, follow links, search.

This is by far the largest group, and the audience whose experience most of the public surface must first be optimized for - if we don't have Readers, we won't have Contributors either.

See [below](#reader-profile) for their motivational picture.

### Contributor

People who add to and improve the site. They write descriptions and essays, upload photos and documents, edit catalog records, and steward the pages they care about.

See [below](#contributor-profile) for their motivational picture.

### Admin

A person that is more trusted than a contributor, something close to a staff member. Probably would get Django Admin access. They operate the site, respond to incidents, review activity, shape the data.

### Maintainer

A member of the [small team](SmallTeam.md) running the project. They have access to source control and production hosting systems, shape the product.

### Co-founder

The co-founders / principals, Moses and William.

## Aliases

Other docs predate this one and use varying terms:

| Role        | Aliases found elsewhere             |
| ----------- | ----------------------------------- |
| Reader      | Visitor, "casual fan", "the public" |
| Contributor | Editor, Writer, "logged-in user"    |
| Admin       | Staff, Superuser                    |
| Maintainer  | Developer                           |

## Future Personas

Potential personas in the future:

- **Moderator** — a Contributor with elevated privileges and responsibilities, that might police less-privileged contributors.

## Reader Profile

"I just played Medieval Madness and now I want to fall down a rabbit hole about Williams in the 90s." The casual fan, the museum visitor, the person just getting into pinball.

Readers come to read — they browse pages, look up models, follow links, search. Often arriving from search engine results, almost always unauthenticated.

### Who Readers are

- People just getting into pinball and wanting the authoritative encyclopedia of all the concepts.
- Casual fans who just played something cool at a bar and want to know more.
- Collectors wanting to learn more about the history of their machines, their significance, the industry context, ideas for other machines to collect.
- The general public of the museum, which is probably mostly casual fans, wanting to explore more about what they've seen, are seeing at the moment (via a kiosk at the museum or their phone) or are about to see before they come.

### Who Readers might be in the future

- Restorers looking for specs, schematics, parts info. We already have a public read-only version of the Flipfix maintenance site that we hope to grow into a deep resource of repair information for the particular models that the museum owns: the entire maintenance history and conversations around maintenance are public. So there's deep interest from the museum in supporting this community. Adding specs, schematics, parts info to this project would absolutely be right in the museum's mission. Dunno, though, whether we can improve on existing sites around this.

### Who Readers are not

The reading experience is not designed for:

- Tournament players who care about rules, competition data.
- Collectors wanting to value what they own.
- Arcade/machine operators managing routes and tracking machine performance.

## Contributor Profile

"I know things about pinball history that aren't captured anywhere, and I want to help build the definitive record." The historian/archivist and the museum-connected enthusiast.

Contributors write descriptions and essays, upload photos and documents, edit catalog records, and steward the pages they care about. They must have an account.

### Who Contributors are

- Historians/archivists who care about preservation for its own sake.
- Museum-connected enthusiasts with deep subject knowledge.

### The opportunity

We suspect there's pent-up demand among amateur pinball writers and historians becuase IPDB, the existing major encyclopedia, has been difficult to work with for years.

This is this project's contributor acquisition strategy: give frustrated IPDB contributors a better home.

### What they contribute

Two distinct activities that attract different people and need different recognition:

**Writing** — original descriptions, historical context, essays on gameplay features (like the evolution of star rollovers), histories of manufacturers, titles, series, people, and places. This is creative, high-effort, high-reward work. It's what makes a page great. A 2,000-word history of Williams' System 11 platform needs to feel like that author's contribution to a shared project, not something that disappeared into the site.

**Uploading** — photos, documents, media. The museum has its own collection of high-quality photos, and people attached to the museum have personal collections. Expect super-uploaders who will upload their entire collection if given an easy way to do so, rather than one-off uploads from random owners. Lower effort per item than writing, more mechanical, but still valuable. Batch upload and bulk tagging are core needs, not nice-to-haves. These people may enjoy having more control over how their photos are presented, giving them more control over layouts... just a hypothesis. We know some of these people and can both ask them and user-test features with them.

Contributors probably won't enter that much structured catalog data — that's already fairly complete for historical models. This may be the way that new models get entered, or we may automate scraping manufacturer sites to get this information.

### What makes it meaningful to them

Both ownership and reputation matter:

- **Stewardship**: The Wikipedia model. "I am the person who maintains the article on Bally Manufacturing, and that matters." The identity comes first; game mechanics (edit counts, awards) reinforce it. Contributors need to feel like stewards of a shared project, not data entry workers for someone else's site.
- **Visibility**: The Pinside model. Contributors are recognized community members. Their name appears on their work, they build a visible contribution history, and the community acknowledges their expertise.

The museum director's background at Wikipedia informs the approach: knowledge as a side-product of well-designed incentives, with stewardship as the foundation and reputation mechanics as reinforcement.
