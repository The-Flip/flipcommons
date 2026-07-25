# Privacy Principles

This is an internal privacy principles doc.

The user-facing privacy policy lives at [frontend/src/routes/(legal)/privacy/+page.svelte](<../frontend/src/routes/(legal)/privacy/+page.svelte>) (served at `/privacy`).

## Core Philosophy

User trust is paramount — it is the foundation of this community. We exist to preserve and share knowledge about pinball history and culture.

Analytics and operational data collection must always support:

- stewardship
- usability
- preservation
- reliability
- community health

## Principles

### Data Minimization

Collect the smallest amount of data necessary to answer legitimate product and operational questions. Avoid speculative collection.

This applies to copies as much as to collection: developer databases refreshed from production are de-identified on the way in, and only the developers who have consented keep their own details. See [Data.md](Data.md#refreshing-localhost-db-from-prod).

### Minimal Public Disclosure

Display the minimum amount of personal information needed for community participation.

Users participate under a chosen username. Real names and other PII are NEVER to be shown publicly without explicit approval by the user. It should go without saying, but email addresses will NEVER be made public.

### No Advertising Ecosystem Participation

We will not:

- sell user data
- participate in behavioral advertising
- share analytics with ad networks
- perform cross-site tracking

### Explicit Instrumentation

Prefer explicit event instrumentation over blanket autocapture.

Preferred:

- intentional workflow events
- aggregate metrics
- scoped diagnostics

Avoid:

- indiscriminate collection
- keystroke capture
- excessive replay systems

### Respectful Session Replay

If session replay is used:

- it must be scoped and limited
- sensitive fields must be masked
- replay must support debugging and usability improvements only

Session replay must never become generalized behavioral surveillance.

### Public Interest Orientation

Analytics must reinforce Flipcommons as:

- a public knowledge resource
- a preservation project
- an enthusiast commons
- an open-web project

rather than a growth-optimization platform.

## Analytics

The principles above govern all data collection. This section applies them specifically to analytics — what we want analytics _for_, how to decide what to instrument, and the cultural frame we use when making those calls.

### Purpose

We use analytics to improve the preservation, discovery, and contribution experience around pinball history and culture.

Analytics exist to support stewardship of a public knowledge commons — not advertising, manipulation, or behavioral extraction.

We view analytics as a tool for:

- reducing contributor friction
- improving discoverability
- understanding preservation gaps
- measuring community health
- improving reliability and usability
- supporting transparent public-interest infrastructure

We do not use analytics to maximize addiction, compulsion, or engagement for its own sake.

### Instrument Behavior, Not People

We are interested in workflows and system behavior, not invasive user profiling.

Examples of healthy analytics:

- abandoned edit flows
- searches with zero results
- upload failures
- article discovery paths
- contribution success rates

Examples of unhealthy analytics:

- behavioral fingerprinting
- engagement addiction metrics
- manipulative notification optimization
- cross-site identity tracking
- predictive behavioral scoring

### Retention

Retention is proportional to identifiability, not measured by clock time. Anonymous, aggregate-shaped data (pageview counts, referrer rollups, search-term frequencies) can be kept indefinitely — the same shape Wikipedia's pageview history takes. Pseudonymous event data is only as long-lived as the user→pseudonym link is unrecoverable; periodic key rotation caps that lifetime even when raw events themselves are retained. Anything directly joinable to a user account should expire quickly.

### Cultural Positioning

We are philosophically closer to:

- Wikipedia
- Archive.org
- OpenStreetMap
- Discogs
- public-interest digital infrastructure

than to advertising-driven social platforms.

When deciding whether to ship a given analytics event or vendor integration, ask: would a project in the list above ship this? If not, that's a strong signal not to.

## Things We Intentionally Avoid

- engagement addiction metrics
- manipulative notification funnels
- infinite-scroll optimization
- dark-pattern retention systems
- behavioral profiling
- fingerprinting
- shadow profiles
- ad-tech integrations
