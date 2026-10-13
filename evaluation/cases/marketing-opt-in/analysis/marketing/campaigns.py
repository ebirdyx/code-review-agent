"""Marketing e-mail campaigns."""

from accounts.models import User


def marketing_recipients(users: list[User]) -> list[str]:
    """E-mail addresses that should receive the monthly newsletter."""
    return [u.email for u in users if not u.unsubscribed]
