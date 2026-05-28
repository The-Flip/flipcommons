import { redirect } from '@sveltejs/kit';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ parent }) => {
  const { model } = await parent();

  // Single-model titles with no variants: redirect to the canonical title page.
  // Never redirect variant models — they have their own detail page.
  if (
    model.title &&
    model.title_models.length === 1 &&
    model.title_models[0].variants.length === 0 &&
    !model.variant_of
  ) {
    redirect(301, `/titles/${model.title.public_id}`);
  }
};
