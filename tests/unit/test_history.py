"""Reading work relations: the API around the shared reader.

The rules themselves are measured by the conformance corpus. These tests
cover what the Python layer adds: types, refusals of bad input, and the
things a reading must never be mistaken for.
"""

from __future__ import annotations

import pytest

from verified import (
    HistoryReading,
    MalformedInputError,
    OfferedRecord,
    ResourceLimitError,
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
