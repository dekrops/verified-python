// SPDX-License-Identifier: Apache-2.0

//! A recomputed authorization, replayed (draft, and not part of the
//! protocol). One call into `verified_derivation::replay`. Nothing on the
//! Python side prepares, decides or compares anything.

use verified_canonical::Value;
use verified_derivation::replay;
use verified_verifier::Trust;

use crate::json::{digest, list, member, object, optional, text, texts};

/// What a replay of `package` under `trust` arrived at: what it computed,
/// or the stage at which the presented result was not reproduced.
pub(crate) fn replayed(package: &Value, trust: &Trust) -> Value {
    match replay(package, trust) {
        Ok(replayed) => object([
            ("outcome", text("reproduced")),
            ("commitment", digest(&replayed.commitment)),
            ("decision", text(&replayed.decision)),
            (
                "authorization",
                list(replayed.derivations.iter().map(|derivation| {
                    object([
                        ("correlation", text(&derivation.correlation)),
                        ("outcome", text(derivation.outcome)),
                        ("reasons", texts(&derivation.reasons)),
                        ("engineDecision", optional(derivation.engine_decision)),
                        ("commitment", digest(&derivation.commitment)),
                        ("diagnostics", derivation.diagnostics.clone()),
                    ])
                })),
            ),
            (
                "bindings",
                member(&replayed.core, "bindings")
                    .cloned()
                    .unwrap_or_else(|| list([])),
            ),
        ]),
        Err(failure) => object([
            ("outcome", text("not-reproduced")),
            ("stage", text(failure.stage)),
            ("code", text(&failure.code)),
            ("detail", list(failure.detail.lines().map(text))),
        ]),
    }
}
