<!-- @component Developer-only panel showing an entity's raw parked IPDB/OPDB source data, for vetting data patches against the text they were derived from. -->
<script lang="ts">
  import { dev } from '$app/environment';
  import AccordionSection from '$lib/components/ui/AccordionSection.svelte';

  let {
    extraData = {},
  }: {
    /** `ModelDetailSchema.extra_data` as the API already delivers it — every
     * winning claim whose `field_name` matched no model field. The API ships
     * this on every request, in production too; this panel is what must not
     * render there, hence the `dev` gate below. */
    extraData?: Record<string, unknown>;
  } = $props();

  /** Keys rendered as labelled sections, in display order. */
  const SECTIONS: { key: string; label: string }[] = [
    { key: 'ipdb.notes', label: 'IPDB notes' },
    { key: 'ipdb.notable_features', label: 'IPDB notable features' },
    { key: 'ipdb.toys', label: 'IPDB toys' },
    { key: 'opdb.features', label: 'OPDB features' },
    { key: 'opdb.keywords', label: 'OPDB keywords' },
    { key: 'opdb.description', label: 'OPDB description' },
    // Despite the `ipdb.` prefix this is not IPDB's own id for the machine —
    // it is the *manufacturer's* model number, which IPDB happens to record.
    // Labelled for what it is so nobody reads it as an IPDB identifier.
    { key: 'ipdb.model_number', label: 'Manufacturer Model ID' },
  ];

  /** Parked keys that are real and expected, but not worth showing: media blobs
   * and the maker-name fields that duplicate resolved columns. Listed rather
   * than filtered server-side so the "unrecognized" bucket below stays
   * meaningful — anything absent from both lists is genuinely a surprise. */
  const SUPPRESSED = new Set([
    'ipdb.image_urls',
    'ipdb.marketing_slogans',
    'ipdb.corporate_entity_name',
    'ipdb.manufacturer_trade_name',
    'opdb.images',
    'opdb.common_name',
  ]);

  /** Denormalized license stamps the resolver appends beside image-field keys. */
  const SUPPRESSED_SUFFIXES = ['.__license_id', '.__permissiveness_rank'];

  function isSuppressed(key: string): boolean {
    return SUPPRESSED.has(key) || SUPPRESSED_SUFFIXES.some((suffix) => key.endsWith(suffix));
  }

  /** Flatten a parked value to text: arrays as comma-separated lists, strings
   * verbatim (they are plain source text, never markdown), anything else as JSON.
   *
   * `JSON.stringify` returns `undefined` (the value, not a string) for
   * `undefined` and for functions, so the fallback is guarded — `display` is
   * typed total and callers render its result directly. */
  function display(value: unknown): string {
    if (typeof value === 'string') return value;
    if (Array.isArray(value) && value.every((v) => typeof v === 'string')) {
      return value.join(', ');
    }
    return JSON.stringify(value, null, 2) ?? String(value);
  }

  /** Whether a parked value has anything to look at. An empty string or empty
   * array is present in the JSON but renders as a heading over a blank block,
   * which reads as "the source said nothing here" rather than "this key was
   * never parked" — so treat it as absent. */
  function hasValue(value: unknown): boolean {
    if (value === undefined || value === null) return false;
    if (typeof value === 'string') return value.trim() !== '';
    if (Array.isArray(value)) return value.length > 0;
    return true;
  }

  const data = $derived(extraData);

  const present = $derived(SECTIONS.filter(({ key }) => hasValue(data[key])));

  /** Keys matching no known section — either stale residue from a resolve that
   * predates the claim's relationship namespace, or a patch that wrote a
   * field name the model does not have. Both are worth a developer's eye,
   * and neither is distinguishable from the value alone, so the UI says so
   * rather than guessing. */
  const unrecognized = $derived(
    Object.keys(data)
      .filter(
        (key) => hasValue(data[key]) && !SECTIONS.some((s) => s.key === key) && !isSuppressed(key),
      )
      .sort(),
  );

  const hasContent = $derived(present.length > 0 || unrecognized.length > 0);
</script>

<!-- `dev` is the production gate. `extra_data` is a long-standing field that the
     API delivers unconditionally — this panel deliberately does not change that —
     so nothing on the wire distinguishes dev from prod and the gate has to live
     here. SvelteKit compiles `dev` to a constant, so the branch is dropped from
     the production bundle entirely.

     Also gated on content: a record with nothing parked (or nothing but
     suppressed keys) would otherwise render a permanently empty accordion, and
     there is no honest empty state to show in its place — "nothing parked" and
     "everything parked was suppressed" are different facts, neither worth a
     section. -->
{#if dev && hasContent}
  <AccordionSection heading="Source Debug" open={true}>
    {#each present as { key, label } (key)}
      <section class="entry">
        <h3>{label}</h3>
        <pre>{display(data[key])}</pre>
      </section>
    {/each}

    {#each unrecognized as key (key)}
      <section class="entry unrecognized">
        <!-- The raw key IS the heading here: unlike the known sections there
             is no friendly label to show, and the key is the thing a
             developer needs in order to find it in the patch. -->
        <h3>{key} <span class="badge">unrecognized field</span></h3>
        <p class="note">
          No model field or relationship matches this claim's field name, so the resolver parked it
          here. Either stale residue from an older resolve, or a patch wrote the wrong field name.
        </p>
        <pre>{display(data[key])}</pre>
      </section>
    {/each}
  </AccordionSection>
{/if}

<style>
  .entry {
    margin-bottom: var(--size-4);
  }

  .entry:last-child {
    margin-bottom: 0;
  }

  /* h3 is the correct level directly under the accordion's own h2, but the
     default h3 renders *larger* than that h2, so a subsection would outrank
     the section containing it. Size it down a step instead of reaching for a
     lower heading level, which would keep the visuals but break the outline. */
  h3 {
    font-size: var(--font-size-1);
    font-weight: 600;
    color: var(--color-text);
    margin: 0 0 var(--size-1);
  }

  .note {
    font-size: var(--font-size-0);
    color: var(--color-text-muted);
    margin: 0 0 var(--size-1);
  }

  /* Preformatted because this is source text, not prose: the IPDB free-text
     fields carry their own line breaks, and a patch author is comparing it
     character-for-character against what the patch claimed. */
  pre {
    font-family: var(--font-mono);
    font-size: var(--font-size-0);
    white-space: pre-wrap;
    overflow-wrap: break-word;
    background: var(--color-surface-muted);
    padding: var(--size-2);
    border-radius: var(--radius-2);
    margin: 0;
  }

  .unrecognized pre {
    border-left: 3px solid var(--color-warning-border);
  }

  .badge {
    font-size: var(--font-size-0);
    font-weight: 400;
    color: var(--color-warning-text);
    background: var(--color-warning-bg);
    border: 1px solid var(--color-warning-border);
    border-radius: var(--radius-1);
    padding: 0 var(--size-1);
    vertical-align: middle;
  }
</style>
