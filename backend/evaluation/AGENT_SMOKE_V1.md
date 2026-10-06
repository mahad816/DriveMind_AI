# First controlled tool-agent smoke (development)

Base: `8eb48e32a821e6781500075d6a9d7e8dc3142346`.

- Dataset SHA-256: `76e507c694d449f346a879852ac8fef11c28cea99139c2470c81f34d77e87336`
- Synthetic HarborDesk corpus identity: `060ad182c0bc7ab14a5966a322d139ece7974e2be1d7515c9eba86cca51c9ca8`
- Graph/tool identity (complete value from freeze): `3f20bbab9e60903a7d02ce36c4ae74af5b270e6449f631249acf86987f6d9677`
- System prompt SHA-256: `b3fea837ec8087e94b877d57d8a093b6a6637386b17dc73727f328b8216f6164`
- Requested model: `gpt-4o-mini`; returned: `gpt-4o-mini-2024-07-18`.

Results: initial tool choice 15/16; exact tool sequence 14/16;
dependent handle reuse 4/4; invented handles 0; filename re-resolution after
producer 0; direct/no-tool 3/3; grounded general knowledge 3/3;
unsafe scope broadening 1; dependent content workflows completed 0/4;
citation-marker coverage 0/3; opaque runtime handle in final prose 1.

Failure families: summary queries returned no evidence despite correct file
selection; unsupported label scope widened to the full inventory; final answers
lacked authoritative citations and one exposed a runtime file handle.

**Tool-agent architecture retained; one implementation revision required.**
No tuning occurred during the first run. Raw live observations remain ignored
and private in `evaluation/results/agent_smoke_v1/`; they are not committed.
This is development evidence, not a generalization holdout.
