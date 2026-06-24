"""DB-level constraints on Actor (validate in the database, per DataModeling.md)."""

import pytest
from django.db import IntegrityError, transaction

from apps.actors.models import Actor


@pytest.mark.django_db
def test_resolution_status_check_rejects_invalid():
    with pytest.raises(IntegrityError), transaction.atomic():
        Actor.objects.create(
            backing_model="user", priority=1, resolution_status="bogus"
        )


@pytest.mark.django_db
def test_backing_model_not_blank():
    with pytest.raises(IntegrityError), transaction.atomic():
        Actor.objects.create(backing_model="", priority=1)
