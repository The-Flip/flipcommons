"""System checks for ``policy_activities`` declarations on Ninja schemas.

Verified at ``manage.py check`` (and at server boot) so a schema/activity
mispairing crashes early instead of producing a wrong verdict on the
wire — which is the worst place for it.

A schema declares the target-aware activities whose verdicts it embeds
via a ``ClassVar[PolicyActivities]`` named ``policy_activities``
(``list`` is also accepted, but ``tuple`` is the convention — the
declaration is static and immutable in spirit). This check walks every
ninja ``Schema`` subclass and asserts:

- each listed activity is registered;
- each listed activity is ``target_aware=True`` (a target-less verdict
  belongs on ``AuthStatusSchema.capabilities``, not on a row);
- the schema declares ``policy_target_model: ClassVar[type[Model]]``
  (required — plain ninja Schemas don't expose their underlying model
  otherwise, and the structural check is the *point* of this system
  check; making it opt-in would let a schema author silently skip it);
- every Protocol attribute the registered ``target`` requires must
  exist on the declared model.

Structural Protocol-vs-model conformance is a presence check by design
— if the schema author got the wrong activity onto the wrong schema, the
named-attribute mismatch is the coarse smoke that catches it. The real
safety is the schema author explicitly typing the list.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.apps.config import AppConfig
from django.core.checks import CheckMessage, Error, Tags, register
from ninja import Schema

from .registry import get_rule
from .types import Activity


@register(Tags.models)
def check_policy_activities(
    app_configs: Sequence[AppConfig] | None,
    # ``**kwargs`` is required by Django's check-framework signature; we
    # don't read any of them.
    **kwargs: Any,  # noqa: ANN401
) -> list[CheckMessage]:
    """Validate every ninja Schema subclass that declares ``policy_activities``."""
    _ = app_configs, kwargs
    errors: list[CheckMessage] = []
    visited: set[type] = set()

    def walk(cls: type) -> None:
        for subclass in cls.__subclasses__():
            if subclass in visited:
                continue
            visited.add(subclass)
            walk(subclass)
            errors.extend(_check_one(subclass))

    walk(Schema)
    return errors


def _check_one(schema: type) -> list[CheckMessage]:
    # ``__dict__.get`` deliberately ignores inherited declarations.
    # Each concrete schema declares its own ``policy_activities``;
    # checking the parent already covers the inherited case, so re-
    # checking subclasses would just emit duplicate errors. A subclass
    # that overrides with a different list is checked on its own dict.
    declared = schema.__dict__.get("policy_activities")
    if declared is None:
        return []

    errors: list[CheckMessage] = []
    if not isinstance(declared, list | tuple):
        errors.append(
            Error(
                f"{schema.__name__}.policy_activities must be a tuple or "
                f"list of Activity members, got {type(declared).__name__}.",
                obj=schema,
                id="authz.E101",
            )
        )
        return errors

    for activity in declared:
        if not isinstance(activity, Activity):
            errors.append(
                Error(
                    f"{schema.__name__}.policy_activities contains "
                    f"{activity!r}, which is not an Activity member.",
                    obj=schema,
                    id="authz.E102",
                )
            )
            continue

        rule = get_rule(activity)
        if rule is None:
            errors.append(
                Error(
                    f"{schema.__name__}.policy_activities lists "
                    f"{activity!r} but no rule is registered for it.",
                    obj=schema,
                    id="authz.E103",
                )
            )
            continue

        if not rule.target_aware:
            errors.append(
                Error(
                    f"{schema.__name__}.policy_activities lists "
                    f"{activity!r}, which is not target-aware. Target-less "
                    f"verdicts belong on AuthStatusSchema.capabilities, "
                    f"not on a per-row schema.",
                    obj=schema,
                    id="authz.E104",
                )
            )
            continue

        if rule.target is None:
            # Target-aware but no Protocol declared (wire-slot reservation,
            # like `claim.revert` today). Embedding the verdict is allowed
            # — the policy just has no target attributes to read — but
            # there's nothing to structurally validate against.
            continue

        errors.extend(_check_protocol_against_schema(schema, activity, rule.target))

    # E106: any schema declaring `policy_activities` whose entries
    # require a Protocol structural check must also declare the model
    # to validate against. Skipped if no entry actually has a Protocol
    # (every listed activity is wire-slot-reservation only — no model
    # is needed).
    needs_model = any(
        isinstance(a, Activity)
        and (rule := get_rule(a)) is not None
        and rule.target is not None
        for a in declared
    )
    if needs_model and _underlying_model(schema) is None:
        errors.append(
            Error(
                f"{schema.__name__} declares policy_activities with one "
                f"or more activities whose target Protocol must be "
                f"validated structurally, but the schema has no "
                f"`policy_target_model: ClassVar[type[Model]]` "
                f"declaration. Add `policy_target_model = <YourModel>` "
                f"so the structural check (authz.E105) can verify "
                f"Protocol attributes against the model.",
                obj=schema,
                id="authz.E106",
            )
        )

    return errors


def _check_protocol_against_schema(
    schema: type,
    activity: Activity,
    protocol: type,
) -> list[CheckMessage]:
    """Coarse presence check: the schema's declared model has each Protocol attribute.

    Requires ``policy_target_model: ClassVar[type[Model]]`` on the
    schema (enforced by E106). The schema author's explicit
    ``policy_activities`` declaration remains the primary safeguard;
    this check catches gross mispairings (wrong activity on wrong
    schema, copy-paste errors).
    """
    model = _underlying_model(schema)
    if model is None:
        return []

    errors: list[CheckMessage] = []
    for attr_name in _protocol_attr_names(protocol):
        if not _model_has_attr(model, attr_name):
            errors.append(
                Error(
                    f"{schema.__name__}.policy_activities lists "
                    f"{activity!r}, whose target Protocol "
                    f"{protocol.__name__} requires attribute "
                    f"{attr_name!r}, but the declared "
                    f"policy_target_model {model.__name__} does not "
                    f"expose it. Either the wrong activity is on this "
                    f"schema, or the model is missing the field.",
                    obj=schema,
                    id="authz.E105",
                )
            )
    return errors


def _underlying_model(schema: type) -> type | None:
    """Resolve the Django model the schema's structural check runs against.

    Reads ``policy_target_model`` off the schema's own ``__dict__``;
    inherited declarations are ignored on purpose (each concrete schema
    declares its own pairing). Returns None when no model is declared,
    in which case ``_check_one`` raises ``authz.E106`` if any listed
    activity actually requires a structural check.
    """
    explicit = schema.__dict__.get("policy_target_model")
    return explicit if isinstance(explicit, type) else None


def _protocol_attr_names(protocol: type) -> set[str]:
    """Names declared on a target Protocol — both ``@property`` and annotations.

    Existing target Protocols use ``@property`` (read-only attribute
    surface); bare annotations are also accepted so the check is
    robust to future Protocol shapes.
    """
    names: set[str] = set()
    for attr_name in vars(protocol):
        if attr_name.startswith("_"):
            continue
        names.add(attr_name)
    for attr_name in getattr(protocol, "__annotations__", {}):
        if attr_name.startswith("_"):
            continue
        names.add(attr_name)
    return names


def _model_has_attr(model: type, attr_name: str) -> bool:
    meta = getattr(model, "_meta", None)
    if meta is None:
        return hasattr(model, attr_name)
    # FK ``user_id`` is exposed as the ``user`` field's ``attname``.
    field_names: set[str] = set()
    for field in meta.get_fields():
        field_names.add(field.name)
        attname = getattr(field, "attname", None)
        if attname:
            field_names.add(attname)
    if attr_name in field_names:
        return True
    return hasattr(model, attr_name)
