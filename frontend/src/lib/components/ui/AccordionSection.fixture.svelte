<script lang="ts">
  import AccordionSection from './AccordionSection.svelte';

  let editCount = $state(0);
</script>

<AccordionSection heading="Overview" onEdit={() => editCount++}>
  <p>Section content</p>
</AccordionSection>

<p data-testid="edit-count">{editCount}</p>
