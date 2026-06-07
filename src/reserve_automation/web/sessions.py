"""Session management using encrypted cookies."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class SessionManager:
    """Manages user sessions via encrypted cookies."""

    def __init__(self, secret_key: str, max_age_hours: int = 24):
        """
        Initialize session manager.

        Args:
            secret_key: Secret key for encryption (should be 32+ char random string)
            max_age_hours: Maximum session age in hours
        """
        self.serializer = URLSafeTimedSerializer(secret_key)
        self.max_age_seconds = max_age_hours * 3600

    def create_session(self, data: dict[str, Any]) -> str:
        """
        Create a new session and return the signed token.

        Args:
            data: Session data to store

        Returns:
            Signed session token (safe for cookies)
        """
        # Add session metadata
        session_data = {
            "session_id": str(uuid.uuid4()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            **data
        }

        # Serialize and sign
        return self.serializer.dumps(session_data)

    def read_session(self, token: str) -> Optional[dict[str, Any]]:
        """
        Read and validate session from token.

        Args:
            token: Signed session token

        Returns:
            Session data if valid, None if invalid/expired
        """
        try:
            # Load and verify signature + age
            data = self.serializer.loads(
                token,
                max_age=self.max_age_seconds
            )
            return data
        except (BadSignature, SignatureExpired):
            return None

    def update_session(self, token: str, updates: dict[str, Any]) -> Optional[str]:
        """
        Update existing session with new data.

        Args:
            token: Current session token
            updates: Data to merge into session

        Returns:
            New session token if successful, None if session invalid
        """
        # Read current session
        session_data = self.read_session(token)
        if session_data is None:
            return None

        # Merge updates
        session_data.update(updates)

        # Create new token with updated data
        return self.serializer.dumps(session_data)

    def clear_session(self) -> None:
        """
        Clear session (returns None for use with response.delete_cookie).

        Note: This is a no-op since sessions are stateless.
        The actual clearing happens by deleting the cookie.
        """
        pass


def get_session_data(session_token: Optional[str], secret_key: str) -> Optional[dict[str, Any]]:
    """
    Helper function to extract session data from token.

    Args:
        session_token: Session token from cookie
        secret_key: Secret key for decryption

    Returns:
        Session data if valid, None otherwise
    """
    if not session_token:
        return None

    manager = SessionManager(secret_key)
    return manager.read_session(session_token)
