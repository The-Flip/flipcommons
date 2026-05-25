import { env } from '$env/dynamic/private';

/**
 * Gates whether this deploy exposes crawlable robots.txt / sitemap.xml
 * signals to search engines.
 *
 * Read from `$env/dynamic/private` — NOT `$env/static/private`, which
 * would bake the value in at build time and silently misclassify any
 * environment that shares a build artifact.
 *
 * Wire-format enforcement lives in the `core.E301` / `core.E302` deploy
 * check (`backend/apps/core/checks.py`).
 */
export function isDeploymentSearchEngineIndexable(): boolean {
  return env.ALLOW_SEARCH_ENGINE_INDEXING === 'true';
}
