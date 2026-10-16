"""
Password utilities for authentication.

This module provides helper functions for password validation,
strength checking, and secure generation.
"""

import logging
import re
import secrets
import string
from typing import Any

logger = logging.getLogger(__name__)


def validate_password_strength(password: str) -> dict[str, Any]:
    """Validate password strength against security requirements.

    Returns:
        dict: Validation result with 'valid' boolean and 'errors' list
    """
    errors = []

    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")

    if len(password) > 128:
        errors.append("Password must be no more than 128 characters long")

    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")

    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        errors.append("Password must contain at least one special character")

    # Check for common weak passwords
    weak_passwords = [
        "password",
        "123456",
        "123456789",
        "qwerty",
        "abc123",
        "password123",
        "admin",
        "administrator",
        "root",
        "user",
    ]
    if password.lower() in weak_passwords:
        errors.append("Password is too common and easily guessable")

    # Check for sequential characters
    if has_sequential_chars(password):
        errors.append("Password should not contain sequential characters (abc, 123)")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "strength": calculate_password_strength(password),
    }


def has_sequential_chars(password: str, min_length: int = 3) -> bool:
    """Check if password contains a run of at least ``min_length`` sequential characters."""
    password = password.lower()

    # Check for sequential letters
    for i in range(len(password) - min_length + 1):
        if all(ord(password[i + j + 1]) == ord(password[i + j]) + 1 for j in range(min_length - 1)):
            return True

    # Check for sequential numbers
    for i in range(len(password) - min_length + 1):
        if password[i : i + min_length].isdigit():
            numbers = [int(c) for c in password[i : i + min_length]]
            if all(numbers[j + 1] == numbers[j] + 1 for j in range(min_length - 1)):
                return True

    return False


def calculate_password_strength(password: str) -> str:
    """Calculate password strength level: weak, moderate, strong or very_strong."""
    score = 0

    # Length scoring
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if len(password) >= 16:
        score += 1

    # Character variety scoring
    if re.search(r"[a-z]", password):
        score += 1
    if re.search(r"[A-Z]", password):
        score += 1
    if re.search(r"\d", password):
        score += 1
    if re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        score += 1

    # Bonus for high character variety
    unique_chars = len(set(password))
    if unique_chars > len(password) * 0.8:
        score += 1

    # Penalty for patterns
    if has_sequential_chars(password):
        score -= 1

    if score <= 2:
        return "weak"
    elif score <= 4:
        return "moderate"
    elif score <= 6:
        return "strong"
    else:
        return "very_strong"


def generate_secure_password(length: int = 16) -> str:
    """Generate a cryptographically secure random password (``length`` >= 8)."""
    if length < 8:
        raise ValueError("Password length must be at least 8 characters")

    # Character sets
    lowercase = string.ascii_lowercase
    uppercase = string.ascii_uppercase
    digits = string.digits
    special = '!@#$%^&*(),.?":{}|<>'
    all_chars = lowercase + uppercase + digits + special

    # Regenerate until the candidate also passes validate_password_strength. By
    # construction each candidate already has the four required character classes and
    # the requested length; the only property not guaranteed up front is the absence
    # of sequential runs (abc/123), which validate_password_strength rejects. Looping
    # keeps the invariant "a generated password passes its own validation" and makes
    # the generator deterministic against that check. The bounded attempts keep the
    # function total: a valid-length candidate is still returned in the extremely
    # unlikely case that every attempt contained a sequential run.
    password = ""
    for _attempt in range(1000):
        password_chars = [
            secrets.choice(lowercase),
            secrets.choice(uppercase),
            secrets.choice(digits),
            secrets.choice(special),
        ]
        for _ in range(length - 4):
            password_chars.append(secrets.choice(all_chars))

        # Shuffle so the guaranteed characters are not always in the first positions
        for i in range(len(password_chars)):
            j = secrets.randbelow(len(password_chars))
            password_chars[i], password_chars[j] = password_chars[j], password_chars[i]

        password = "".join(password_chars)
        if not has_sequential_chars(password):
            return password

    return password


def is_password_compromised(password: str) -> bool:
    """Check if password appears in known breach lists.

    Note: This is a placeholder for future implementation.
    In production, this could integrate with services like HaveIBeenPwned API.
    """
    # For now, just check against a small list of very common passwords
    very_common_passwords = {
        "password",
        "123456",
        "123456789",
        "qwerty",
        "abc123",
        "password123",
        "admin",
        "administrator",
        "letmein",
        "welcome",
        "monkey",
        "dragon",
        "master",
        "jesus",
        "ninja",
        "mustang",
        "soccer",
        "batman",
        "hello",
    }

    return password.lower() in very_common_passwords


def sanitize_password_error_message(error_messages: list[str]) -> str:
    """Create a user-friendly error message from password validation errors."""
    if not error_messages:
        return "Password is valid"

    if len(error_messages) == 1:
        return error_messages[0]

    return "Password requirements: " + "; ".join(error_messages)
