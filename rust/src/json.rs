// SPDX-License-Identifier: Apache-2.0

//! Building the JSON this extension returns, and reading the JSON it is given.
//!
//! Everything crosses the Python boundary as JSON text. The values are the
//! protocol's own (`verified_canonical::Value`), so no second JSON model, and
//! no float, ever sits between Python and the verifier.

use pyo3::PyErr;
use verified_canonical::{Integer, Limits, Object, ParseError, Sha256Digest, Value, parse};

use crate::fail;

pub(crate) fn text(value: &str) -> Value {
    Value::String(value.to_owned())
}

pub(crate) fn count(value: usize) -> Value {
    Value::Integer(Integer::from(i64::try_from(value).unwrap_or(i64::MAX)))
}

pub(crate) fn number(value: i64) -> Value {
    Value::Integer(Integer::from(value))
}

pub(crate) fn object<const N: usize>(members: [(&str, Value); N]) -> Value {
    let mut object = Object::new();
    for (name, value) in members {
        object.insert(name, value);
    }
    Value::Object(object)
}

pub(crate) fn list(items: impl IntoIterator<Item = Value>) -> Value {
    Value::Array(items.into_iter().collect())
}

pub(crate) fn texts<S: AsRef<str>>(items: &[S]) -> Value {
    list(items.iter().map(|item| text(item.as_ref())))
}

pub(crate) fn optional(value: Option<&str>) -> Value {
    value.map_or(Value::Null, text)
}

/// `{ "value": … }`, the wire form of identifiers and times.
pub(crate) fn wrapped(value: &str) -> Value {
    object([("value", text(value))])
}

/// `{ "algorithm": "sha-256", "hex": … }`, the wire form of a digest.
pub(crate) fn digest(value: &Sha256Digest) -> Value {
    object([
        ("algorithm", text(Sha256Digest::ALGORITHM)),
        ("hex", text(&value.to_hex())),
    ])
}

/// Reads JSON given by the caller. `code` names what could not be read; a
/// resource limit is always reported as one.
pub(crate) fn read(input: &[u8], what: &str, code: &str) -> Result<Value, PyErr> {
    parse(input, &Limits::DEFAULT).map_err(|error| match error {
        ParseError::Limit(limit) => fail("RESOURCE_LIMIT", format!("{what}: {limit}")),
        other => fail(code, format!("{what}: {other}")),
    })
}

pub(crate) fn member<'a>(value: &'a Value, name: &str) -> Option<&'a Value> {
    value.as_object().and_then(|object| object.get(name))
}

pub(crate) fn member_text<'a>(value: &'a Value, path: &[&str]) -> Option<&'a str> {
    path.iter()
        .try_fold(value, |value, name| member(value, name))
        .and_then(Value::as_str)
}
