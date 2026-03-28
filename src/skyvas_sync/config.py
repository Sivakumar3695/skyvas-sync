"""Application configuration for different environments."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable application configuration."""

    cognito_domain: str
    client_id: str
    user_pool_id: str
    region: str
    api_base_url: str
    redirect_uri: str = "http://localhost:8585/callback"
    local_server_port: int = 8585
    oauth_scopes: str = "email openid profile aws.cognito.signin.user.admin"

    @property
    def authorize_url(self) -> str:
        """Cognito OAuth2 authorize endpoint."""
        return f"https://{self.cognito_domain}/oauth2/authorize"

    @property
    def token_url(self) -> str:
        """Cognito OAuth2 token endpoint."""
        return f"https://{self.cognito_domain}/oauth2/token"


STAGING = Config(
    cognito_domain="staging-auth.skyvas.in",
    client_id="q4g5opnshgjoq1truddsghupe",
    user_pool_id="ap-south-1_xZn3hC5D3",
    region="ap-south-1",
    api_base_url="https://staging-muga400.skyvas.in/api/v1",
)

PRODUCTION = Config(
    cognito_domain="muga400.auth.ap-south-1.amazoncognito.com",
    client_id="49rg8en6nkl5ui4f1molibo8ki",
    user_pool_id="ap-south-1_7KBQJW7fL",
    region="ap-south-1",
    api_base_url="https://muga400.skyvas.in/api/v1",
)

_CONFIGS = {"staging": STAGING, "production": PRODUCTION}


def get_config(env: str | None = None) -> Config:
    """Return configuration for the given environment.

    Falls back to the ``SKYVAS_ENV`` environment variable, defaulting to
    ``"staging"``.
    """
    if env is None:
        env = os.environ.get("SKYVAS_ENV", "staging")
    return _CONFIGS.get(env, STAGING)
