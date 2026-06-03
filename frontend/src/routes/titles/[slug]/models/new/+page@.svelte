<script lang="ts">
  import client from '$lib/api/client';
  import CreatePage from '$lib/components/pages/record/create/CreatePage.svelte';
  import { slugifyForModel } from './model-create';

  let { data } = $props();
  let titleSlug = $derived(data.title.slug);
  let titleName = $derived(data.title.name);
</script>

<CreatePage
  entityLabel="Model"
  heading={`New model in ${titleName}`}
  initialName=""
  submit={(body) =>
    client.POST('/api/titles/{title_public_id}/models/', {
      params: { path: { title_public_id: titleSlug } },
      body,
    })}
  detailHref={(slug) => `/models/${slug}`}
  cancelHref={`/titles/${titleSlug}`}
  parentBreadcrumb={{ text: titleName, href: `/titles/${titleSlug}` }}
  projectSlug={(name) => slugifyForModel(name, titleSlug)}
/>
