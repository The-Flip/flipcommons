<script lang="ts">
  import { resolve } from '$app/paths';
  import Button from '$lib/components/Button.svelte';

  interface Props {
    titleSlug: string;
    titleName: string;
  }

  let { titleSlug, titleName }: Props = $props();
</script>

<div class="prompt">
  <p class="lead">{titleName} has no models yet.</p>
  <Button tag="a" href={resolve(`/titles/${titleSlug}/models/new`)}>Create first model</Button>
</div>

<style>
  .prompt {
    border: 1px dashed var(--color-border-soft);
    border-radius: var(--radius-2);
    padding: var(--size-5) var(--size-4);
    text-align: center;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--size-2);
    margin-bottom: var(--size-4);
  }

  .lead {
    margin: 0;
    font-size: var(--font-size-2);
    font-weight: 600;
  }
</style>
