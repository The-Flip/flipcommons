<script lang="ts">
  import Page from '$lib/components/layout/page/Page.svelte';
  import PageHeader from '$lib/components/layout/page/PageHeader.svelte';
  import { pageTitle } from '$lib/constants';
</script>

<svelte:head>
  <title>{pageTitle('Verify your email')}</title>
</svelte:head>

<Page>
  <PageHeader title="Verify your email" />
  <p>Verify your email to start editing — please check your inbox for a confirmation link.</p>
</Page>
