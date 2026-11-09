// Modified for Deepforge on 2026-11-09; original notices retained.
// Dadcraft wide-world extension
// SPDX-License-Identifier: LGPL-2.1-or-later
#pragma once
#include "irr_v3d.h"
#include <stdexcept>

inline u64 hashWorldNodePosition(v3s32 pos)
{
    if (pos.X >= -32768 && pos.X <= 32767 && pos.Y >= -32768 && pos.Y <= 32767 && pos.Z >= -32768 && pos.Z <= 32767)
        return ((u64)(pos.Z + 32768) << 32) | ((u64)(pos.Y + 32768) << 16) | (u64)(pos.X + 32768);
    if (pos.X < -65535 || pos.X > 65535 || pos.Y < -65535 || pos.Y > 65535 || pos.Z < -65535 || pos.Z > 65535)
        throw std::out_of_range("Node coordinate outside supported wide world");
    return (1ULL << 51) + ((u64)(pos.Z + 65536) << 34) + ((u64)(pos.Y + 65536) << 17) + (u64)(pos.X + 65536);
}
