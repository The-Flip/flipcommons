<script lang="ts" module>
  export function initialsFor(input: {
    firstName?: string | null;
    lastName?: string | null;
    username: string;
  }): string {
    const first = (input.firstName ?? '').trim();
    const last = (input.lastName ?? '').trim();
    if (first && last) return (first[0] + last[0]).toUpperCase();
    if (first) return first[0].toUpperCase();
    return input.username.slice(0, 2).toUpperCase();
  }
</script>

<script lang="ts">
  type Props = {
    firstName?: string | null;
    lastName?: string | null;
    username: string;
    size?: string;
  };

  let { firstName, lastName, username, size = '2rem' }: Props = $props();

  const initials = $derived(initialsFor({ firstName, lastName, username }));
</script>

<span class="avatar" style:width={size} style:height={size} aria-hidden="true" data-testid="avatar">
  {initials}
</span>

<style>
  .avatar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    background: var(--color-accent);
    color: var(--color-text-inverse);
    font-size: 0.75em;
    font-weight: 600;
    line-height: 1;
    user-select: none;
  }
</style>
