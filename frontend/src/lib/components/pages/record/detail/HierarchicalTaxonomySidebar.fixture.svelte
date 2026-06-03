<script lang="ts">
  import HierarchicalTaxonomySidebar from './HierarchicalTaxonomySidebar.svelte';

  let {
    basePath = '/gameplay-features',
    parents = [{ name: 'Physical Feature', public_id: 'physical-feature' }],
    children = [
      { name: 'Slingshot', public_id: 'slingshot' },
      { name: 'Bumper', public_id: 'bumper' },
    ],
    aliases = ['Pop'],
    parentHeading = 'Type of',
    childHeading = 'Subtypes',
    aliasHeading = 'Also known as',
  }: {
    basePath?: string;
    parents?: { name: string; public_id: string }[];
    children?: { name: string; public_id: string }[];
    aliases?: string[];
    parentHeading?: string;
    childHeading?: string;
    aliasHeading?: string;
  } = $props();
</script>

<HierarchicalTaxonomySidebar
  {basePath}
  {parents}
  {children}
  {aliases}
  {parentHeading}
  {childHeading}
  {aliasHeading}
/>
