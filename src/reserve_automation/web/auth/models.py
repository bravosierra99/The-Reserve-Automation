"""Authenticated user model."""

from pydantic import BaseModel, Field


class AuthenticatedUser(BaseModel):
    """Represents an authenticated user from Cloudflare Access or dev mode."""
    email: str
    role: str = "guest"
    display_name: str = ""

    def model_post_init(self, __context):
        """Derive display name from email if not set."""
        if not self.display_name:
            self.display_name = self.email.split("@")[0].replace(".", " ").title()
