<script lang="ts">
  import type { IconDefinition } from '@fortawesome/fontawesome-svg-core';

  interface Props {
    icon: IconDefinition;
    class?: string;
    size?: string;
  }

  let { icon, class: className = '', size }: Props = $props();

  let path = $derived(() => {
    const d = icon.icon[4];
    return Array.isArray(d) ? d[0] : d;
  });
</script>

<svg
  viewBox="0 0 {icon.icon[0]} {icon.icon[1]}"
  fill="currentColor"
  class={className}
  aria-hidden="true"
  style:width={size}
  style:height={size}
>
  <path d={path()} />
</svg>
