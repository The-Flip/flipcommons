<!-- @component One numbered entry in a citation reference list: the back-link
to its marker, the citation's identity, and the flash that plays when a marker
jumps here. Shared by the rich-text references accordion and the Sources page,
which differ in where the list sits, not in what an entry is. -->
<script lang="ts">
  import CitationBody from '$lib/components/citation/CitationBody.svelte';
  import type { CitationIdentity } from '$lib/components/citation/citation-links';

  let {
    index,
    citation,
    onBackLink,
    highlighted = false,
    onFlashEnd,
    anchorId,
  }: {
    /** The entry's reference number — what its markers render as `[n]`, and
     *  the `data-ref-index` a jump targets. */
    index: number;
    citation: CitationIdentity;
    /** Jump back to the first marker carrying this number. */
    onBackLink: (index: number) => void;
    /** Plays the flash. The parent owns it, so it can drive the entry a marker
     *  just jumped to without this component knowing what triggered it. */
    highlighted?: boolean;
    /** The flash finished — the parent clears `highlighted` here, so jumping to
     *  the same entry twice replays it. */
    onFlashEnd?: () => void;
    /** Fragment target for markers that link here. Opt-in: a page rendering
     *  two reference lists would otherwise mint duplicate ids. */
    anchorId?: string;
  } = $props();
</script>

<li id={anchorId} data-ref-index={index} class:flash={highlighted} onanimationend={onFlashEnd}>
  <button class="back-link" onclick={() => onBackLink(index)} aria-label="Back to citation {index}"
    >&#x21A9;</button
  >
  <CitationBody {citation} layout="inline" />
</li>

<style>
  li {
    margin-bottom: var(--size-2);
    /* Jump target: keep the entry clear of a sticky header when scrolled to. */
    scroll-margin-top: var(--size-5);
  }

  li.flash {
    animation: cite-flash 1.5s ease-out;
  }

  .back-link {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--color-link);
    font-size: var(--font-size-0);
    padding: 0;
    margin-right: var(--size-1);
  }

  .back-link:hover {
    text-decoration: underline;
  }

  /* Scoped per component: `no-unknown-animations` resolves keyframes within a
     stylesheet, so a shared global one would not satisfy it — and Svelte hashes
     a local @keyframes together with the rule referencing it. */
  @keyframes cite-flash {
    from {
      background-color: var(--color-highlight-bg);
    }

    to {
      background-color: transparent;
    }
  }
</style>
