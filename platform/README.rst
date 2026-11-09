Deepforge platform
==================

The optional platform provides persistent identities, clocks, scheduling,
state-machine scripts, controller memory and authenticated actor control.
Projects supply worlds, content, action handlers, policies and research tasks.

Install ``platform/runtime`` as a local Python package. Existing integrations
continue to import ``dadcraft_platform``; the console command is
``deepforge-platform``. The runtime requires Python 3.11 or later and has no
third-party production dependencies. It retains its MIT license.

The generic Lua adapter is ``platform/luanti/dadcraft_platform``. Copy it into
the consuming project's mod set and explicitly attach existing entities to
stable IDs. Its advertised basic actions are turn, bounded move and wait.
Projects register additional operations and remain responsible for checking
their permissions and game preconditions. No default actor is spawned.

The optional ``dadcraft_platform_locations`` observer emits bounded presence
events for a supplied location catalogue. The scheduler and script definitions
are reusable without any geographic or game-specific content.

Run the service with ``deepforge-platform --config service.json``. Configure
separate engine/controller tokens, a database, world IDs and a loopback port.
No credentials or live configuration are included. Keep platform state and
engine-side command receipts together when preserving a world. Independent
copies require separate namespaces and service state.

Controller observations, acquire/renew/release/handoff, action receipts,
cancellation and revision-checked memory are implemented in the client module.
A timed movement completion does not certify arrival or pathfinding. A changed
controller invalidates stale grants; unknown execution outcomes stay explicit.
The observation transport budget is 256 loaded actors at a time.

Research use is opt-in. Projects define their hypotheses, controls, evaluations
and provenance. This infrastructure does not constitute evidence of learning
or an autonomous policy, and normal play requires no training.
