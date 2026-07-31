<script lang="ts">
  import ActiveFilterChips, {
    type FilterChipSpec,
  } from '$lib/components/collections/filters/ActiveFilterChips.svelte';
  import ActionMenu from '$lib/components/ui/menu/ActionMenu.svelte';
  import Button from '$lib/components/ui/Button.svelte';
  import MenuDivider from '$lib/components/ui/menu/MenuDivider.svelte';
  import MenuItem from '$lib/components/ui/menu/MenuItem.svelte';
  import MenuSectionHeader from '$lib/components/ui/menu/MenuSectionHeader.svelte';
  import PageHeader from '$lib/components/layout/page/PageHeader.svelte';
  import ThemeSwitcher from './_components/ThemeSwitcher.svelte';
  import Card, {
    type CardDistressCorner,
    type CardDistressType,
  } from '$lib/components/collections/cards/Card.svelte';
  import GameCard from '$lib/components/collections/cards/GameCard.svelte';

  const distressCases: {
    label: string;
    type: CardDistressType;
    corner: CardDistressCorner;
  }[] = [
    { label: 'Torn top left', type: 'torn-corner', corner: 'tl' },
    { label: 'Torn top right', type: 'torn-corner', corner: 'tr' },
    { label: 'Torn bottom left', type: 'torn-corner', corner: 'bl' },
    { label: 'Torn bottom right', type: 'torn-corner', corner: 'br' },
    { label: 'Dog ear top left', type: 'dog-ear', corner: 'tl' },
    { label: 'Dog ear top right', type: 'dog-ear', corner: 'tr' },
    { label: 'Dog ear bottom left', type: 'dog-ear', corner: 'bl' },
    { label: 'Dog ear bottom right', type: 'dog-ear', corner: 'br' },
  ];

  let demoChips = $state([
    { key: 'manufacturer:williams', label: 'Williams' },
    { key: 'themes:sci-fi', label: 'Science fiction' },
    { key: 'year', label: 'Year: 1980–1995' },
  ]);
  let filterChips = $derived(
    demoChips.map((chip): FilterChipSpec => ({
      ...chip,
      remove: () => (demoChips = demoChips.filter((c) => c.key !== chip.key)),
    })),
  );
</script>

<div class="lab-header">
  <PageHeader title="Style Lab" subtitle="UI samples for judging palette and texture changes." />
  <div class="theme-control">
    <ThemeSwitcher />
  </div>
</div>
<div class="style-lab">
  <section class="specimen">
    <div class="section-heading">
      <h2>Reference Search</h2>
      <p>Primary content, links, buttons, and form controls.</p>
    </div>

    <div class="search-panel">
      <label for="lab-search">Catalog search</label>
      <div class="search-row">
        <input id="lab-search" type="search" value="bally space invaders" />
        <Button>Search</Button>
      </div>
      <p>
        Match results across <a href="/titles">titles</a>, manufacturers, people, systems, and
        gameplay features.
      </p>
    </div>
  </section>

  <section class="specimen">
    <div class="section-heading">
      <h2>Detail Surface</h2>
      <p>Dense record content with status chips and sidebar treatment.</p>
    </div>

    <div class="detail-shell">
      <article class="record-panel">
        <div class="record-kicker">Machine model</div>
        <h3>Attack from Mars</h3>
        <p>
          A widebody-feeling fan favorite with saucers, martians, stroke-heavy callouts, and
          unusually broad collector recognition.
        </p>
        <div class="chip-row" aria-label="Metadata">
          <span>Williams</span>
          <span>1995</span>
          <span>Solid state</span>
        </div>
      </article>

      <aside class="sidebar-panel">
        <h3>Claims</h3>
        <dl>
          <div>
            <dt>Status</dt>
            <dd>Reviewed</dd>
          </div>
          <div>
            <dt>Sources</dt>
            <dd>IPDB, flyers, operator manual</dd>
          </div>
        </dl>
      </aside>
    </div>
  </section>

  <section class="specimen">
    <div class="section-heading">
      <h2>System States</h2>
      <p>Feedback colors, menu surface, and secondary actions.</p>
    </div>

    <div class="states-grid">
      <div class="status-card success">Saved changes to manufacturer claims.</div>
      <div class="status-card warning">Three citations need locator details.</div>
      <div class="status-card error">Slug conflicts with an existing record.</div>
      <div class="filter-state-card">
        <div class="state-label">Active filters</div>
        <ActiveFilterChips chips={filterChips} />
      </div>
      <div class="action-cluster">
        <Button variant="secondary">Cancel</Button>
        <Button>Save changes</Button>
        <ActionMenu label="Actions">
          <MenuSectionHeader>record</MenuSectionHeader>
          <MenuItem>View sources</MenuItem>
          <MenuItem>Open edit history</MenuItem>
          <MenuDivider />
          <MenuItem>Request review</MenuItem>
        </ActionMenu>
      </div>
    </div>
  </section>
  <section class="specimen">
    <div class="section-heading">
      <h2>Form Controls</h2>
      <p>
        Input surfaces, focus rings, validation feedback, disabled states, and button variants.
        Click any control to verify the focus ring against the page background.
      </p>
    </div>

    <div class="form-grid">
      <div class="form-row">
        <label for="lab-text">Text</label>
        <input id="lab-text" type="text" value="Williams" />
      </div>
      <div class="form-row">
        <label for="lab-email">Email</label>
        <input id="lab-email" type="email" placeholder="curator@flipcommons.org" />
      </div>
      <div class="form-row">
        <label for="lab-number">Year</label>
        <input id="lab-number" type="number" value="1995" />
      </div>
      <div class="form-row">
        <label for="lab-select">Manufacturer</label>
        <select id="lab-select">
          <option>Williams</option>
          <option>Bally</option>
          <option>Stern</option>
        </select>
      </div>
      <div class="form-row form-row--wide">
        <label for="lab-textarea">Notes</label>
        <textarea id="lab-textarea" rows="3"
          >Citation pending operator manual confirmation.</textarea
        >
      </div>
      <div class="form-row">
        <label for="lab-invalid">Invalid</label>
        <input id="lab-invalid" type="text" value="not-a-valid-slug!" aria-invalid="true" />
      </div>
      <div class="form-row">
        <label for="lab-disabled">Disabled</label>
        <input id="lab-disabled" type="text" value="Read-only field" disabled />
      </div>

      <fieldset class="form-row form-row--wide">
        <legend>Choice inputs</legend>
        <div class="choice-row">
          <label class="choice"><input type="checkbox" checked /> Verified</label>
          <label class="choice"><input type="checkbox" /> Featured</label>
          <label class="choice"><input type="checkbox" disabled checked /> Locked</label>
        </div>
        <div class="choice-row">
          <label class="choice"><input type="radio" name="lab-radio" checked /> Solid state</label>
          <label class="choice"><input type="radio" name="lab-radio" /> Electromechanical</label>
          <label class="choice"><input type="radio" name="lab-radio" disabled /> Mechanical</label>
        </div>
      </fieldset>

      <div class="form-row form-row--wide">
        <span class="form-label">Buttons: active • disabled</span>
        <div class="action-cluster">
          <Button>Save</Button>
          <Button variant="secondary">Cancel</Button>
          •
          <Button disabled>Save</Button>
          <Button variant="secondary" disabled>Cancel</Button>
        </div>
      </div>
    </div>
  </section>

  <section class="specimen">
    <div class="section-heading">
      <h2>Editor Dialog</h2>
      <p>Buttons are inert.</p>
    </div>

    <div class="editor-stage" aria-hidden="true">
      <div class="stage-backdrop">
        <h3>Attack from Mars</h3>
        <p>
          A widebody-feeling fan favorite with saucers, martians, stroke-heavy callouts, and
          unusually broad collector recognition. Sourced from IPDB, flyers, and operator manuals.
        </p>
        <div class="chip-row">
          <span>Williams</span>
          <span>1995</span>
          <span>Solid state</span>
        </div>
      </div>

      <div class="stage-scrim">
        <!--
          Visually mirrors Modal.svelte's `.modal-dialog` / `-header` /
          `-body` / `-footer`. Uses the same tokens (--color-bg,
          --color-border, --radius-3, --shadow-modal) so theme changes
          carry across identically. If Modal's structure or tokens
          change, update here too — Modal.svelte is the source of truth.
        -->
        <div class="editor-dialog">
          <header class="editor-header">
            <h3>Name <span aria-hidden="true">▾</span></h3>
            <button type="button" class="editor-close" aria-label="Close">×</button>
          </header>
          <div class="editor-body">
            <div class="form-row">
              <label for="lab-edit-name">Name</label>
              <input id="lab-edit-name" type="text" value="Bally" />
            </div>
            <div class="form-row">
              <label for="lab-edit-slug">Slug</label>
              <input id="lab-edit-slug" type="text" value="bally" />
            </div>
            <details class="notes-citations">
              <summary>Notes &amp; Citations</summary>
              <div class="form-row">
                <label for="lab-edit-note">Note (optional, public)</label>
                <input id="lab-edit-note" type="text" placeholder="Why this edit?" />
              </div>
            </details>
          </div>
          <footer class="editor-footer">
            <Button variant="secondary">Cancel</Button>
            <Button>Save</Button>
          </footer>
        </div>
      </div>
    </div>
  </section>

  <section class="specimen">
    <div class="section-heading">
      <h2>Catalog Cards</h2>
      <p>Polaroid cards, muted metadata, and link contrast.</p>
    </div>

    <div class="card-grid">
      <GameCard
        entityType="model"
        publicId="go-go"
        name="Go Go"
        thumbnailUrl="/fakes/fake_backglass1.avif"
        manufacturerName="Williams"
        year={1966}
      />
      <GameCard
        entityType="model"
        publicId="critters"
        name="Critters"
        thumbnailUrl="/fakes/fake_backglass2.avif"
        manufacturerName="Jersey Jack"
        year={2023}
      />
      <GameCard
        entityType="model"
        publicId="astro-blitz"
        name="Astro Blitz"
        thumbnailUrl="/fakes/fake_backglass3.avif"
        manufacturerName="Williams"
        year={1982}
      />
    </div>
  </section>

  <section class="specimen">
    <div class="section-heading">
      <h2>Torn Surfaces</h2>
      <p>Forced wear-effect variants for visually debugging every distressed card corner.</p>
    </div>

    <div class="distress-grid">
      {#each distressCases as distressCase (distressCase.label)}
        <Card
          href="/style-lab"
          title={distressCase.label}
          distressType={distressCase.type}
          distressCorner={distressCase.corner}
          distressEarSize={1.7}
        >
          <p class="distress-note">{distressCase.type} · {distressCase.corner}</p>
        </Card>
      {/each}
      <Card
        href="/style-lab"
        title="Crease"
        distressType="crease"
        distressCorner="tl"
        distressCreaseAngle={-16}
        distressCreasePos={44}
      >
        <p class="distress-note">crease · fixed angle</p>
      </Card>
    </div>
  </section>
</div>

<style>
  .style-lab {
    display: grid;
    gap: var(--size-7);
  }

  .lab-header {
    align-items: flex-start;
    border-bottom: 1px solid var(--color-border-soft);
    display: flex;
    gap: var(--size-5);
    justify-content: space-between;
    margin-bottom: var(--size-5);
    padding-bottom: var(--size-4);
  }

  .theme-control {
    display: flex;
    align-items: center;
    gap: var(--size-2);
    color: var(--color-text-muted);
    font-size: var(--font-size-1);
  }

  .specimen {
    display: grid;
    gap: var(--size-4);
  }

  .section-heading {
    max-width: 42rem;
  }

  .section-heading h2 {
    font-size: var(--font-size-4);
    margin-bottom: var(--size-1);
  }

  .section-heading p,
  .search-panel p,
  .record-panel p {
    color: var(--color-text-muted);
    line-height: 1.55;
  }

  .search-panel,
  .record-panel,
  .sidebar-panel,
  .filter-state-card,
  .status-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    box-shadow: var(--shadow-card);
  }

  .search-panel {
    padding: var(--size-5);
    display: grid;
    gap: var(--size-3);
  }

  .search-panel label {
    font-weight: 600;
    color: var(--color-text);
  }

  .search-row {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: var(--size-3);
    align-items: center;
  }

  .card-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--size-4);
  }

  .distress-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: var(--size-4);
  }

  .distress-note {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
  }

  .detail-shell {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(16rem, 1fr);
    gap: var(--size-4);
  }

  .record-panel,
  .sidebar-panel {
    padding: var(--size-5);
  }

  .record-kicker {
    color: var(--color-link);
    font-size: var(--font-size-0);
    font-weight: 700;
    margin-bottom: var(--size-2);
    text-transform: uppercase;
  }

  .record-panel h3,
  .sidebar-panel h3 {
    font-size: var(--font-size-4);
    margin-bottom: var(--size-2);
  }

  .chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-2);
    margin-top: var(--size-4);
  }

  .chip-row span {
    background: var(--color-surface-muted);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-2);
    color: var(--color-text);
    font-size: var(--font-size-0);
    font-weight: 600;
    padding: var(--size-1) var(--size-2);
  }

  .sidebar-panel dl {
    display: grid;
    gap: var(--size-3);
  }

  .sidebar-panel div {
    border-top: 1px solid var(--color-border-soft);
    padding-top: var(--size-3);
  }

  .sidebar-panel dt {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    margin-bottom: var(--size-1);
  }

  .sidebar-panel dd {
    color: var(--color-text);
  }

  .states-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: var(--size-3);
  }

  .status-card {
    padding: var(--size-4);
    font-weight: 600;
  }

  .filter-state-card {
    display: grid;
    gap: var(--size-2);
    grid-column: 1 / -1;
    padding: var(--size-4);
  }

  .state-label {
    color: var(--color-text-muted);
    font-size: var(--font-size-0);
    font-weight: 700;
    text-transform: uppercase;
  }

  .success {
    background: var(--color-success-bg);
    border-color: var(--color-success-border);
    color: var(--color-success-text);
  }

  .warning {
    background: var(--color-warning-bg);
    border-color: var(--color-warning-border);
    color: var(--color-warning-text);
  }

  .error {
    background: var(--color-error-bg);
    border-color: var(--color-error-border);
    color: var(--color-error-text);
  }

  .action-cluster {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-2);
    align-items: center;
    grid-column: 1 / -1;
  }

  /* Editor dialog: faithful inline re-render of Modal.svelte's chrome so
     the dialog can be judged by scrolling without trapping focus or
     locking page scroll. Token usage mirrors Modal.svelte's styles; if
     Modal changes, update here too. */
  .editor-stage {
    border-radius: var(--radius-2);
    min-height: 38rem;
    overflow: hidden;
    position: relative;
  }

  .stage-backdrop {
    align-items: start;
    background: var(--color-surface);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    display: grid;
    gap: var(--size-3);
    height: 100%;
    padding: var(--size-5);
  }

  .stage-backdrop h3 {
    font-size: var(--font-size-4);
  }

  .stage-scrim {
    background: var(--color-scrim);
    display: grid;
    inset: 0;
    padding: var(--size-5);
    place-items: center;
    position: absolute;
  }

  /* Mirrors Modal.svelte `.modal-dialog`. */
  .editor-dialog {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-3);
    box-shadow: var(--shadow-modal);
    display: flex;
    flex-direction: column;
    max-width: 36rem;
    overflow: hidden;
    width: 100%;
  }

  /* Mirrors Modal.svelte `.modal-header`. */
  .editor-header {
    align-items: center;
    border-bottom: 1px solid var(--color-border-soft);
    display: flex;
    gap: var(--size-3);
    justify-content: space-between;
    padding: var(--size-3) var(--size-4);
  }

  .editor-header h3 {
    align-items: center;
    color: var(--color-text);
    display: inline-flex;
    font-size: var(--font-size-3);
    font-weight: 600;
    gap: var(--size-1);
    margin: 0;
  }

  .editor-close {
    background: none;
    border: 0;
    color: var(--color-text-muted);
    cursor: pointer;
    font-size: 1.5rem;
    line-height: 1;
    padding: var(--size-1);
  }

  .editor-close:hover {
    color: var(--color-text);
  }

  .editor-body {
    display: grid;
    gap: var(--size-4);
    padding: var(--size-4);
  }

  /* Mirrors Modal.svelte `.modal-footer`. */
  .editor-footer {
    align-items: center;
    border-top: 1px solid var(--color-border-soft);
    display: flex;
    gap: var(--size-2);
    justify-content: flex-end;
    padding: var(--size-3) var(--size-4);
  }

  /* Mirrors NotesAndCitationsDetails.svelte. `background: inherit` on
     both the details and the summary suppresses the user agent's
     default summary background (a subtle blue/grey tint in Chrome) so
     the row picks up the dialog's --color-bg cleanly. */
  .notes-citations {
    background: inherit;
    border-top: 1px solid var(--color-border-soft);
    margin-top: var(--size-4);
    padding-top: var(--size-3);
  }

  .notes-citations > summary {
    background: inherit;
    color: var(--color-text-muted);
    cursor: pointer;
    font-size: var(--font-size-0);
    user-select: none;
  }

  .notes-citations summary + .form-row {
    margin-top: var(--size-3);
  }

  .form-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--size-3);
    background: var(--color-surface);
    border: 1px solid var(--color-border-soft);
    border-radius: var(--radius-2);
    box-shadow: var(--shadow-card);
    padding: var(--size-5);
  }

  .form-row {
    display: grid;
    gap: var(--size-1);
  }

  .form-row--wide {
    grid-column: 1 / -1;
  }

  .form-row label,
  .form-row legend,
  .form-label {
    color: var(--color-text);
    font-size: var(--font-size-1);
    font-weight: 600;
  }

  /* Fieldset keeps its semantic grouping but loses the border — the muted
     bg already separates it from the surrounding form-grid surface. Float
     pulls the legend out of its default "straddle the top border"
     rendering so it behaves like a normal block label and doesn't clash
     with the fieldset's rounded corners or split across two surfaces. */
  .form-grid fieldset {
    background: var(--color-surface-muted);
    border: 0;
    border-radius: var(--radius-2);
    display: grid;
    gap: var(--size-2);
    padding: var(--size-3) var(--size-4);
  }

  .form-grid fieldset legend {
    float: left;
    margin: 0;
    padding: 0;
    width: 100%;
  }

  .choice-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--size-4);
  }

  .choice {
    align-items: center;
    display: inline-flex;
    font-size: var(--font-size-1);
    font-weight: 400;
    gap: var(--size-1);
  }

  @media (--breakpoint-narrow) {
    .lab-header {
      display: grid;
      gap: var(--size-3);
    }

    .search-row,
    .card-grid,
    .distress-grid,
    .detail-shell,
    .states-grid,
    .form-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
