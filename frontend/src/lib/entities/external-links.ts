import type { EntityInfo, ExternalReference } from './types';

/** A resolvable external-database link: a human label and a ready-to-use href. */
export interface ExternalLink {
  label: string;
  href: string;
}

/**
 * The resolvable external-database links for an entity, in declaration order.
 *
 * Walks the entity's `externalRefs` registry: each `{ label, urlTemplate }` entry
 * with a present value yields a link (`{id}` ← the stored value); `{ identifier }`
 * entries are JSON-LD-only and produce nothing here. The same registry feeds
 * the JSON-LD `sameAs`/`identifier` in `buildSchemaOrgNode`, so the visible
 * links and the structured-data identities can never drift apart.
 *
 * Compose across entities for pages that surface more than one (e.g. a Title
 * page shows its Model's IPDB/Pinside links plus the Title's Fandom link):
 * `[...externalLinks(md, modelInfo), ...externalLinks(title, titleInfo)]`.
 */
export function externalLinks<T>(entity: T, info: EntityInfo<T>): ExternalLink[] {
  const links: ExternalLink[] = [];
  const map: Partial<Record<keyof T, ExternalReference>> = info.externalRefs ?? {};
  for (const key of Object.keys(map) as (keyof T)[]) {
    const entry = map[key];
    if (entry === undefined || !('urlTemplate' in entry)) continue;
    const value = entity[key];
    // Same skip rule as the JSON-LD assembler: null / undefined / empty string.
    if (value === null || value === undefined || value === '') continue;
    links.push({
      label: entry.showId ? `${entry.label} #${String(value)}` : entry.label,
      href: entry.urlTemplate.replace('{id}', String(value)),
    });
  }
  return links;
}
