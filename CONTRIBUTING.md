# Development policy

## Sources of truth

README is the entrance; CONTEXT contains product background only. This document
owns development rules. AGENTS points agents here without duplicating policy.
Record architectural decisions and rationale in numbered ADRs; keep proposals
marked Proposed until reviewed. Issues own scope, acceptance criteria and
progress. Dated evidence records exact revisions, commands, environments,
results and limitations. Link these records from the PR; do not treat chat or
a progress note as an approved specification.

## Changes and review

Use a separate worktree and feature branch from current `main`. Check the remote
and repository identity before pushing. Keep commits scoped and reviewable.
Create a draft PR targeting `main`, link its Issue and request user review.
No merge is authorized by this bootstrap. Do not change repository security
settings, protections, rulesets or GitHub Apps without a separate decision.
Never infer new approval privileges from these rules.

## Architecture and privacy

Schema/contracts and domain behavior must not depend on provider SDKs, network
clients or storage adapters. Adapters implement ports and may depend inward.
Define and test contract compatibility before changing serialized data.
Keep provider selection and credentials outside domain behavior.

Privacy decisions must fail closed: deny storage, retrieval or transmission
when policy is missing, invalid or undecidable. Apply policy at each boundary;
a prompt is not an enforcement mechanism. Never put credentials or secrets in
prompts, fixtures, logs or commits. Use synthetic test data. Test denial paths,
memory correction/deletion and adapter boundaries when those features exist.

## Reproducible bootstrap

Install Node **24.19.0**, matching `.node-version`; no package installation,
LLM credentials, network calls or GPU are required for validation. Node is only
a documentation-tool runtime, not a product-language choice. The checker uses
only built-in modules; there are no development packages to lock today.

```sh
node --test tools/check-docs.test.mjs
node tools/check-docs.mjs
git diff --check
```

`Bootstrap checks / docs-tooling` runs on every pull request and main push,
without path filters. It checks tracked Markdown local file targets (not anchor
existence or remote URLs), text whitespace/newlines, JSON syntax and the
checker's real regression tests. It does not establish product correctness or
provide a complete secret scanner. Review staged content for confidential data.
CI uses read-only contents permission, pinned official Actions, no secrets,
no `pull_request_target` and no cache. Update pinned tools in reviewed changes.

## Product gates to add with the first implementation

Before accepting product code, agree the language/toolchain in an ADR and add
exact development dependency versions with a committed lockfile and frozen
installation. Add actual commands for lint, format-check, static types, UT,
IT1 and package build/install smoke tests. These gates are **NOT IMPLEMENTED**
today; do not create empty-success jobs, zero-test passes or dummy tests.

UT and IT1 must be deterministic, with no external communication or real LLM.
UT covers units; IT1 covers in-process integration using fakes/local fixtures.
IT2 and ST run only in explicitly authorized real environments. Record provider,
environment, revision, date, sanitized inputs/results and relevant cost/limits
as evidence; do not call them passed on a mocked run. Default setup stays usable
without a real LLM or GPU.

Required test failure, skips or NOT RUN results must never become PASS. Explain
the missing coverage and do not claim readiness until required gates pass.
When runners are added, make zero discovered required tests fail. Keep a stable
required-check name and avoid path/conditional rules that leave it pending.

## Repository settings for the owner to consider

After reviewing the workflow, consider requiring `docs-tooling`, PR review and
blocking direct main pushes. Review bypass permissions and fork behavior before
enabling protections. These settings have not been changed by this work.
