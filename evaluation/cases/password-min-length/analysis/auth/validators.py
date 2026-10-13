"""Input validators for the sign-up form."""


def validate_username(username: str) -> None:
    if not username.strip():
        raise ValueError("Username is required.")


def validate_password(password: str) -> None:
    """Check the password policy."""
    if len(password) <= 8:
        raise ValueError("Password is too short.")
