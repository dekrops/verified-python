"""The single doorway to the native extension.

Nothing else in the package imports ``verified._native``. The extension is
loaded on first use, never at import time, and its absence is reported as an
explicit capability error.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from functools import cache
from types import ModuleType
from typing import Any, NoReturn, TypeAlias

from verified.errors import (
    AssemblyError,
    ContractError,
    MalformedInputError,
    NativeUnavailableError,
    ResourceLimitError,
    TrustRegistryError,
    UnsupportedOperationError,
    VerifiedError,
    WorkUnitError,
)

Json: TypeAlias = "bool | int | str | list[Json] | dict[str, Json] | None"

_CONTRACT_CODES = frozenset(
    {
        "CONTRACT_MALFORMED",
        "CONTRACT_ILL_FORMED",
        "ENVIRONMENT_MALFORMED",
        "ENVIRONMENT_NONCONFORMING",
        "WORK_LIMIT",
    }
)


@cache
def _load() -> ModuleType:
    try:
        # Loaded on first use, never at import time.
        native = importlib.import_module("verified._native")
    except ImportError as error:
        raise NativeUnavailableError(
            "the native verification extension (verified._native) is not available in this "
            "installation, so this operation cannot be performed. Nothing was verified. "
            "Install a wheel built for this platform, or build from source with a Rust toolchain."
        ) from error
    return native


def native_available() -> bool:
    """Whether the native extension can be loaded."""
    try:
        _load()
    except NativeUnavailableError:
        return False
    return True


def _raise(code: str, message: str) -> NoReturn:
    if code == "RESOURCE_LIMIT":
        raise ResourceLimitError(message)
    if code == "TRUST_REGISTRY":
        raise TrustRegistryError(message)
    if code in {"MALFORMED_JSON", "MALFORMED_PACKAGE", "WORK_RECORD", "ASSEMBLY_INPUT"}:
        raise MalformedInputError(message)
    if code in {"EXPECTATIONS_UNDEFINED", "RECORD_UNDEFINED"}:
        raise UnsupportedOperationError(message)
    if code == "WORK_UNIT":
        raise WorkUnitError(message)
    if code == "ASSEMBLY_REFUSED":
        raise AssemblyError(code, message)
    if code in _CONTRACT_CODES:
        raise ContractError(code, message)
    if code == "USAGE":
        raise ValueError(message)
    raise VerifiedError(f"{code}: {message}")


def call(name: str, /, *args: Any, **kwargs: Any) -> Any:
    """Calls a native function, translating its errors."""
    native = _load()
    try:
        return getattr(native, name)(*args, **kwargs)
    except native.NativeError as error:
        code, message = error.args
        _raise(code, message)


def call_json(name: str, /, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Calls a native function that returns a JSON object as text."""
    result: dict[str, Any] = json.loads(call(name, *args, **kwargs))
    return result


def plain(value: object, *, where: str = "value") -> Json:
    """A plain JSON value, or ``TypeError`` for anything the protocol's
    encoding cannot hold. Floats are refused, never rounded."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise TypeError(
            f"{where}: the protocol's encoding has no fractional numbers; "
            "write amounts as text in the contract's scale"
        )
    if isinstance(value, Mapping):
        result: dict[str, Json] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{where}: object keys are text")
            result[key] = plain(item, where=f"{where}.{key}")
        return result
    if isinstance(value, list | tuple):
        return [plain(item, where=f"{where}[{i}]") for i, item in enumerate(value)]
    raise TypeError(f"{where}: {type(value).__name__} is not a JSON value")


def dumps(value: object, *, where: str = "value") -> bytes:
    """JSON text for the native side. Not canonical: the native side encodes."""
    return json.dumps(plain(value, where=where), ensure_ascii=False, allow_nan=False).encode()
