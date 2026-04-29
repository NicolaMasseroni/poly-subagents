"""Singleton Langfuse client per il CEO agent.

Legge credenziali da env: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST.
Importare DOPO load_dotenv() per garantire che le variabili siano già caricate.
"""

from __future__ import annotations

from langfuse import get_client, propagate_attributes

langfuse = get_client()

__all__ = ["langfuse", "propagate_attributes"]
