/**
 * The frontend citation-type registry.
 *
 * One entry per registered type, keyed by the generated `CitationTypeKey`
 * union — so a backend type without a frontend module fails `svelte-check`,
 * not the user. Components consult this registry (and the generated
 * `CITATION_TYPE_META`) instead of naming a type; search results, recognition
 * responses and mint responses all carry `source_type` as the lookup key.
 */
import {
  CITATION_TYPE_META,
  type CitationTypeKey,
  type CitationTypeMeta,
} from './citation-type-meta';
import { freeformType, type CitationTypeFrontend } from './frontend-types';
import { videoType } from './video';

/** Exhaustive by construction: `Record<CitationTypeKey, …>` makes a missing
 * or extra entry a compile error after `make codegen` regenerates the keys. */
const CITATION_TYPE_FRONTENDS: Record<CitationTypeKey, CitationTypeFrontend> = {
  book: freeformType,
  magazine: freeformType,
  web: freeformType,
  video: videoType,
};

function isCitationTypeKey(sourceType: string): sourceType is CitationTypeKey {
  return sourceType in CITATION_TYPE_META;
}

/**
 * The declarative meta for a source's type. Falls back to the freeform book
 * row when the type is unknown or absent (an older API payload without
 * `source_type`) — the flow degrades to today's generic locator prompt.
 */
export function citationTypeMeta(sourceType: string): CitationTypeMeta {
  return isCitationTypeKey(sourceType) ? CITATION_TYPE_META[sourceType] : CITATION_TYPE_META.book;
}

/** The behavior module for a source's type, with the same freeform fallback. */
export function citationTypeFrontend(sourceType: string): CitationTypeFrontend {
  return isCitationTypeKey(sourceType) ? CITATION_TYPE_FRONTENDS[sourceType] : freeformType;
}
