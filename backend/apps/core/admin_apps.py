from django.contrib.admin.apps import AdminConfig


class FlipAdminConfig(AdminConfig):
    """Make FlipAdminSite the project's default admin site.

    Using ``default_site`` keeps every existing ``@admin.register(...)``
    registration working against the customized site, so the password-form
    override applies everywhere without touching individual ModelAdmins.

    Lives in its own module rather than alongside ``CoreConfig`` because
    Django's app loader rejects any module that exports more than one
    ``AppConfig`` subclass with ``default = True`` (which ``AdminConfig``
    sets and we inherit).
    """

    default_site = "apps.core.admin_site.FlipAdminSite"
