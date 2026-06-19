from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "Catalog"

    def ready(self) -> None:
        from . import (
            authz,  # noqa: F401  # registers authz rules at startup
            signals,
        )
        from .claims import register_catalog_relationship_schemas
        from .resolve import register_catalog_resolve_handlers

        signals.connect()
        register_catalog_relationship_schemas()
        register_catalog_resolve_handlers()
        self._register_link_types()
        self._register_autocomplete_types()
        self._register_picker_types()
        self._register_reference_cleanup()

    @staticmethod
    def _register_reference_cleanup() -> None:
        from django.apps import apps

        from apps.core.markdown import MarkdownField
        from apps.core.models import register_reference_cleanup

        models_with_markdown = [
            model
            for model in apps.get_app_config("catalog").get_models()
            if any(isinstance(f, MarkdownField) for f in model._meta.get_fields())
            and not model._meta.abstract
        ]
        if models_with_markdown:
            register_reference_cleanup(*models_with_markdown)

    @staticmethod
    def _register_link_types() -> None:
        """Register one ``LinkType`` per addressable catalog entity.

        Walks ``LinkableModel`` so every URL-addressable entity is renderable
        via ``[[<entity-type>:<public-id>]]`` markdown — even ones absent from the
        wikilink picker (Location). Picker presentation is a separate registry;
        see :meth:`_register_picker_types`.
        """
        from apps.core.wikilinks import LinkType, register

        from ._walks import linkable_models

        for model in linkable_models():
            register(
                LinkType(
                    name=model.entity_type,
                    model_path=f"catalog.{model.__name__}",
                    public_id_field=model.public_id_field,
                    url_pattern=model.link_url_pattern,
                    url_field="public_id",
                    label_field="name",
                )
            )

    @staticmethod
    def _register_autocomplete_types() -> None:
        """Register one ``AutocompleteType`` per autocompletable catalog model.

        Walks ``AutocompletableModel`` and reads each model's autocomplete
        search contract. The ``name`` key is the model's ``entity_type`` — every
        catalog autocompletable model is also a ``LinkableModel`` (they all
        descend from ``CatalogModel``), the ``issubclass`` assert both documents
        that invariant and narrows the type so ``entity_type`` reads cleanly.
        """
        from apps.core.autocomplete import AutocompleteType, register_autocomplete
        from apps.core.models import LinkableModel

        from ._walks import autocompletable_models

        for model in autocompletable_models():
            assert issubclass(model, LinkableModel)
            register_autocomplete(
                AutocompleteType(
                    name=model.entity_type,
                    model_path=f"catalog.{model.__name__}",
                    search_fields=model.autocomplete_search_fields,
                    ordering=model.autocomplete_ordering,
                    select_related=model.autocomplete_select_related,
                )
            )

    @staticmethod
    def _register_picker_types() -> None:
        """Register one ``PickerType`` per catalog model that opts into the picker.

        Walks ``WikilinkableModel`` (a strict subset of ``LinkableModel``).
        Models that are URL-addressable but absent from the picker — Location
        is the live case — inherit ``LinkableModel`` only and so register a
        ``LinkType`` (renderer) but no ``PickerType``. Picker entries carry only
        menu presentation; their search comes from the ``AutocompleteType``
        registered under the same ``entity_type``.
        """
        from apps.core.wikilinks import PickerType, register_picker

        from ._walks import wikilinkable_models

        for model in wikilinkable_models():
            label = model.link_label or str(model._meta.verbose_name).title()
            description = (
                model.link_description or f"Link to a {model._meta.verbose_name}"
            )
            register_picker(
                PickerType(
                    name=model.entity_type,
                    label=label,
                    description=description,
                    sort_order=model.link_sort_order,
                )
            )
