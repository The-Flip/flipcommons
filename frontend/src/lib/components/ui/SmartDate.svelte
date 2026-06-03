<script lang="ts">
  import { smartDate, fullDateTime } from '$lib/dates';

  let { iso }: { iso: string } = $props();
</script>

<time datetime={iso} title={fullDateTime(iso)}>{smartDate(iso)}</time>
