"""Test-only factories for authz unit tests.

The policy engine (`check`) and enforcement wrapper (`enforce`) are
pure functions over the `PolicyUser` Protocol. Their unit tests need
a `PolicyUser`-shaped object but should not hit the DB — a real
`User` row would couple the tests to ORM behavior the engine
deliberately doesn't depend on, and force `@pytest.mark.django_db` on
in-memory logic. Tests that exercise a request path (HTTP client,
force-login) want a real `User` and should use ``make_user`` from
``apps.accounts.test_factories`` instead.
"""

from __future__ import annotations


class StubPolicyUser:
    """A `PolicyUser`-shaped stub that returns canned attribute values.

    `@property` mirrors Django's read-only `User.is_authenticated` /
    `AnonymousUser.is_authenticated`, matching the `@property`
    declarations in the `PolicyUser` Protocol.
    """

    def __init__(
        self,
        *,
        is_authenticated: bool = True,
        is_active: bool = True,
        is_email_verified: bool = True,
        is_staff: bool = False,
        is_superuser: bool = False,
        id: int = 1,
        actor_id: int | None = None,
    ) -> None:
        self.id = id
        self.actor_id = actor_id
        self._is_authenticated = is_authenticated
        self._is_active = is_active
        self._is_email_verified = is_email_verified
        self._is_staff = is_staff
        self._is_superuser = is_superuser

    @property
    def is_authenticated(self) -> bool:
        return self._is_authenticated

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def email_verified(self) -> bool:
        return self._is_email_verified

    @property
    def is_staff(self) -> bool:
        return self._is_staff

    @property
    def is_superuser(self) -> bool:
        return self._is_superuser
