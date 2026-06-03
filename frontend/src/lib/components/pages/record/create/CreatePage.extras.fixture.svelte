<script lang="ts">
  import CreatePage from './CreatePage.svelte';

  type Created = { slug: string; name: string };

  type Overrides = Partial<{
    extraError: string;
    extraValue: string;
    submit: (body: {
      name: string;
      slug: string;
      note: string;
      citation: unknown;
    }) => Promise<{ data: Created | undefined; error: unknown; response: Response }>;
  }>;

  let { extraError = '', extraValue = 'mfr-x', submit }: Overrides = $props();

  const defaultSubmit = () =>
    Promise.resolve({
      data: { slug: 'ada-lovelace', name: 'Ada Lovelace' },
      error: undefined,
      response: { status: 201, headers: new Headers() } as Response,
    });

  function buildExtra() {
    if (extraError) return { error: extraError };
    if (extraValue === null) return null;
    return { manufacturer_slug: extraValue };
  }
</script>

<CreatePage
  entityLabel="System"
  initialName="Ada"
  submit={submit ?? defaultSubmit}
  detailHref={(slug: string) => `/things/${slug}`}
  cancelHref="/things"
  extraFieldKeys={['manufacturer_slug']}
  extraBody={buildExtra}
>
  {#snippet extraFields({ disabled, errors })}
    <div>
      <label for="extra-input">Extra</label>
      <input
        id="extra-input"
        type="text"
        data-testid="extra-input"
        {disabled}
        value={extraValue ?? ''}
      />
      {#if errors.manufacturer_slug}
        <p data-testid="extra-error">{errors.manufacturer_slug}</p>
      {/if}
    </div>
  {/snippet}
</CreatePage>
