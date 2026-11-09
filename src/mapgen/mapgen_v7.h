// Modified for Deepforge on 2026-11-09; original notices retained.
// Luanti
// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2014-2020 paramat
// Copyright (C) 2013-2016 kwolekr, Ryan Kwolek <kwolekr@minetest.net>

#pragma once

#include "mapgen.h"

///////////// Mapgen V7 flags
#define MGV7_MOUNTAINS   0x01
#define MGV7_RIDGES      0x02
#define MGV7_FLOATLANDS  0x04
#define MGV7_CAVERNS     0x08
#define MGV7_BIOMEREPEAT 0x10 // Now unused


extern const FlagDesc flagdesc_mapgen_v7[];


struct MapgenV7Params : public MapgenParams {
	s32 mount_zero_level = 0;
	s32 floatland_ymin = 1024;
	s32 floatland_ymax = 4096;
	s32 floatland_taper = 256;
	float float_taper_exp = 2.0f;
	float floatland_density = -0.6f;
	s32 floatland_ywater = -31000;

	float cave_width = 0.09f;
	s32 large_cave_depth = -33;
	u16 small_cave_num_min = 0;
	u16 small_cave_num_max = 0;
	u16 large_cave_num_min = 0;
	u16 large_cave_num_max = 2;
	float large_cave_flooded = 0.5f;
	s32 cavern_limit = -256;
	s32 cavern_taper = 256;
	float cavern_threshold = 0.7f;
	s32 dungeon_ymin = -31000;
	s32 dungeon_ymax = 31000;

	NoiseParams np_terrain_base;
	NoiseParams np_terrain_alt;
	NoiseParams np_terrain_persist;
	NoiseParams np_height_select;
	NoiseParams np_filler_depth;
	NoiseParams np_mount_height;
	NoiseParams np_ridge_uwater;
	NoiseParams np_mountain;
	NoiseParams np_ridge;
	NoiseParams np_floatland;
	NoiseParams np_cavern;
	NoiseParams np_cave1;
	NoiseParams np_cave2;
	NoiseParams np_dungeons;

	MapgenV7Params();
	~MapgenV7Params() = default;

	void readParams(const Settings *settings);
	void writeParams(Settings *settings) const;
	void setDefaultSettings(Settings *settings);
};


class MapgenV7 : public MapgenBasic {
public:
	MapgenV7(MapgenV7Params *params, EmergeParams *emerge);
	~MapgenV7();

	virtual MapgenType getType() const { return MAPGEN_V7; }

	virtual void makeChunk(BlockMakeData *data);
	int getSpawnLevelAtPoint(v2s32 p);

	float baseTerrainLevelAtPoint(s32 x, s32 z);
	float baseTerrainLevelFromMap(int index);
	bool getMountainTerrainAtPoint(s32 x, s32 y, s32 z);
	bool getMountainTerrainFromMap(int idx_xyz, int idx_xz, s32 y);
	bool getRiverChannelFromMap(int idx_xyz, int idx_xz, s32 y);
	bool getFloatlandTerrainFromMap(int idx_xyz, float float_offset);

	int generateTerrain();

private:
	s32 mount_zero_level;
	s32 floatland_ymin;
	s32 floatland_ymax;
	s32 floatland_taper;
	float float_taper_exp;
	float floatland_density;
	s32 floatland_ywater;

	float *float_offset_cache = nullptr;

	Noise *noise_terrain_base = nullptr;
	Noise *noise_terrain_alt = nullptr;
	Noise *noise_terrain_persist = nullptr;
	Noise *noise_height_select = nullptr;
	Noise *noise_mount_height = nullptr;
	Noise *noise_ridge_uwater = nullptr;
	Noise *noise_mountain = nullptr;
	Noise *noise_ridge = nullptr;
	Noise *noise_floatland = nullptr;
};
