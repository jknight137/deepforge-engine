// Modified for Deepforge on 2026-11-09; original notices retained.
// Luanti
// SPDX-License-Identifier: LGPL-2.1-or-later
// Copyright (C) 2014 celeron55, Perttu Ahola <celeron55@gmail.com>

#pragma once

#include "config.h"

#if USE_REDIS

#include <hiredis.h>
#include <string>
#include "database.h"

class Settings;

class Database_Redis : public MapDatabase
{
public:
	Database_Redis(Settings &conf);
	~Database_Redis();

	void beginSave();
	void endSave();

	bool saveBlock(const v3s32 &pos, std::string_view data);
	void loadBlock(const v3s32 &pos, std::string *block);
	bool deleteBlock(const v3s32 &pos);
	void listAllLoadableBlocks(std::vector<v3s32> &dst);

private:
	redisContext *ctx = nullptr;
	std::string hash = "";
};

#endif // USE_REDIS
