<script lang="ts">
  /**
   * Emits a single <script type="application/ld+json"> block into <head>.
   * `data` is the full JSON-LD document (typically `{ "@context": ..., "@graph": [...] }`).
   *
   * The script tag is built via @html rather than a literal element because
   * Svelte treats the contents of a literal <script> tag as opaque text and
   * skips {@html} interpolation inside it.
   */
  let { data }: { data: Record<string, unknown> } = $props();

  // Escape HTML-unsafe characters so the JSON payload cannot break out of
  // the surrounding <script> tag.
  let serialized = $derived(
    JSON.stringify(data).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026'),
  );

  // Split the opening/closing script tags across string concatenation so
  // neither Svelte's parser nor the build pipeline mistakes them for a real
  // <script> block in this component.
  let scriptTag = $derived(
    '<' + 'script type="application/ld+json">' + serialized + '</' + 'script>',
  );
</script>

<svelte:head>
  <!-- eslint-disable-next-line svelte/no-at-html-tags -- serialized is JSON.stringify output with <, >, & escaped -->
  {@html scriptTag}
</svelte:head>
