from dataclasses import dataclass


@dataclass
class User:
    email: str
    opted_in_to_marketing: bool = False
    unsubscribed: bool = False
