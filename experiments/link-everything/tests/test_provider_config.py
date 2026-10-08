"""AI must never silently fall back to a private provider endpoint."""

import os
import unittest
from unittest.mock import patch

from backend import parametric_ai


class ProviderConfigurationTest(unittest.TestCase):
    def test_provider_address_is_required_even_when_a_key_exists(self):
        with patch.dict(os.environ, {"CONNECTION_DESIGN_ONEAPI_KEY": "test-only-placeholder"}, clear=True):
            with patch("urllib.request.urlopen") as request:
                with self.assertRaisesRegex(parametric_ai.AIUnavailable, "BASE_URL"):
                    parametric_ai._model_response({})
                request.assert_not_called()

    def test_non_https_remote_provider_is_rejected_before_network(self):
        config = {
            "CONNECTION_DESIGN_ONEAPI_KEY": "test-only-placeholder",
            "CONNECTION_DESIGN_ONEAPI_BASE_URL": "http://provider.example/v1",
        }
        with patch.dict(os.environ, config, clear=True), patch("urllib.request.urlopen") as request:
            with self.assertRaisesRegex(parametric_ai.AIUnavailable, "HTTPS"):
                parametric_ai._model_response({})
            request.assert_not_called()
