# Developer documentation

Deepforge development is maintained in this repository. Its current scope is
persistent voxel worlds and a general agentic research testbed. Project content,
models and experiment protocols are supplied by consuming projects.

- [Contribution guide](../../.github/CONTRIBUTING.md)
- [Build instructions](../compiling/README.md)
- [Windows SDK recipe](../../build-support/README.md)
- [Lua API](../lua_api.md)
- [Database constraints](../databases.md)
- [Controller runtime](../../platform/README.rst)
- [Licensing and provenance](../../THIRD_PARTY_NOTICES.md)

Windows builds and bounded native correctness checks are the qualified release
path. Other inherited build recipes require platform-specific qualification.
Visible clients and input capture require an agreed local testing window.
Use disposable state for automated checks and preserve inhabited worlds.
