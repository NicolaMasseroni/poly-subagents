"""
Pytest configuration: stub out langfuse and observability at import time.

Uses create_autospec against the real Langfuse client class so that tests
raise AttributeError for any method that doesn't exist in the installed SDK
(e.g. update_current_observation, propagate_attributes).  Catching these in
tests prevents the "deploy → crash" cycle caused by mismatched API calls.

The span returned by start_as_current_observation uses plain MagicMock because
create_autospec on dunder methods (__enter__/__exit__) requires additional
wiring that adds no safety benefit here.
"""

import sys
import types
from unittest.mock import MagicMock, create_autospec

# Import the real Langfuse class BEFORE stubbing sys.modules so we can build a
# spec-constrained mock.  Importing only the class does not open a connection.
from langfuse._client.client import Langfuse as _RealLangfuse


def _make_span_mock() -> MagicMock:
    """Plain context-manager mock — returned by start_as_current_observation."""
    span = MagicMock()
    span.__enter__ = MagicMock(return_value=span)
    span.__exit__ = MagicMock(return_value=False)
    return span


def _make_langfuse_client_mock() -> MagicMock:
    """
    Spec-constrained mock of the Langfuse client (langfuse 4.x).

    create_autospec enforces that only methods that actually exist on
    langfuse._client.client.Langfuse can be called.  Calling a nonexistent
    method (e.g. propagate_attributes, update_current_observation) raises
    AttributeError in tests — matching pod runtime behaviour.
    """
    span_mock = _make_span_mock()

    client = create_autospec(_RealLangfuse, instance=True)
    client.start_as_current_observation.return_value = span_mock
    client.flush.return_value = None
    client.shutdown.return_value = None
    client.update_current_span.return_value = None
    client.set_current_trace_io.return_value = None
    return client


_langfuse_client = _make_langfuse_client_mock()

# propagate_attributes is a standalone context manager imported from langfuse directly.
_propagate_attrs_mock = MagicMock()
_propagate_attrs_mock.__enter__ = MagicMock(return_value=None)
_propagate_attrs_mock.__exit__ = MagicMock(return_value=False)

# Stub the langfuse package so `from langfuse import get_client, propagate_attributes` resolves.
_langfuse_pkg = types.ModuleType("langfuse")
_langfuse_pkg.get_client = MagicMock(return_value=_langfuse_client)  # type: ignore[attr-defined]
_langfuse_pkg.propagate_attributes = MagicMock(return_value=_propagate_attrs_mock)  # type: ignore[attr-defined]
sys.modules.setdefault("langfuse", _langfuse_pkg)

# Stub the observability module so agents can do `from observability import langfuse, propagate_attributes`.
_obs_mod = types.ModuleType("observability")
_obs_mod.langfuse = _langfuse_client  # type: ignore[attr-defined]
_obs_mod.propagate_attributes = _langfuse_pkg.propagate_attributes  # type: ignore[attr-defined]
sys.modules.setdefault("observability", _obs_mod)
