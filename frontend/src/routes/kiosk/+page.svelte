<script lang="ts">
  import KioskHome from '$lib/kiosk/KioskHome.svelte';
  import StatusMessage from '$lib/components/ui/StatusMessage.svelte';
  import { resolve } from '$app/paths';

  let { data } = $props();
</script>

{#if data.kioskConfig}
  <KioskHome config={data.kioskConfig} />
{:else}
  <StatusMessage variant="empty">
    This device isn't set up as a kiosk. Visit
    <a href={resolve('/kiosk/edit')}>/kiosk/edit</a> to choose a kiosk.
  </StatusMessage>
{/if}
