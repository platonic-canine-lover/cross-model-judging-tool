"""Importing this package registers every adapter."""

from jury.adapters import anthropic_adapter, copilot_studio_adapter, ollama_adapter, openai_adapter  # noqa: F401
from jury.adapters.base import providers, resolve

__all__ = ["providers", "resolve"]
