"""Integrations with agent runtimes.

``verified.integrations`` itself depends on nothing but the core SDK. Each
framework adapter lives in its own module, imports its framework only when
that module is imported, and is installed through its own extra.
"""

from verified.integrations.generic import verified_tool

__all__ = ["verified_tool"]
