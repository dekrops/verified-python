"""Exceptions raised by the SDK.

Exceptions are for *operational* failures: something prevented an operation
from being carried out, so nothing was concluded. Expected protocol outcomes
are never exceptions. A refused package, an incomplete verification and a
reproduced ``CONTRADICTED`` decision are all values of
:class:`verified.VerificationResult`.

The one deliberate exception to that rule is :class:`RequirementNotMet`,
raised only by the ``require_*`` methods a caller invokes to turn a result
into an enforcement decision.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from verified.verification import VerificationResult

__all__ = [
    "AssemblyError",
    "ContractError",
    "LifecycleError",
    "MalformedInputError",
    "NativeUnavailableError",
    "RequirementNotMet",
    "ResourceLimitError",
    "SigningAuthorityError",
    "TrustRegistryError",
    "UnsupportedOperationError",
    "VerifiedError",
    "WorkUnitError",
]


class VerifiedError(Exception):
    """Base class of every exception this SDK raises on purpose."""


class NativeUnavailableError(VerifiedError):
    """The native verification extension is not available in this install.

    Verification, canonical encoding, signing input and package assembly are
    implemented by the shared Rust crates and are never approximated in
    Python. Without the extension those operations fail with this error;
    they do not fall back to a weaker check.
    """


class MalformedInputError(VerifiedError):
    """An input is not JSON the protocol's encoding can represent.

    This includes fractional numbers and duplicate object keys, which
    ``verified-json-v1`` does not have.
    """


class ResourceLimitError(VerifiedError):
    """An input exceeds a resource bound of this verifier.

    This is not a protocol refusal: the input was not examined, and a
    verifier with other limits may accept it.
    """


class TrustRegistryError(VerifiedError):
    """A trust registry is missing, malformed or holds unusable key material.

    A configuration error of the relying party, never a statement about a
    package.
    """


class ContractError(VerifiedError):
    """A document is not a well-formed Work Contract Language contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class WorkUnitError(VerifiedError):
    """A work-unit scope or its identifying values are not usable."""


class UnsupportedOperationError(VerifiedError):
    """The protocol version at hand does not define the requested operation.

    For example relying-party expectations and work records exist only for
    ``wvp-0.2``. Ignoring the request would report more than was checked.
    """


class SigningAuthorityError(VerifiedError):
    """A signature was requested outside the signer's declared authority.

    Raised before anything is signed, when an evidence source is asked to
    speak for a system, tenant or purpose its authority does not name.
    """


class LifecycleError(VerifiedError):
    """An operation is not valid in the current state of a work item or session."""


class AssemblyError(VerifiedError):
    """A package could not be issued.

    ``code`` is ``ASSEMBLY_REFUSED`` when the shared verifier would not
    reproduce the package completely under the issuer's registry (the message
    names the protocol refusal), or a contract-language refusal code when the
    contract cannot be evaluated against the claim and evidence.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class RequirementNotMet(VerifiedError):
    """A ``require_*`` check on a verification result failed.

    ``result`` is the full result, so a handler can still tell a refusal from
    an incomplete verification from a reproduced ``CONTRADICTED``.
    """

    def __init__(self, message: str, result: VerificationResult) -> None:
        super().__init__(message)
        self.result = result
