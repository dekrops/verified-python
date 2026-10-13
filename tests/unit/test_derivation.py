"""Replaying a recomputed authorization: the API around the shared replayer.

The rules are the replayer's, measured upstream against the first
implementation. These tests cover what the Python layer adds: types, refusals
of bad input, and the things a replay must never be mistaken for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from verified import (
    AuthorizationOutcome,
    DerivationReplay,
    ReplayOutcome,
    TrustRegistry,
    replay_derivation,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "derivation"
TRUST = TrustRegistry.from_json((FIXTURES / "trust.json").read_bytes())


def package(name: str) -> dict[str, Any]:
    case = json.loads((FIXTURES / f"{name}.json").read_text())
    replay_package: dict[str, Any] = case["package"]
    return replay_package


def test_a_package_is_reproduced_from_its_evidence() -> None:
    replay = replay_derivation(package("01-allowed"), TRUST)

    assert replay.outcome is ReplayOutcome.REPRODUCED
    assert replay.draft is True
    assert replay.decision == "SUPPORTED"
    assert replay.commitment is not None
    (authorization,) = replay.authorizations
    assert authorization.correlation == "WF-7"
    assert authorization.outcome is AuthorizationOutcome.ALLOW
    assert authorization.reasons == ()
    assert authorization.engine_decision == "Allow"
    assert (replay.stage, replay.code, replay.detail) == (None, None, ())


def test_a_replay_has_no_truth_value() -> None:
    replay = replay_derivation(package("01-allowed"), TRUST)

    with pytest.raises(TypeError, match="no truth value"):
        bool(replay)


def test_cedars_own_answer_is_kept_apart_from_the_outcome() -> None:
    replay = replay_derivation(package("09-evaluation-error"), TRUST)

    # Reproduced: this verifier arrived at the same undetermined result.
    assert replay.outcome is ReplayOutcome.REPRODUCED
    (authorization,) = replay.authorizations
    # Cedar skipped a policy that failed to evaluate, and allowed.
    assert authorization.engine_decision == "Allow"
    assert authorization.outcome is AuthorizationOutcome.UNDETERMINED
    assert authorization.reasons == ("EVALUATION_ERROR",)
    assert replay.decision == "UNDETERMINED"


def test_a_requirement_is_bound_to_the_derivations_it_depends_on() -> None:
    replay = replay_derivation(package("15-two-requirements-one-derivation"), TRUST)

    assert [b.requirement for b in replay.bindings] == [
        "APPROVAL_AUTHORIZED",
        "DECISION_NAMES_THE_ORDER",
    ]
    first, second = replay.bindings
    assert first.derivations == second.derivations
    assert first.method == "verified-cedar-recomputation"
    assert first.derivations[0].commitment == replay.authorizations[0].commitment
    assert first.derivations[0].record is not None


def test_a_presented_result_the_evidence_does_not_yield_is_not_reproduced() -> None:
    replay = replay_derivation(package("25-outcome-altered"), TRUST)

    assert replay.outcome is ReplayOutcome.NOT_REPRODUCED
    assert (replay.stage, replay.code) == ("DERIVATION", "NOT_REPRODUCED")
    assert 'presented "ALLOW" computed "DENY"' in replay.detail[0]
    assert replay.commitment is None
    assert replay.decision is None
    assert replay.authorizations == ()


def test_the_registry_is_yours_and_never_the_packages() -> None:
    empty = TrustRegistry.from_json(b'{"keys":[]}')

    replay = replay_derivation(package("01-allowed"), empty)

    assert (replay.outcome, replay.stage, replay.code) == (
        ReplayOutcome.NOT_REPRODUCED,
        "EVIDENCE",
        "UNKNOWN_KEY",
    )


def test_what_is_not_a_replay_package_is_not_reproduced_and_bad_input_is_an_error() -> None:
    other = replay_derivation({"package": "something-else"}, TRUST)
    assert (other.stage, other.code) == ("PACKAGE", "UNSUPPORTED_PACKAGE")

    with pytest.raises(TypeError, match="TrustRegistry"):
        replay_derivation(package("01-allowed"), {"keys": []})  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="no fractional numbers"):
        replay_derivation({"package": 1.5}, TRUST)


def test_the_report_is_kept_as_the_replayer_states_it() -> None:
    replay = replay_derivation(package("01-allowed"), TRUST)

    assert isinstance(replay, DerivationReplay)
    assert replay.raw["outcome"] == "reproduced"
    assert replay.raw["authorization"][0]["diagnostics"]["interpretation"] == {
        "outcome": "ALLOW",
        "reasons": [],
    }
