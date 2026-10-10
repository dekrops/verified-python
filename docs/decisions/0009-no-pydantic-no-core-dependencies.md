# 0009. No Pydantic and no runtime dependencies in the core

Status: accepted.

## Decision

Domain types are frozen dataclasses and enums. The core package declares no
runtime dependencies.

## Why

- Wire validation is done once, exactly, by the Rust side: unknown members,
  canonical spellings, integer ranges. A Pydantic schema would be a second,
  looser definition of the same formats.
- The protocol has no floats and uses text for numbers; general-purpose
  coercion is the opposite of what is wanted.
- An SDK meant to sit inside other people's agents should not pin their
  Pydantic, HTTP or tracing stack.

## Would change if

A platform client is added: an HTTP dependency would then live behind an
extra, in its own module.
