<script lang="ts">
  import { resolve } from '$app/paths';
  import Button from '$lib/components/Button.svelte';

  interface Props {
    manufacturerSlug: string;
    manufacturerName: string;
  }

  let { manufacturerSlug, manufacturerName }: Props = $props();
</script>

<div class="prompt">
  <p class="lead">{manufacturerName} has no corporate entities yet.</p>
  <Button tag="a" href={resolve(`/manufacturers/${manufacturerSlug}/corporate-entities/new`)}>
    Create first corporate entity
  </Button>
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
