# 0010. Pin upstream crates and the corpus by commit

Status: accepted.

## Decision

- The five upstream crates are git dependencies pinned to the commit of one
  tag of `dekrops/verified-cli` (the same tag the applications pin), locked,
  built with `--locked`.
- The conformance corpus is a git submodule of `dekrops/wvp` at one commit.
- The pinned revision is compiled into the extension, reported by
  `build_info()` and on every result, and tied to the docs by a test.

## Why

Upstream is unpublished. It tags revisions and asks consumers that exchange
packages to pin the same tag by its commit. A submodule cannot be edited in place
without showing up in `git status`, which suits vectors that must never be
changed to make a test pass.

## Cost

Source builds need network access to GitHub. Upgrades are deliberate.

## Ends when

Upstream publishes crates; then a version requirement replaces the revision.
