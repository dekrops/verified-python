"""Framework-independent instrumentation for agent tools."""

from __future__ import annotations

import functools
import inspect
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ParamSpec, TypeVar, cast

from verified.contracts import WorkContract
from verified.errors import LifecycleError
from verified.instrumentation import WorkSession

__all__ = ["verified_tool"]

P = ParamSpec("P")
R = TypeVar("R")


def verified_tool(
    *,
    work_type: str,
    contract: WorkContract | str | os.PathLike[str] | None = None,
    inputs: Callable[..., Mapping[str, str | bool | int]] | None = None,
    require_session: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Instruments a tool an agent calls, for synchronous and ``async``
    functions alike.

    Inside a :class:`verified.WorkSession` each call:

    1. records that the tool was called and whether it returned or raised,
       correlated with the session and turn;
    2. if ``contract`` and ``inputs`` are given, opens a
       :class:`verified.Work` for the call (``inputs`` receives the call's
       arguments and returns the contract's inputs) and leaves it ``OPEN``.

    That is all. **Returning without an exception is not recorded as
    success**, and no evidence is created: the tool is the agent's own hands,
    and the agent saying an invoice was posted is not the ERP saying so. The
    opened work waits for evidence from an identified source; find it in
    :attr:`verified.WorkSession.works`.

    Outside a session the function runs unchanged, unless
    ``require_session=True``, in which case calling it is an error.

    ``contract`` may be a path; it is read on the first call, never at
    import time.
    """
    if (contract is None) != (inputs is None):
        raise ValueError("give contract and inputs together, or neither")
    loaded: list[WorkContract] = []

    def resolve() -> WorkContract:
        if not loaded:
            assert contract is not None  # noqa: S101 - narrowed by the check above
            loaded.append(
                contract if isinstance(contract, WorkContract) else WorkContract.load(contract)
            )
        return loaded[0]

    def session_for_call() -> WorkSession | None:
        session = WorkSession.current()
        if session is None and require_session:
            raise LifecycleError(
                f"tool {work_type!r} was called outside a WorkSession, and it requires one"
            )
        return session

    def open_work(
        session: WorkSession, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> dict[str, Any]:
        if inputs is None:
            return {}
        work = session.begin_work(
            contract=resolve(), inputs=inputs(*args, **kwargs), label=work_type
        )
        return {"claim": work.claim_id}

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(function):
            coroutine = cast("Callable[P, Awaitable[Any]]", function)

            @functools.wraps(function)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
                session = session_for_call()
                if session is None:
                    return await coroutine(*args, **kwargs)
                attributes = open_work(session, args, kwargs)
                async with session.tool(work_type, **attributes):
                    return await coroutine(*args, **kwargs)

            return cast("Callable[P, R]", async_wrapper)

        @functools.wraps(function)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            session = session_for_call()
            if session is None:
                return function(*args, **kwargs)
            attributes = open_work(session, args, kwargs)
            with session.tool(work_type, **attributes):
                return function(*args, **kwargs)

        return wrapper

    return decorate
