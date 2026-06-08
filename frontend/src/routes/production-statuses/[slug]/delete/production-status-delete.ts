import { createDeleteSubmitter } from '$lib/delete-flow';

export const submitDelete = createDeleteSubmitter('production-statuses');
