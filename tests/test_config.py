"""Tests for skyvas_sync.config."""

import os
from unittest.mock import patch

from skyvas_sync.config import Config, STAGING, PRODUCTION, get_config


class TestConfig:
    def test_staging_has_expected_fields(self):
        assert STAGING.cognito_domain == "staging-auth.skyvas.in"
        assert STAGING.client_id == "q4g5opnshgjoq1truddsghupe"
        assert STAGING.region == "ap-south-1"
        assert "staging" in STAGING.api_base_url

    def test_production_has_expected_fields(self):
        assert PRODUCTION.client_id == "49rg8en6nkl5ui4f1molibo8ki"
        assert "amazoncognito" in PRODUCTION.cognito_domain

    def test_authorize_url(self):
        cfg = Config(
            cognito_domain="auth.example.com",
            client_id="cid",
            user_pool_id="pool",
            region="us-east-1",
            api_base_url="http://localhost",
        )
        assert cfg.authorize_url == "https://auth.example.com/oauth2/authorize"

    def test_token_url(self):
        cfg = Config(
            cognito_domain="auth.example.com",
            client_id="cid",
            user_pool_id="pool",
            region="us-east-1",
            api_base_url="http://localhost",
        )
        assert cfg.token_url == "https://auth.example.com/oauth2/token"

    def test_get_config_defaults_to_staging(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = get_config()
            assert cfg is STAGING

    def test_get_config_production(self):
        cfg = get_config("production")
        assert cfg is PRODUCTION

    def test_get_config_env_variable(self):
        with patch.dict(os.environ, {"SKYVAS_ENV": "production"}):
            cfg = get_config()
            assert cfg is PRODUCTION

    def test_get_config_unknown_falls_back_to_staging(self):
        cfg = get_config("unknown")
        assert cfg is STAGING

    def test_config_is_frozen(self):
        import pytest
        with pytest.raises(Exception):
            STAGING.client_id = "x"

    def test_default_redirect_uri(self):
        assert STAGING.redirect_uri == "http://localhost:8585/callback"

    def test_default_scopes(self):
        assert "openid" in STAGING.oauth_scopes
        assert "email" in STAGING.oauth_scopes
