import type { ClaimSchema } from '$lib/api/schema';

type Claim = ClaimSchema;

export type FieldGroup = { field: string; claims: Claim[] };

export function groupSourcesByField(sources: Claim[]): {
  conflicts: FieldGroup[];
  agreed: FieldGroup[];
  single: FieldGroup[];
} {
  const byField: Record<string, Claim[]> = {};
  for (const claim of sources) {
    (byField[claim.field_name] ??= []).push(claim);
  }

  const conflicts: FieldGroup[] = [];
  const agreed: FieldGroup[] = [];
  const single: FieldGroup[] = [];

  for (const [field, claims] of Object.entries(byField)) {
    const group = { field, claims };
    if (claims.length === 1) {
      single.push(group);
    } else {
      const values = claims.map((c) => JSON.stringify(c.value.raw));
      const allSame = values.every((v) => v === values[0]);
      if (allSame) agreed.push(group);
      else conflicts.push(group);
    }
  }

  return { conflicts, agreed, single };
}
