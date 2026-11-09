// Modified for Deepforge on 2026-11-09; original notices retained.
// Luanti
// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2010-2013 celeron55, Perttu Ahola <celeron55@gmail.com>

#include "directiontables.h"

const v3s32 g_6dirs[6] =
{
	// +right, +top, +back
	v3s32( 0, 0, 1), // back
	v3s32( 0, 1, 0), // top
	v3s32( 1, 0, 0), // right
	v3s32( 0, 0,-1), // front
	v3s32( 0,-1, 0), // bottom
	v3s32(-1, 0, 0) // left
};

const v3s32 g_7dirs[7] =
{
	v3s32(0,0,1), // back
	v3s32(0,1,0), // top
	v3s32(1,0,0), // right
	v3s32(0,0,-1), // front
	v3s32(0,-1,0), // bottom
	v3s32(-1,0,0), // left
	v3s32(0,0,0), // self
};

const v3s32 g_26dirs[26] =
{
	// +right, +top, +back
	v3s32( 0, 0, 1), // back
	v3s32( 0, 1, 0), // top
	v3s32( 1, 0, 0), // right
	v3s32( 0, 0,-1), // front
	v3s32( 0,-1, 0), // bottom
	v3s32(-1, 0, 0), // left
	// 6
	v3s32(-1, 1, 0), // top left
	v3s32( 1, 1, 0), // top right
	v3s32( 0, 1, 1), // top back
	v3s32( 0, 1,-1), // top front
	v3s32(-1, 0, 1), // back left
	v3s32( 1, 0, 1), // back right
	v3s32(-1, 0,-1), // front left
	v3s32( 1, 0,-1), // front right
	v3s32(-1,-1, 0), // bottom left
	v3s32( 1,-1, 0), // bottom right
	v3s32( 0,-1, 1), // bottom back
	v3s32( 0,-1,-1), // bottom front
	// 18
	v3s32(-1, 1, 1), // top back-left
	v3s32( 1, 1, 1), // top back-right
	v3s32(-1, 1,-1), // top front-left
	v3s32( 1, 1,-1), // top front-right
	v3s32(-1,-1, 1), // bottom back-left
	v3s32( 1,-1, 1), // bottom back-right
	v3s32(-1,-1,-1), // bottom front-left
	v3s32( 1,-1,-1), // bottom front-right
	// 26
};

const v3s32 g_27dirs[27] =
{
	// +right, +top, +back
	v3s32( 0, 0, 1), // back
	v3s32( 0, 1, 0), // top
	v3s32( 1, 0, 0), // right
	v3s32( 0, 0,-1), // front
	v3s32( 0,-1, 0), // bottom
	v3s32(-1, 0, 0), // left
	// 6
	v3s32(-1, 1, 0), // top left
	v3s32( 1, 1, 0), // top right
	v3s32( 0, 1, 1), // top back
	v3s32( 0, 1,-1), // top front
	v3s32(-1, 0, 1), // back left
	v3s32( 1, 0, 1), // back right
	v3s32(-1, 0,-1), // front left
	v3s32( 1, 0,-1), // front right
	v3s32(-1,-1, 0), // bottom left
	v3s32( 1,-1, 0), // bottom right
	v3s32( 0,-1, 1), // bottom back
	v3s32( 0,-1,-1), // bottom front
	// 18
	v3s32(-1, 1, 1), // top back-left
	v3s32( 1, 1, 1), // top back-right
	v3s32(-1, 1,-1), // top front-left
	v3s32( 1, 1,-1), // top front-right
	v3s32(-1,-1, 1), // bottom back-left
	v3s32( 1,-1, 1), // bottom back-right
	v3s32(-1,-1,-1), // bottom front-left
	v3s32( 1,-1,-1), // bottom front-right
	// 26
	v3s32(0,0,0),
};

const u8 wallmounted_to_facedir[8] = {
	20,
	0,
	16 + 1,
	12 + 3,
	8,
	4 + 2,
	20 + 1, // special 1
	0 + 1 // special 2
};

const v3s32 wallmounted_dirs[8] = {
	v3s32(0, 1, 0),
	v3s32(0, -1, 0),
	v3s32(1, 0, 0),
	v3s32(-1, 0, 0),
	v3s32(0, 0, 1),
	v3s32(0, 0, -1),
};

const v3s32 facedir_dirs[32] = {
	//0
	v3s32(0, 0, 1),
	v3s32(1, 0, 0),
	v3s32(0, 0, -1),
	v3s32(-1, 0, 0),
	//4
	v3s32(0, -1, 0),
	v3s32(1, 0, 0),
	v3s32(0, 1, 0),
	v3s32(-1, 0, 0),
	//8
	v3s32(0, 1, 0),
	v3s32(1, 0, 0),
	v3s32(0, -1, 0),
	v3s32(-1, 0, 0),
	//12
	v3s32(0, 0, 1),
	v3s32(0, -1, 0),
	v3s32(0, 0, -1),
	v3s32(0, 1, 0),
	//16
	v3s32(0, 0, 1),
	v3s32(0, 1, 0),
	v3s32(0, 0, -1),
	v3s32(0, -1, 0),
	//20
	v3s32(0, 0, 1),
	v3s32(-1, 0, 0),
	v3s32(0, 0, -1),
	v3s32(1, 0, 0),
};

const v3s32 fourdir_dirs[4] = {
	v3s32(0, 0, 1),
	v3s32(1, 0, 0),
	v3s32(0, 0, -1),
	v3s32(-1, 0, 0),
};
