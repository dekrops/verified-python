# 0008. No platform client in the first release

Status: accepted.

## Context

The platform does not yet offer a stable, versioned API with service
credentials for submitting claims, evidence or verification requests. What it
accepts is a finished `wvp-0.2` package.

## Decision

Ship no `Client`. Do not write one against an interface that is not there
yet, and do not ship a mock that looks like one.

## Consequence

Everything in this SDK works with no platform, account or network. The
platform integration is a roadmap item that depends on a versioned API and
service credentials existing first.
