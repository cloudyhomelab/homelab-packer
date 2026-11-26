# settings netbox-docker reads from no environment variable

ADMIN_GROUP = "admin"

LOGIN_FORM_HIDDEN = True
SOCIAL_AUTH_BACKEND_ATTRS = {"oidc": ("Pocket ID", "login")}
# off by default in social-core's OIDC backend; the pocket-id client requires it
SOCIAL_AUTH_OIDC_USE_PKCE = True

# NetBox's default pipeline plus sync_superuser; re-check against netbox/settings.py on a NetBox
# upgrade, since replacing the setting drops any step NetBox adds to its default.
# netbox-docker registers this file in sys.modules as netbox_configuration_sso.
SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",
    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "netbox.authentication.user_default_groups_handler",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
    "netbox_configuration_sso.sync_superuser",
)


def sync_superuser(backend, user=None, response=None, *args, **kwargs):
    """Grant superuser on every login to members of ADMIN_GROUP and revoke it from everyone else."""
    if user is None:
        return
    groups = (response or {}).get("groups") or []
    is_admin = ADMIN_GROUP in groups
    if user.is_superuser != is_admin:
        user.is_superuser = is_admin
        user.save(update_fields=["is_superuser"])
