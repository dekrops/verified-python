"""verified: the Python SDK for the Work Verification Protocol (WVP).

What did this agent do, under which authority, with what evidence, according
to which contract, and can an independent party reproduce the result?

Three entry points, each usable without the others:

- :class:`Verifier` verifies a package offline against *your* trust registry.
- :class:`EvidenceSource` signs what an identified system observed.
- :class:`Work` and :class:`WorkSession` carry a claim from an agent's run to
  an issued package.

The protocol is a draft and this SDK is a developer preview.
"""

from verified._bridge import native_available
from verified.canonical import Digest, canonicalize
from verified.contracts import WorkContract
from verified.errors import (
    AssemblyError,
    ContractError,
    LifecycleError,
    MalformedInputError,
    NativeUnavailableError,
    RequirementNotMet,
    ResourceLimitError,
    SigningAuthorityError,
    TrustRegistryError,
    UnsupportedOperationError,
    VerifiedError,
    WorkUnitError,
)
from verified.evidence import (
    Authentication,
    Completeness,
    EvidenceKind,
    EvidenceSource,
    Record,
    SignedEvidence,
    Subject,
)
from verified.history import (
    HistoryReading,
    OfferedRecord,
    Reference,
    RelationRead,
    SameClaim,
    SignedRelation,
    Standing,
    StreamCompleteness,
    StreamRead,
    read_history,
)
from verified.instrumentation import (
    EventKind,
    ExecutionTrace,
    Scope,
    TraceEvent,
    WorkSession,
    content_digest,
)
from verified.records import WorkPackage, WorkRecord
from verified.signing import DECISION_SOURCE, Ed25519Signer, Signer, SigningAuthority
from verified.trust import TrustedKey, TrustRegistry
from verified.verification import (
    Condition,
    Conflict,
    ContractReference,
    Decision,
    Expectations,
    Property,
    PropertyStatus,
    Refusal,
    RequirementValue,
    StatedContent,
    StatedStatement,
    Truth,
    VerificationResult,
    VerificationStatus,
    Verifier,
)
from verified.work import AgentIdentity, Claim, DecisionIssuer, IssuedWork, Work, WorkState
from verified.work_unit import WorkUnit, WorkUnitScope, work_unit

__version__ = "0.1.0"

__all__ = [
    "DECISION_SOURCE",
    "AgentIdentity",
    "AssemblyError",
    "Authentication",
    "Claim",
    "Completeness",
    "Condition",
    "Conflict",
    "ContractError",
    "ContractReference",
    "Decision",
    "DecisionIssuer",
    "Digest",
    "Ed25519Signer",
    "EventKind",
    "EvidenceKind",
    "EvidenceSource",
    "ExecutionTrace",
    "Expectations",
    "HistoryReading",
    "IssuedWork",
    "LifecycleError",
    "MalformedInputError",
    "NativeUnavailableError",
    "OfferedRecord",
    "Property",
    "PropertyStatus",
    "Record",
    "Reference",
    "Refusal",
    "RelationRead",
    "RequirementNotMet",
    "RequirementValue",
    "ResourceLimitError",
    "SameClaim",
    "Scope",
    "SignedEvidence",
    "SignedRelation",
    "Signer",
    "SigningAuthority",
    "SigningAuthorityError",
    "Standing",
    "StatedContent",
    "StatedStatement",
    "StreamCompleteness",
    "StreamRead",
    "Subject",
    "TraceEvent",
    "TrustRegistry",
    "TrustRegistryError",
    "TrustedKey",
    "Truth",
    "UnsupportedOperationError",
    "VerificationResult",
    "VerificationStatus",
    "VerifiedError",
    "Verifier",
    "Work",
    "WorkContract",
    "WorkPackage",
    "WorkRecord",
    "WorkSession",
    "WorkState",
    "WorkUnit",
    "WorkUnitError",
    "WorkUnitScope",
    "__version__",
    "build_info",
    "canonicalize",
    "content_digest",
    "native_available",
    "read_history",
    "work_unit",
]


def build_info() -> dict[str, object]:
    """What this install's verifier is built from: the upstream revision,
    the protocol versions it implements and the encoding it uses."""
    from verified import _bridge  # noqa: PLC0415

    return _bridge.call_json("build_info")
