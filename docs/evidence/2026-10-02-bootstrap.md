# Bootstrap validation — 2026-10-02

Scope: documentation and validation tooling only. Progress:
[Issue 1](https://github.com/FYuki/digital-souls-core/issues/1).

Repository identity: `FYuki/digital-souls-core`, stable ID `1401730345`, public.
Initial main: `9806cf4e60d09256b26c5cc00b49a65eee251276` (README only).
The repository had no refs or implementation before initialization.

Official action tags were verified with `git ls-remote` on 2026-10-02:

- `https://github.com/actions/checkout.git`, `refs/tags/v4.2.2`:
  `11bd71901bbe5b1630ceea73d27597364c9af683`.
- `https://github.com/actions/setup-node.git`, `refs/tags/v4.4.0`:
  `49933ea5288caeca8642d1e84afbd3f7d6820020`.

Local environment: Windows PowerShell, Node 24.19.0, Git. Commands and final
revision/results are recorded in the PR after execution. CI executes on
Ubuntu 24.04 with the same pinned Node version; hosted OS images can change.

Product lint, formatting, types, UT, IT1 and packaging: NOT IMPLEMENTED.
Real-environment IT2/ST: NOT RUN. No providers or GPU were used. The documentation
checker's regression tests are tooling tests only, not Core product tests.
Branch protections, rulesets and GitHub Apps were not changed.
