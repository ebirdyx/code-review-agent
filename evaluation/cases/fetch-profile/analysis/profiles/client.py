"""Client for the profile service."""

import json
import urllib.request

PROFILE_URL = "https://profiles.internal.example/api/users/{user_id}"


def fetch_profile(user_id: int) -> dict:
    """Return the profile of a user from the profile service."""
    with urllib.request.urlopen(PROFILE_URL.format(user_id=user_id)) as response:
        return json.load(response)
