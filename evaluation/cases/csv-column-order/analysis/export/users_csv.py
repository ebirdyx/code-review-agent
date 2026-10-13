"""CSV export of user accounts."""

import csv


def export_users(users: list[dict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "id", "email"])
        writer.writeheader()
        writer.writerows(users)
