<script lang="ts" module>
  type Content = {
    heading: string;
    body: string;
  };

  function contentForStatus(status: number): Content {
    if (status === 404) {
      return {
        heading: 'Page not found',
        body: "We couldn't find what you were looking for. It may have moved or never existed.",
      };
    }
    if (status === 403) {
      return {
        heading: 'Not allowed',
        body: "You don't have access to this page.",
      };
    }
    return {
      heading: 'Something went wrong',
      body: 'An unexpected error occurred. Try again in a moment.',
    };
  }
</script>

<script lang="ts">
  import { page } from '$app/state';
  import Button from '$lib/components/Button.svelte';
  import ErrorPage from '$lib/components/ErrorPage.svelte';

  const content = $derived(contentForStatus(page.status));
</script>

<ErrorPage heading={content.heading} body={content.body}>
  {#snippet cta()}
    <Button tag="a" href="/">Back to home</Button>
  {/snippet}
</ErrorPage>
