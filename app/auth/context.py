from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ActorContext:
    user_id: str | None = None
    guest_id: str | None = None
    email: str | None = None
    role: str = "user"
    balance_usd: Decimal = Decimal("0")
    is_master: bool = False
    is_guest: bool = False
    email_verified: bool = False

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None

    @property
    def bypass_limits(self) -> bool:
        return self.is_master

    @property
    def owner_key(self) -> tuple[str, str]:
        if self.user_id:
            return ("user", self.user_id)
        if self.guest_id:
            return ("guest", self.guest_id)
        return ("anonymous", "")
