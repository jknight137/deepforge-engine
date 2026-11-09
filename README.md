# Deepforge

Deepforge is a voxel engine and agentic research testbed with larger continuous
worlds, persistent scripting, durable scheduling and external actor control.
It is a standalone project maintained in this repository.

## Capabilities

- Signed 32-bit node and block positions with a supported envelope of +/-65535
  nodes per axis. A node representing one metre gives roughly 131 km across.
- Coordinate-aware SQLite storage and a matching client/server protocol.
- Persistent world-scoped identities, controller memory and scripted state.
- Durable scheduled events, region activation and bounded catch-up.
- An authenticated controller service, Python SDK and Lua actor adapter.
- Existing entity bodies can move between local behavior and external control.

The platform supports experiments involving perception, action, memory and
controller handoff. Projects supply their policies, models, content and task
definitions. No paid model provider, trained policy or scientific result is
bundled. Ordinary world execution does not require a training pipeline.

## Build and run

Standard CMake source builds are supported. See [build instructions](doc/compiling/README.md).
The client executable is `deepforge`; the dedicated server is `deepforgeserver`.
On Windows, use `deepforge.exe` and `deepforgeserver.exe`.

For the pinned Windows SDK recipe, see [build-support](build-support/README.md).
The shared service and controller interfaces are in [platform](platform/README.rst).
Native correctness checks run through `--test-module` before game startup.
Benchmarks are optional and are disabled in the supplied build configuration.

## Compatibility

The wide-world build uses network protocol 32001 and mapblock format 30.
All peers need matching builds. Original format-29 blocks remain readable;
saving in the new format is a forward-only change. Back up existing worlds
before upgrading. Preserve each independent world's namespace and service state.
SQLite is the qualified wide-coordinate backend. Other database backends have
not been qualified for the expanded coordinate range.

The engine preserves existing Lua APIs and configuration identifiers where
needed for compatibility. SDK package and mod names retain the
`dadcraft_platform` identifiers so existing integrations continue to work.
External observations expose up to 256 loaded bodies at a time; this is a
transport budget rather than a total world population limit. Default actor
operations are turn, bounded movement and wait; projects register other lawful
operations. Multiplayer capacity and large population performance are unmeasured.

Public server directories, external content catalogues and automatic update
endpoints are unconfigured by default. A consuming project may set its own.

## Controls

W/A/S/D move, Space jumps, Shift sneaks, left click digs or punches, right click
places or interacts, I opens inventory, T opens chat, and Esc opens the menu.
Projects may override controls and behavior. Keyboard bindings are configurable.

## Licensing and provenance

The engine derives from Luanti revision
`e8f12bf1b93245cfc479ea21787beb1ec472cce9` and remains
**LGPL-2.1-or-later**. Copyright (C) 2010-2026 Perttu Ahola and contributors.
Upstream authorship and Git history are retained. Deepforge modifications
are identified in changed files and version control.

See [COPYING.LESSER](COPYING.LESSER), [LICENSE.txt](LICENSE.txt) and
[third-party notices](THIRD_PARTY_NOTICES.md). Media, fonts and dependencies
retain their individual licenses. The separate Python platform is MIT licensed.
The Deepforge identity artwork is original project artwork under CC0-1.0.

When distributing a modified engine binary, provide the corresponding covered
source and build/install scripts, plus the applicable licenses and notices.
Rebranding does not replace or remove those obligations.
