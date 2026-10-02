# Product context

This repository is intended to explore a small, provider-independent Core.
The following boundary is a starting point for discussion, not an approved API:

- Character definitions and the context needed for an interaction.
- Privacy decisions and policies for storage, retrieval and external transmission.
- Memory extraction, acceptance, correction and deletion.
- An LLM port that allows provider adapters to be replaced.

Speech/STT/TTS, LiveKit, resident agent infrastructure, schedulers, workers and
user interfaces are outside the current Core scope. No business implementation
is introduced by the bootstrap. Contracts, persistence semantics, providers,
implementation language and acceptance scenarios must be agreed before coding.

Development policy belongs in [CONTRIBUTING](CONTRIBUTING.md), not this document.
