<script lang="ts">
  import HierarchicalTaxonomyMobileMetaBar from './HierarchicalTaxonomyMobileMetaBar.svelte';

  let {
    basePath = '/gameplay-features',
    parents = [{ name: 'Physical Feature', public_id: 'physical-feature' }],
    aliases = ['Pop'],
    parentLabel = 'Type of',
    aliasLabel = 'Also known as',
  }: {
    basePath?: string;
    parents?: { name: string; public_id: string }[];
    aliases?: string[];
    parentLabel?: string;
    aliasLabel?: string;
  } = $props();
</script>

<HierarchicalTaxonomyMobileMetaBar {basePath} {parents} {aliases} {parentLabel} {aliasLabel} />
