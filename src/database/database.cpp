// Modified for Deepforge on 2026-11-09; original notices retained.
// Luanti
// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2013 celeron55, Perttu Ahola <celeron55@gmail.com>

#include "database.h"
#include "exceptions.h"
#include "irrlichttypes.h"


/****************
 * The position encoding is a bit messed up because negative
 * values were not taken into account.
 * But this also maps 0,0,0 to 0, which is nice, and we mostly
 * need forward encoding in Luanti.
 */
s64 MapDatabase::getBlockAsInteger(const v3s32 &pos)
{
	if (pos.X < -2048 || pos.X > 2047 || pos.Y < -2048 || pos.Y > 2047 || pos.Z < -2048 || pos.Z > 2047)
        throw FileNotGoodException("Wide mapblocks require a split-coordinate backend; legacy packed keys are restricted to their original range");
    return (s64)pos.Z * 16777216LL + (s64)pos.Y * 4096LL + pos.X;
}


v3s32 MapDatabase::getIntegerAsBlock(s64 i)
{
	// Offset so that all negative coordinates become non-negative
	i = i + 0x800800800;
	// Which is now easier to decode using simple bit masks:
	return { (s16)( (i        & 0xFFF) - 0x800),
	         (s16)(((i >> 12) & 0xFFF) - 0x800),
	         (s16)(((i >> 24) & 0xFFF) - 0x800) };
}
