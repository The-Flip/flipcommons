<script lang="ts">
  import Button from './Button.svelte';

  let {
    variant,
    fullWidth = false,
  }: { variant?: 'primary' | 'secondary' | 'destructive'; fullWidth?: boolean } = $props();
</script>

<Button {variant} {fullWidth}>Press me</Button>
