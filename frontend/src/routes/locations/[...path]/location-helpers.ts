import type { LocationChildRef, LocationDetailSchema } from '$lib/api/schema';

export type LocationDetail = LocationDetailSchema;
export type LocationChild = LocationChildRef;

const CHILD_TYPE_LABELS: Record<string, string> = {
  country: 'Countries',
  state: 'States',
  region: 'Regions',
  department: 'Departments',
  province: 'Provinces',
  community: 'Communities',
  prefecture: 'Prefectures',
  district: 'Districts',
  county: 'Counties',
  city: 'Cities',
};

const CHILD_TYPE_SINGULAR: Record<string, string> = {
  country: 'Country',
  state: 'State',
  region: 'Region',
  department: 'Department',
  province: 'Province',
  community: 'Community',
  prefecture: 'Prefecture',
  district: 'District',
  county: 'County',
  city: 'City',
};

export function childrenHeading(children: LocationChild[]): string {
  if (children.length === 0) return 'Subdivisions';
  const first = children[0].location_type;
  const allSame = children.every((c) => c.location_type === first);
  return allSame ? (CHILD_TYPE_LABELS[first] ?? 'Subdivisions') : 'Subdivisions';
}

export function childLabelFor(type: string): string {
  // ``divisions`` accepts any non-blank string, so the backend can
  // legitimately return a label not in our hardcoded singular table
  // (e.g. ``oblast``). Capitalize the first character so unknown labels
  // still produce a usable "+ New …" action rather than getting
  // suppressed as if the parent had no valid child type.
  return CHILD_TYPE_SINGULAR[type] ?? type.charAt(0).toUpperCase() + type.slice(1);
}

export function newChildLabel(profile: LocationDetail): string | null {
  // Existing children are the most reliable signal — whatever type they
  // are is what a new sibling will be.
  if (profile.children.length > 0) {
    return childLabelFor(profile.children[0].location_type);
  }
  // No children: trust the backend's server-derived label, which reads
  // from the country ancestor's ``divisions`` list. ``null`` means
  // divisions are missing or exhausted (a structural reason no child
  // type exists); the caller suppresses the "+ New …" action only in
  // that case. Unknown-but-valid labels fall through the humanizer.
  if (profile.expected_child_type) {
    return childLabelFor(profile.expected_child_type);
  }
  return null;
}
