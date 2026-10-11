"""Reading work relations: the API around the shared reader.

The rules themselves are measured by the conformance corpus. These tests
cover what the Python layer adds: types, refusals of bad input, and the
things a reading must never be mistaken for.
"""

from __future__ import annotations

import pytest

from verified import (
    Digest,
    Ed25519Signer,
    EvidenceSource,
    HistoryReading,
    MalformedInputError,
    OfferedRecord,
    Reference,
    ResourceLimitError,
    SigningAuthority,
    TrustRegistry,
    read_history,
)
from verified.history import RecordKind

EMPTY = TrustRegistry.from_json(b'{"keys":[]}')


def test_nothing_given_reads_as_nothing_said() -> None:
    reading = read_history([], [], EMPTY)

    assert reading.relations == ()
    assert reading.records == ()
    assert reading.same_claims == ()
    assert reading.streams == ()
    assert reading.records_verified is False


def test_a_reading_has_no_truth_value() -> None:
    reading = read_history([], [], EMPTY)

    with pytest.raises(TypeError, match="no truth value"):
        bool(reading)


def test_a_text_is_held_only_as_a_record_of_a_kind_this_version_defines() -> None:
    reading = read_history(
        [],
        [
            OfferedRecord("invoice", "{}"),
            OfferedRecord(RecordKind.WORK_RECORD, "{}"),
            {"kind": "work-record", "text": "not json"},
        ],
        EMPTY,
    )

    assert reading.records == ("UNKNOWN_KIND", "MALFORMED_RECORD", "MALFORMED_RECORD")


def test_a_relation_nobody_you_trust_signed_is_refused_not_an_error() -> None:
    reading = read_history([{"statement": {}, "body": {}}], [], EMPTY)

    (relation,) = reading.relations
    assert relation.standing.value == "REFUSED"
    assert relation.code == "MALFORMED"
    # Nobody the registry trusts said it, so no authority is named.
    assert relation.source is None
    assert relation.key_id is None


def test_input_that_is_not_relations_and_records_is_an_error_of_the_input() -> None:
    with pytest.raises(MalformedInputError):
        read_history([{"statement": {}}], [], EMPTY)
    with pytest.raises(MalformedInputError):
        read_history([], [{"kind": "work-record"}], EMPTY)
    with pytest.raises(TypeError):
        read_history([], [], {"keys": []})  # type: ignore[arg-type]


def test_a_history_is_bounded() -> None:
    many = [OfferedRecord("work-record", "{}")] * 1025

    with pytest.raises(ResourceLimitError):
        read_history([], many, EMPTY)


def test_the_reading_is_the_shared_readers_own() -> None:
    reading = read_history([], [], EMPTY)

    assert isinstance(reading, HistoryReading)
    assert reading.raw == {"records": [], "relations": [], "sameClaims": [], "streams": []}


# --- issuing a relation -------------------------------------------------------


def _source(system: str = "application") -> tuple[EvidenceSource, TrustRegistry]:
    signer = Ed25519Signer(key_id="test-application", seed=bytes([21]) * 32)
    authority = SigningAuthority(
        key_id=signer.key_id,
        issuer="00000000-0000-4000-8000-000000000901",
        tenant="tenant-test",
        sources=[system],
    )
    source = EvidenceSource(system=system, authority=authority, signer=signer)
    trust = TrustRegistry.from_keys(
        [authority.trusted_key(signer.public_key, valid_from="2026-01-01T00:00:00Z")]
    )
    return source, trust


def _members() -> list[Reference]:
    return [
        Reference.package(Digest.of_bytes(b"package 2")),
        Reference.package(Digest.of_bytes(b"package 1")),
    ]


def test_a_source_says_that_records_belong_to_one_group() -> None:
    source, trust = _source()

    relation = source.group("session-1", _members())
    reading = read_history([relation], [], trust)

    (said,) = reading.relations
    assert said.relation == "groups"
    assert said.source == "application"
    # Authentic and well carried. No record was given, so it is stated.
    assert said.standing.value == "STATED"
    assert {reference.digest for reference in said.absent} == {m.digest for m in _members()}
    # A group is a set: the one encoding orders its members.
    listed = [member["digest"]["hex"] for member in relation.body["groups"]["members"]]
    assert listed == sorted(listed)


def test_only_a_key_the_reader_trusts_for_the_source_is_heard() -> None:
    source, _ = _source()
    _, other = _source("another-application")

    reading = read_history([source.group("session-1", _members())], [], other)

    assert reading.relations[0].standing.value == "REFUSED"
    assert reading.relations[0].code == "SOURCE_NOT_AUTHORIZED"


def test_relations_chained_in_a_stream_show_that_none_is_missing() -> None:
    source, trust = _source()

    first = source.group("session-1", _members(), stream="application/relations")
    second = source.group("session-2", _members(), after=first)

    whole = read_history([first, second], [], trust)
    tail = read_history([second], [], trust)
    assert [(s.completeness, s.last) for s in whole.streams] == [("UNINTERRUPTED", 1)]
    # Without the first statement, what came before is not known.
    assert [s.completeness for s in tail.streams] == ["UNKNOWN"]


def test_a_group_a_reader_would_refuse_is_not_signed() -> None:
    source, _ = _source()
    first = source.group("session-1", _members(), stream="application/relations")

    with pytest.raises(ValueError, match="relation"):
        source.group("session-1", [])
    with pytest.raises(ValueError, match="relation"):
        source.group("", _members())
    with pytest.raises(ValueError, match="relation"):
        source.group("session-1", [*_members(), _members()[0]])
    with pytest.raises(ValueError, match="member"):
        source.group("session-1", [Reference("invoice", Digest.of_bytes(b"x"))])
    with pytest.raises(ValueError, match="not both"):
        source.group("session-2", _members(), stream="another", after=first)
    with pytest.raises(TypeError):
        source.group("session-1", [Digest.of_bytes(b"x")])  # type: ignore[list-item]
