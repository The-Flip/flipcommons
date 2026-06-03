<script lang="ts">
  import { resolve } from '$app/paths';

  let { username }: { username: string } = $props();
</script>

<a href={resolve('/users/[username]', { username })}>{username}</a>
