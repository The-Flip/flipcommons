# pages

This folder contains page shell components.

Each subfolder corresponds to a Sveltekit route pattern, such as:

- `record/detail/` ↔ `/[entity]/[slug]/`
- `record/edit/` ↔ `/[entity]/[slug]/edit/[section]/`

...etc. A new page-kind means a new subfolder under the matching parent.

These are importable only from `routes/` or from within `pages/`. A component
reused outside a page shell belongs elsewhere.
