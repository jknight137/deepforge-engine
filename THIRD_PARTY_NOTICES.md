# Third-party notices

## Engine origin

Deepforge contains modified Luanti source, originally developed by Perttu Ahola
and contributors. The source-file copyright notices and complete Git ancestry
remain intact. The inherited code and engine modifications are
LGPL-2.1-or-later; the full terms are in COPYING.LESSER. Modified files carry
dated Deepforge notices. Original project material is retained for legal
attribution, technical compatibility and source provenance.

## Bundled components and media

LICENSE.txt retains the original source, media, Irrlicht, JThread, Lua and font
notices. Individual licenses in irr, lib and fonts also apply. Distributed
native SDK libraries include their notices in licenses/. The SDK dependency
and runtime-DLL manifests are in build-support/.

Existing media is generally CC BY-SA 3.0, with separately identified CC BY-SA
4.0, CC BY 4.0 and Apache 2.0 exceptions. Its creator attribution, license
references and applicable change notices must accompany redistribution.
Original Deepforge branding assets replace the application logo and icons;
their CC0-1.0 notice is in textures/base/pack/DEEPFORGE-ARTWORK.txt.

## Separate platform

The Python runtime and its generic Lua adapters are separate project modules.
The runtime's MIT license and original copyright notice are in
platform/runtime/LICENSE. SDK import names remain compatible with existing
consuming projects. Engine licensing is not replaced by the platform license.

## Distribution

Distributions must retain the applicable license and copyright notices. Provide
the complete corresponding covered source and the scripts needed to build and
install a distributed modified engine. Keep build and dependency records with
each binary version. Recipients retain the LGPL rights over covered code.
Independent content has its own license; assess copied or linked components
under their actual licenses instead of assigning a blanket license to a game.
