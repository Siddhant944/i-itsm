"""Adapters: implementations of the domain's ports for external services.

Gemini, SMTP, Telegram and Google each get an adapter with a deterministic fallback or fake.
Same dependency rule as persistence (D-013).
"""
