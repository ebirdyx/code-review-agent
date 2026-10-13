"""Serving files uploaded by users."""

import os

UPLOAD_DIR = "/srv/app/uploads"


def read_upload(filename: str) -> bytes:
    """Return the content of an uploaded file."""
    path = os.path.join(UPLOAD_DIR, filename)
    with open(path, "rb") as f:
        return f.read()
