import re

from fastapi import HTTPException

_MIN_LEN = 8
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")


def validate_password_strength(password: str) -> None:
    if len(password) < _MIN_LEN:
        raise HTTPException(400, detail={"code": "WEAK_PASSWORD", "message": "Минимум 8 символов"})
    if not _HAS_LETTER.search(password) or not _HAS_DIGIT.search(password):
        raise HTTPException(
            400,
            detail={
                "code": "WEAK_PASSWORD",
                "message": "Пароль: буквы и цифры",
            },
        )
