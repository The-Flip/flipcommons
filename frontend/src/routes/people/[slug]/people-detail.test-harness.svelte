<!--
	SSR render harness for +page.svelte. The page pulls `editAction` from the
	person context that the layout normally provides; this harness wires a
	no-op dispatcher so a test can render the page in isolation without also
	bootstrapping the layout. Test-only — do not import from production code.
-->
<script lang="ts">
  import type { ComponentProps } from 'svelte';
  import { personEditActionContext } from '$lib/components/pages/record/edit/editors/edit-action-context';
  import Page from './+page.svelte';

  const props: ComponentProps<typeof Page> = $props();

  personEditActionContext.setForTesting(() => () => {});
</script>

<Page {...props} />
