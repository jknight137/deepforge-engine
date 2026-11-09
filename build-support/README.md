# Windows build inputs

The native SDK manifest lists pinned downloads and SHA-256 hashes. The CMake
options use `${CACHE}` for the SDK root and `${NINJA}` for the Ninja executable.
Use one compiler worker to keep local resource use bounded. Compile client and
server with the same configuration; protocol 32001 is incompatible with stock
clients. Source builds use ordinary CMake and retain the bundled dependencies.

The SDK is composed of the compiler and native libraries listed in
sdk-inputs.json. Download and hash-check each archive, then extract it to the
listed destination relative to the cache. No binary SDK is committed here.
runtime-dlls.json lists the runtime files to copy beside the executables.
The corresponding third-party license notices are retained under licenses/.

Configure the source tree with windows-cmake.json after replacing its two
placeholders, build with `cmake --build BUILD --parallel 1`, then install with
`cmake --install BUILD --prefix OUTPUT`. No build command starts a game.

Distributors must provide the matching covered source and build scripts along
with the appropriate dependency source or other valid license-compliance route.

The supplied helper performs these steps and verifies SDK archive/file hashes:

```sh
python tools/build_windows.py --sdk PATH_TO_CACHE --ninja PATH_TO_NINJA
```
