"""The ActorModel registry and its DB-free class-shape system check."""

import pytest

from apps.accounts.models import User
from apps.accounts.test_factories import make_user
from apps.actors.checks import _check_one, check_actor_models
from apps.actors.models import Actor, ActorModel
from apps.actors.registry import (
    actor_backing_models,
    backing_model_class,
    is_machine_actor,
)
from apps.provenance.models import Source


def test_registry_resolves_user_and_source():
    mapping = actor_backing_models()
    assert mapping["user"] is User
    assert mapping["source"] is Source


def test_is_machine_mapping():
    assert is_machine_actor("user") is False
    assert is_machine_actor("source") is True


def test_backing_model_class_unknown_raises():
    with pytest.raises(ValueError, match="bot"):
        backing_model_class("bot")


def test_system_check_passes_for_real_registry():
    assert check_actor_models(app_configs=None) == []


def test_check_one_flags_missing_is_machine_and_unoverridden_hooks():
    # Synthetic stand-in (mirrors core/checks _check_one tests): exercises the
    # error branches without registering a real Django model.
    class _Malformed:
        __name__ = "Malformed"
        is_machine = "yes"  # not a bool -> actors.E001
        # hooks left as the base's -> actors.E002 x2
        actor_priority = ActorModel.actor_priority
        actor_resolution_status = ActorModel.actor_resolution_status

    ids = {m.id for m in _check_one(_Malformed)}
    assert ids == {"actors.E001", "actors.E002"}


def test_check_one_passes_well_formed_stand_in():
    class _Good:
        __name__ = "Good"
        is_machine = True
        actor_priority = property(lambda self: 1)
        actor_resolution_status = property(lambda self: "active")

    assert _check_one(_Good) == []


@pytest.mark.django_db
def test_every_actor_row_has_a_registered_backing_model():
    # Row-level integrity (a test, NOT the system check): the mint path only
    # ever sets a registered _meta.model_name.
    make_user()
    Source.objects.create(name="IPDB", slug="ipdb", source_type="database")

    registered = set(actor_backing_models())
    assert registered  # sanity
    for backing_model in Actor.objects.values_list("backing_model", flat=True):
        assert backing_model in registered
