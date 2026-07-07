<!-- @component Generic soft-delete confirmation page: impact/blocked preview, deletion note + citations and the undoable delete submit. -->
<script lang="ts" generics="TResponse extends { changeset_id: number }">
  import { goto } from '$app/navigation';
  import Button from '$lib/components/ui/Button.svelte';
  import NotesAndCitationsDetails from '$lib/components/input/citation/NotesAndCitationsDetails.svelte';
  import { pageTitle } from '$lib/constants';
  import type { DeleteOutcome } from '$lib/delete-flow';
  import type { EditCitationSelection } from '$lib/edit-citation';
  import { toast } from '$lib/toast/toast.svelte';
  import { submitUndoDelete } from '$lib/undo-delete';
  import { resolveHref } from '$lib/utils';
  import type { BlockedState, ImpactState, ParentBreadcrumb } from './delete-page';

  type Props = {
    entityLabel: string;
    entityName: string;
    public_id: string;
    submit: (
      public_id: string,
      opts: { note: string; citations: EditCitationSelection[] },
    ) => Promise<DeleteOutcome<TResponse>>;
    cancelHref: string;
    redirectAfterDelete: string;
    editHistoryHref: string;
    parentBreadcrumb?: ParentBreadcrumb;
    blocked: BlockedState | null;
    impact: ImpactState;
    noteHint?: string;
  };

  let {
    entityLabel,
    entityName,
    public_id,
    submit,
    cancelHref,
    redirectAfterDelete,
    editHistoryHref,
    parentBreadcrumb,
    blocked,
    impact,
    noteHint,
  }: Props = $props();

  let note = $state('');
  let citations = $state<EditCitationSelection[]>([]);
  let formError = $state('');
  let submitting = $state(false);

  let isBlocked = $derived(blocked !== null);
  let heading = $derived(isBlocked ? `Can't delete “${entityName}”` : `Delete “${entityName}”?`);
  let headTitle = $derived(isBlocked ? `Can't delete ${entityName}` : `Delete ${entityName}?`);
  let hint = $derived(noteHint ?? `Why are you deleting this ${entityLabel.toLowerCase()}?`);

  async function handleDelete() {
    formError = '';
    submitting = true;
    try {
      const outcome = await submit(public_id, { note, citations });
      switch (outcome.kind) {
        case 'ok': {
          const name = entityName;
          const changesetId = outcome.data.changeset_id;
          const handle = toast.success(`Deleted “${name}”.`, {
            persistUntilNav: true,
            dwellMs: 8_000,
            action: {
              label: 'Undo',
              onAction: async () => {
                const undo = await submitUndoDelete(changesetId);
                switch (undo.kind) {
                  case 'ok':
                    handle.update(`Restored “${name}”.`, { dwellMs: 4_000 });
                    return;
                  case 'superseded':
                    handle.update(undo.message, {
                      dwellMs: 8_000,
                      href: editHistoryHref,
                    });
                    return;
                  case 'form_error':
                    handle.update(undo.message, { dwellMs: 8_000 });
                    return;
                }
              },
            },
          });
          await goto(resolveHref(redirectAfterDelete));
          return;
        }
        case 'rate_limited':
          formError = outcome.message;
          return;
        case 'blocked':
          // Shouldn't normally reach here — preview should have shown
          // blockers — but handle defensively if state changed between
          // preview and submit.
          formError = outcome.message;
          return;
        case 'form_error':
          formError = outcome.message;
          return;
      }
    } finally {
      submitting = false;
    }
  }

  function handleCancel() {
    goto(resolveHref(cancelHref));
  }
</script>

<svelte:head>
  <title>{pageTitle(headTitle)}</title>
</svelte:head>

<div class="delete-page">
  <header class="hdr">
    <h1>{heading}</h1>
    {#if parentBreadcrumb}
      <p class="parent-ref">
        under <a href={resolveHref(parentBreadcrumb.href)}>{parentBreadcrumb.text}</a>
      </p>
    {/if}
  </header>

  {#if blocked}
    <section class="blocked">
      <p class="blocked-lead">{blocked.lead}</p>
      {#if blocked.kind === 'referrers'}
        <ul>
          {#each blocked.referrers as ref (`${ref.entity_type}|${ref.slug ?? ''}|${ref.relation}`)}
            {@const href = blocked.renderReferrerHref?.(ref) ?? null}
            <li>
              {#if href}
                <a href={resolveHref(href)}>{ref.name}</a>
              {:else}
                {ref.name}
              {/if}
              <span class="muted">{blocked.renderReferrerHint(ref)}</span>
            </li>
          {/each}
        </ul>
        {#if blocked.footer}
          <p class="muted">{blocked.footer}</p>
        {/if}
      {/if}
    </section>
  {:else}
    <section class="impact">
      <p>This will hide:</p>
      <ul>
        {#each impact.items as item (item)}
          <li>{item}</li>
        {/each}
      </ul>
      <p class="muted">{impact.note}</p>
    </section>
  {/if}

  {#if formError}
    <p class="save-error" role="alert">{formError}</p>
  {/if}

  {#if !isBlocked}
    <NotesAndCitationsDetails bind:note bind:citations noteLabel="Deletion note" noteHint={hint} />
  {/if}

  <div class="form-footer">
    <Button variant="secondary" onclick={handleCancel}>Cancel</Button>
    {#if !isBlocked}
      <Button onclick={handleDelete} disabled={submitting}>
        {submitting ? 'Deleting…' : `Delete ${entityLabel}`}
      </Button>
    {/if}
  </div>
</div>

<style>
  .delete-page {
    max-width: 36rem;
    margin: 0 auto;
    padding: var(--size-6) var(--size-5);
    display: flex;
    flex-direction: column;
    gap: var(--size-4);
  }

  .hdr h1 {
    margin: 0 0 var(--size-2);
  }

  .parent-ref {
    margin: 0;
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  .impact,
  .blocked {
    background: var(--color-surface-muted);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--size-2);
    padding: var(--size-3) var(--size-4);
  }

  .impact ul,
  .blocked ul {
    margin: var(--size-2) 0;
    padding-left: var(--size-4);
  }

  .impact li,
  .blocked li {
    margin: var(--size-1) 0;
  }

  .blocked-lead {
    margin: 0 0 var(--size-2);
  }

  .save-error {
    color: var(--color-error-text);
    font-size: var(--font-size-1);
    margin: 0;
  }

  .form-footer {
    display: flex;
    justify-content: flex-end;
    gap: var(--size-3);
    margin-top: var(--size-4);
    padding-top: var(--size-3);
    border-top: 1px solid var(--color-border-soft);
  }
</style>
