// SPDX-License-Identifier: Apache-2.0

//! Work relation v1 (draft): reading what authorities say about records.
//! One call into `verified_history::read`. No record is verified here, and
//! nothing on the Python side decides anything about a relation.

use pyo3::PyResult;
use verified_canonical::Value;
use verified_history::{Carried, Offered, read};
use verified_verifier::Trust;

use crate::fail;
use crate::json::member;

/// The most relations, and the most records, one history may hold: the
/// reader compares each relation with each record.
const MAX_ITEMS: usize = 1024;

fn items<'a>(value: &'a Value, what: &str) -> PyResult<&'a [Value]> {
    let items = value
        .as_array()
        .ok_or_else(|| fail("MALFORMED_JSON", format!("{what} is a list")))?;
    if items.len() > MAX_ITEMS {
        return Err(fail(
            "RESOURCE_LIMIT",
            format!("{} {what}; at most {MAX_ITEMS} are read", items.len()),
        ));
    }
    Ok(items)
}

/// The reading of `relations` (each `{ statement, body }`) against `records`
/// (each `{ kind, text }`) under `trust`, in the form the conformance
/// vectors state.
pub(crate) fn reading(relations: &Value, records: &Value, trust: &Trust) -> PyResult<Value> {
    let carried = items(relations, "relations")?
        .iter()
        .map(|item| {
            Some(Carried {
                statement: member(item, "statement")?,
                body: member(item, "body")?,
            })
        })
        .collect::<Option<Vec<_>>>()
        .ok_or_else(|| fail("MALFORMED_JSON", "a relation is { statement, body }"))?;
    let offered = items(records, "records")?
        .iter()
        .map(|item| {
            Some(Offered {
                kind: member(item, "kind")?.as_str()?,
                text: member(item, "text")?.as_str()?,
            })
        })
        .collect::<Option<Vec<_>>>()
        .ok_or_else(|| fail("MALFORMED_JSON", "a record is { kind, text }"))?;
    Ok(read(&carried, &offered, trust).to_value())
}
