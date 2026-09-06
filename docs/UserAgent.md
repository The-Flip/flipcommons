# User-Agent

Requests to servers we do not own (Open Library, R2, the Sentry and Railway APIs, any URL a user pasted into a citation form) send:

```text
Flipcommons/1.0 (+https://flipcommons.org/about)
```

Requests the edge smoke suite makes to our own site send:

```text
flipcommons-edge-smoke/1.0
```

| Tree                       | Constant                                                                            |
| -------------------------- | ----------------------------------------------------------------------------------- |
| `backend/apps/`            | `apps.core.user_agent.USER_AGENT`                                                   |
| `production_logs/pull/`    | `pull_common.USER_AGENT`, a separate literal since the pullers do not import Django |
| `backend/edge_tests/`      | `edge_tests.probe.USER_AGENT`                                                       |
| `production_logs/analyze/` | `is_synthetic_ua` in `sql/00_reference.sql`                                         |

## The probe marker

`is_synthetic_ua` marks any request whose agent starts with `flipcommons-`, in any casing, and the health views, `timeline` and `problems` leave marked rows out. A prefix rather than an exact string, so a new probe needs no SQL edit. The marker lives in the User-Agent because Bunny logs no custom headers and a query parameter would change the cache key.

So no outward agent may start with `flipcommons-`. `Flipcommons/1.0` has a slash, and that one character keeps real traffic out of the synthetic bucket. SQL cannot import Python, so `backend/tests/test_synthetic_user_agent.py` pins both sides; the `production_logs/pull` literal is out of its reach.

The probe string is a machine key read only by our own pipeline, so it takes neither the brand capitalization nor a contact URL. Adding `+https://` would also move probe-triggered errors into the `bot` bucket of Sentry's `ua_family` tag.

## The outward string

- **Capitalized** because it is a brand name, like `Googlebot` and `Applebot`; lowercase agents are package names like `curl` and `python-requests`.
- **Not `Flipcommonsbot`.** A `-bot` suffix claims crawler behavior (`robots.txt`, crawl-delay) that `safe_fetch` does not have, and bot-management rules classify on it. If `safe_fetch` ever re-fetches on a schedule, that is crawling, and it gets a `Flipcommonsbot` agent and `robots.txt` support together.
- **`1.0` is a client-behavior generation marker**, not a release version, and stays unwired from `pyproject.toml`. Bump it when a site operator's rule for us would need revisiting: more redirects, JavaScript execution, scheduled re-fetching, anything crawl-shaped. Not for a new subsystem, a timeout change or a deploy.
- **Never the git SHA.** The repo is public and `safe_fetch` fetches user-supplied URLs, so a SHA would tell any site which commit is deployed.
- **`+URL`, not an email**, since agents sent to arbitrary sites are harvested. `/about` gives a stranger context; a page describing our fetching would be a better target if one is written.
- **Hardcoded**, not derived from `SITE_ORIGIN`, which is localhost in development.

SvelteKit SSR sends no agent: its traffic never leaves our origin. SDKs (`sentry_sdk`, `boto3`, `workos`) set their own.
