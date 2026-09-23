"""Token acquisition for the Power Platform API.

IMPORTANT - documented constraint:
    "Power Platform API uses delegated permissions only at this time ...
     For service principal identities, don't use application permissions.
     Instead, after you create your app registration, assign it an RBAC role
     to grant scoped permissions."
    -- Programmability and Extensibility: Authentication (Microsoft Learn)

Practical consequence for CI/CD: a client-credentials token is issued, but the
service principal's EFFECTIVE permissions come from the Power Platform RBAC
role assigned to it - not from API permissions on the app registration. If you
get a token and still receive 401/403 from the evaluation endpoints, the RBAC
role assignment is the thing to check first.

Three supported modes:
  * client_secret  - service principal, for unattended pipelines (needs RBAC role)
  * device_code    - delegated, no browser on the machine (good for first-run setup)
  * interactive    - delegated, opens a local browser
  * azure_cli      - reuse an existing `az login` session

Scope in all cases: https://api.powerplatform.com/.default
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import requests

POWER_PLATFORM_SCOPE = "https://api.powerplatform.com/.default"
POWER_PLATFORM_RESOURCE = "https://api.powerplatform.com"
# Fixed first-party app ID of the Power Platform API across all tenants.
POWER_PLATFORM_API_APP_ID = "8578e004-a5c6-46e7-913e-12f58912df43"


class AuthError(Exception):
    """Raised when a token cannot be acquired."""


class TokenProvider:
    """Acquires and caches a bearer token, refreshing shortly before expiry."""

    def __init__(
        self,
        mode: str,
        tenant_id: str,
        client_id: str | None = None,
        client_secret: str | None = None,
        scope: str = POWER_PLATFORM_SCOPE,
        resource: str = POWER_PLATFORM_RESOURCE,
    ) -> None:
        self.mode = mode
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.resource = resource
        self._token: str | None = None
        self._expires_at: float = 0.0

    # -- public ---------------------------------------------------------

    def token(self) -> str:
        if self._token and time.time() < self._expires_at - 120:
            return self._token
        acquire = {
            "client_secret": self._client_secret,
            "device_code": self._device_code,
            "interactive": self._interactive,
            "azure_cli": self._azure_cli,
        }.get(self.mode)
        if acquire is None:
            raise AuthError(
                f"Unknown auth mode '{self.mode}'. Use one of: "
                "client_secret, device_code, interactive, azure_cli."
            )
        token, expires_in = acquire()
        self._token = token
        self._expires_at = time.time() + float(expires_in or 3600)
        return token

    def header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    # -- modes ----------------------------------------------------------

    def _client_secret(self) -> tuple[str, int]:
        if not (self.client_id and self.client_secret):
            raise AuthError("client_secret mode requires CLIENT_ID and CLIENT_SECRET.")
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        response = requests.post(
            url,
            data={
                "client_id": self.client_id,
                "scope": self.scope,
                "client_secret": self.client_secret,
                "grant_type": "client_credentials",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=60,
        )
        if response.status_code != 200:
            raise AuthError(
                f"Token request failed ({response.status_code}). "
                f"Response: {response.text[:500]}"
            )
        payload = response.json()
        return payload["access_token"], payload.get("expires_in", 3599)

    def _msal_app(self):
        try:
            import msal  # imported lazily so the SP path needs no extra dependency
        except ImportError as exc:  # pragma: no cover
            raise AuthError(
                "Delegated auth requires the 'msal' package. Run: pip install msal"
            ) from exc
        if not self.client_id:
            raise AuthError("Delegated auth requires CLIENT_ID.")
        return msal.PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
        )

    def _device_code(self) -> tuple[str, int]:
        app = self._msal_app()
        flow = app.initiate_device_flow(scopes=[self.scope])
        if "user_code" not in flow:
            raise AuthError(f"Could not start device code flow: {json.dumps(flow)[:400]}")
        print(flow["message"], flush=True)
        result = app.acquire_token_by_device_flow(flow)
        return self._from_msal(result)

    def _interactive(self) -> tuple[str, int]:
        app = self._msal_app()
        result = app.acquire_token_interactive(scopes=[self.scope])
        return self._from_msal(result)

    def _azure_cli(self) -> tuple[str, int]:
        if not shutil.which("az"):
            raise AuthError("azure_cli mode requires the Azure CLI on PATH.")
        try:
            raw = subprocess.check_output(
                [
                    "az", "account", "get-access-token",
                    "--resource", self.resource,
                    "--output", "json",
                ],
                stderr=subprocess.PIPE,
                timeout=120,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or b"").decode("utf-8", "replace")[:400]
            raise AuthError(f"az account get-access-token failed. {detail}") from exc
        payload = json.loads(raw)
        return payload["accessToken"], 3300

    @staticmethod
    def _from_msal(result: dict) -> tuple[str, int]:
        if "access_token" not in result:
            raise AuthError(
                f"{result.get('error', 'unknown_error')}: "
                f"{result.get('error_description', '')}"[:500]
            )
        return result["access_token"], result.get("expires_in", 3599)


def provider_from_env(prefix: str = "") -> TokenProvider:
    """Build a TokenProvider from environment variables.

    Recognised variables (optionally prefixed, e.g. DATAVERSE_):
        AUTH_MODE, TENANT_ID, CLIENT_ID, CLIENT_SECRET
    """
    def get(name: str, default: str | None = None) -> str | None:
        return os.environ.get(f"{prefix}{name}", os.environ.get(name, default))

    tenant_id = get("TENANT_ID")
    if not tenant_id:
        raise AuthError(f"{prefix}TENANT_ID is not set.")

    secret = get("CLIENT_SECRET")
    default_mode = "client_secret" if secret else "device_code"
    return TokenProvider(
        mode=(get("AUTH_MODE") or default_mode).strip(),
        tenant_id=tenant_id,
        client_id=get("CLIENT_ID"),
        client_secret=secret,
    )
