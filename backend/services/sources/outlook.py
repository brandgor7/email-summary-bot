"""MS Graph (Outlook) source provider."""
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import certifi
import httpx

import db
from services.sources.base import EmailMessage, EmailSource, TokenRefreshError
from services.token_store import decrypt, encrypt

logger = logging.getLogger(__name__)

_SSL_VERIFY: bool | str = (
    False if os.getenv("SSL_VERIFY", "true").lower() == "false" else certifi.where()
)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SCOPES = "Mail.Read User.Read offline_access"

_AUTHORITY_MAP = {
    "personal": "https://login.microsoftonline.com/consumers/oauth2/v2.0",
    "work": "https://login.microsoftonline.com/organizations/oauth2/v2.0",
}


def _authority(account_type: str) -> str:
    """Return the MS identity authority URL for the given account type."""
    return _AUTHORITY_MAP.get(account_type, _AUTHORITY_MAP["personal"])


class OutlookSource(EmailSource):
    async def get_auth_url(self, user_id: str, account_type: str = "personal") -> str:
        """Return Microsoft OAuth consent URL."""
        params = {
            "client_id": os.getenv("MS_CLIENT_ID", ""),
            "response_type": "code",
            "redirect_uri": os.getenv("MS_REDIRECT_URI", ""),
            "response_mode": "query",
            "scope": _SCOPES,
            "state": f"{user_id}|{account_type}",
        }
        return f"{_authority(account_type)}/authorize?{urlencode(params)}"

    async def handle_callback(self, user_id: str, code: str) -> None:
        """Exchange auth code for tokens and store them encrypted.

        `user_id` may be a pipe-delimited string `{user_id}|{account_type}`
        when coming from the browser redirect flow.
        """
        if "|" in user_id:
            actual_user_id, account_type = user_id.split("|", 1)
        else:
            actual_user_id, account_type = user_id, "personal"
        client_id = os.getenv("MS_CLIENT_ID", "")
        client_secret = os.getenv("MS_CLIENT_SECRET", "")
        redirect_uri = os.getenv("MS_REDIRECT_URI", "")

        try:
            async with httpx.AsyncClient(verify=_SSL_VERIFY) as client:
                token_resp = await client.post(
                    f"{_authority(account_type)}/token",
                    data={
                        "grant_type": "authorization_code",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "redirect_uri": redirect_uri,
                        "code": code,
                    },
                )
                token_resp.raise_for_status()
                token_data = token_resp.json()

            async with httpx.AsyncClient(verify=_SSL_VERIFY) as client:
                me_resp = await client.get(
                    f"{_GRAPH_BASE}/me",
                    headers={"Authorization": f"Bearer {token_data['access_token']}"},
                    params={"$select": "mail,userPrincipalName"},
                )
                me_resp.raise_for_status()
                me_data = me_resp.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Microsoft auth failed: {exc}") from exc

        provider_email = me_data.get("mail") or me_data.get("userPrincipalName", "")
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
        ).isoformat()

        await db.upsert_source_token(
            token_id=str(uuid.uuid4()),
            user_id=actual_user_id,
            provider="outlook",
            provider_email=provider_email,
            access_token_enc=encrypt(token_data["access_token"]),
            refresh_token_enc=encrypt(token_data["refresh_token"]),
            expires_at=expires_at,
            created_at=datetime.now(timezone.utc).isoformat(),
            account_type=account_type,
        )

    async def fetch_emails(self, user_id: str, since: datetime | None) -> list[EmailMessage]:
        """Fetch inbox emails since the given datetime, auto-refreshing the token if needed."""
        if since is None:
            since = datetime.now(timezone.utc) - timedelta(hours=24)

        access_token = await self._get_valid_access_token(user_id)
        since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            async with httpx.AsyncClient(verify=_SSL_VERIFY) as client:
                resp = await client.get(
                    f"{_GRAPH_BASE}/me/mailFolders/inbox/messages",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "$filter": f"receivedDateTime ge {since_str}",
                        "$select": (
                            "id,subject,from,bodyPreview,"
                            "receivedDateTime,isRead,conversationId,hasAttachments"
                        ),
                        "$top": "100",
                        "$orderby": "receivedDateTime desc",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"MS Graph fetch failed: {exc}") from exc

        return [self._map_message(item) for item in data.get("value", [])]

    async def revoke(self, user_id: str) -> None:
        """Delete stored tokens for this user."""
        await db.delete_source_token(user_id, "outlook")

    async def _get_valid_access_token(self, user_id: str) -> str:
        """Return a valid access token, refreshing it if it is expired or near expiry."""
        row = await db.get_source_token(user_id, "outlook")
        if not row:
            raise RuntimeError(f"No Outlook token found for user {user_id}")

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) >= expires_at - timedelta(minutes=5):
            account_type = row["account_type"] if "account_type" in row.keys() else "personal"
            return await self._refresh_token(user_id, decrypt(row["refresh_token_enc"]), account_type)

        return decrypt(row["access_token_enc"])

    async def _refresh_token(self, user_id: str, refresh_token: str, account_type: str = "personal") -> str:
        """Exchange a refresh token for a new access token and persist the updated tokens."""
        try:
            async with httpx.AsyncClient(verify=_SSL_VERIFY) as client:
                resp = await client.post(
                    f"{_authority(account_type)}/token",
                    data={
                        "grant_type": "refresh_token",
                        "client_id": os.getenv("MS_CLIENT_ID", ""),
                        "client_secret": os.getenv("MS_CLIENT_SECRET", ""),
                        "refresh_token": refresh_token,
                        "scope": _SCOPES,
                    },
                )
                resp.raise_for_status()
                token_data = resp.json()
        except httpx.HTTPError as exc:
            raise TokenRefreshError(f"Token refresh failed: {exc}") from exc

        new_access_token = token_data["access_token"]
        new_refresh_token = token_data.get("refresh_token", refresh_token)
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=token_data["expires_in"])
        ).isoformat()

        row = await db.get_source_token(user_id, "outlook")
        await db.upsert_source_token(
            token_id=row["id"],
            user_id=user_id,
            provider="outlook",
            provider_email=row["provider_email"],
            access_token_enc=encrypt(new_access_token),
            refresh_token_enc=encrypt(new_refresh_token),
            expires_at=expires_at,
            created_at=row["created_at"],
            account_type=account_type,
        )

        logger.info("Refreshed Outlook access token for user %s", user_id)
        return new_access_token

    def _map_message(self, item: dict) -> EmailMessage:
        """Map a single MS Graph message object to an EmailMessage."""
        from_addr = item.get("from", {}).get("emailAddress", {})
        received_raw = item.get("receivedDateTime", "")
        try:
            received_at = datetime.fromisoformat(received_raw.replace("Z", "+00:00"))
        except ValueError:
            received_at = datetime.now(timezone.utc)

        return EmailMessage(
            id=item.get("id", ""),
            subject=item.get("subject") or "(no subject)",
            sender_name=from_addr.get("name", ""),
            sender_email=from_addr.get("address", ""),
            body_preview=item.get("bodyPreview", ""),
            received_at=received_at,
            is_read=item.get("isRead", False),
            conversation_id=item.get("conversationId"),
            has_attachments=item.get("hasAttachments", False),
        )
