# Contributing to Deepforge

Describe the problem and intended behavior. Keep changes focused and preserve
source-file attribution. Include reproduction steps or focused regression tests
and state exactly what was validated. Never use inhabited worlds as fixtures.

Use CMake with BUILD_UNITTESTS=ON for native unit modules and keep benchmarks
disabled unless measuring performance is the stated task. The platform tests
use disposable SQLite state and Lua engine doubles. Do not introduce game
content into the universal engine or assume a particular model provider.

Review source and binary licensing before distributing changes. See
COPYING.LESSER, LICENSE.txt and THIRD_PARTY_NOTICES.md.
