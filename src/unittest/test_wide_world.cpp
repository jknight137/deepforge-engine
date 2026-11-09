// Modified for Deepforge on 2026-11-09; original notices retained.
// Dadcraft wide-world extension
// SPDX-License-Identifier: LGPL-2.1-or-later
#include "test.h"
#include "gamedef.h"
#include "mapblock.h"
#include "dummymap.h"
#include "environment.h"
#include "raycast.h"
#include "nodemetadata.h"
#include "nodedef.h"
#include "mapgen/mapgen.h"
#include "database/database-sqlite3.h"
#include "network/networkpacket.h"
#include "serialization.h"
#include "util/areastore.h"
#include "util/numeric.h"
#include "util/pointedthing.h"
#include "util/serialize.h"
#include "util/world_coordinates.h"
#include <set>
#include <limits>

class FarTestEnvironment : public Environment {
    DummyMap map;
public:
    FarTestEnvironment(IGameDef *gamedef, v3s32 target, content_t content = t_CONTENT_STONE) :
        Environment(gamedef), map(gamedef, getNodeBlockPos(target-v3s32(3)), getNodeBlockPos(target+v3s32(3))) {
        map.fill(getNodeBlockPos(target-v3s32(3)), getNodeBlockPos(target+v3s32(3)), MapNode(CONTENT_AIR));
        map.setNode(target, MapNode(content));
    }
    void step(f32 dtime) override {}
    Map &getMap() override { return map; }
    void getSelectedActiveObjects(const core::line3d<f32> &line, std::vector<PointedThing> &objects,
        const std::optional<Pointabilities> &pointabilities) override {}
};

class TestWideWorld : public TestBase {
public:
    TestWideWorld() { TestManager::registerTestModule(this); }
    const char *getName() { return "TestWideWorld"; }
    void runTests(IGameDef *gamedef) {
        TEST(coordinates, gamedef);
        TEST(packets);
        TEST(pointing);
        TEST(sqlite);
        TEST(metadata, gamedef);
        TEST(blockPersistence, gamedef);
        TEST(raycast, gamedef);
        TEST(areas);
        TEST(hashes);
        TEST(budgets);
    }
    void coordinates(IGameDef *gamedef) {
        for (s32 n : {-65535, -40000, -32769, -32768, -1, 0, 32767, 32768, 40000, 65535}) {
            v3s32 pos(n, n, n);
            UASSERT(floatToInt(intToFloat(pos, BS), BS) == pos);
            v3s32 blockpos = getNodeBlockPos(pos);
            UASSERT(!blockpos_over_max_limit(blockpos));
            MapBlock block(blockpos, gamedef);
            UASSERT(block.getPosRelative() == blockpos * MAP_BLOCKSIZE);
            UASSERT(block.getPosRelative().X <= n);
            UASSERT(n - block.getPosRelative().X < MAP_BLOCKSIZE);
            std::stringstream fixed;
            writeV3F1000(fixed, intToFloat(pos, BS));
            UASSERT(floatToInt(readV3F1000(fixed), BS) == pos);
        }
        auto edges = get_mapgen_edges(MAX_MAP_GENERATION_LIMIT, v3s32(5, 5, 5));
        UASSERT(edges.first.X < -32768 && edges.second.X > 32767);
        UASSERT(edges.first.X >= -65535 && edges.second.X <= 65535);
        UASSERT(std::nextafter(655350.0f, std::numeric_limits<float>::infinity()) - 655350.0f < 0.1f);
    }
    void packets() {
        NetworkPacket packet(0, 0);
        v3s32 first(-65535, 40000, 65535), second(32768, -40000, -32769), result;
        packet << first << second;
        UASSERTEQ(u32, packet.getSize(), 24);
        packet.seek(0);
        packet >> result;
        UASSERT(result == first);
        packet >> result;
        UASSERT(result == second);
        UASSERTEQ(u32, packet.getRemainingBytes(), 0);
        EXCEPTION_CHECK(PacketError, packet >> result);
        UASSERTEQ(u16, LATEST_PROTOCOL_VERSION, 32001);
        UASSERTEQ(u16, SERVER_PROTOCOL_VERSION_MIN, 32001);
        UASSERTEQ(u16, CLIENT_PROTOCOL_VERSION_MIN, 32001);
    }
    void pointing() {
        PointedThing thing;
        thing.type = POINTEDTHING_NODE;
        thing.node_undersurface = v3s32(-65535, 40000, 65534);
        thing.node_abovesurface = v3s32(-65535, 40000, 65535);
        std::stringstream stream;
        thing.serialize(stream);
        PointedThing restored;
        restored.deSerialize(stream);
        UASSERT(restored.node_undersurface == thing.node_undersurface);
        UASSERT(restored.node_abovesurface == thing.node_abovesurface);
        std::stringstream legacy;
        writeU8(legacy, 0); writeU8(legacy, POINTEDTHING_NODE);
        writeV3S16(legacy, v3s16(-31000, 0, 31000));
        writeV3S16(legacy, v3s16(-31000, 1, 31000));
        restored.deSerialize(legacy);
        UASSERT(restored.node_abovesurface == v3s32(-31000, 1, 31000));
    }
    void sqlite() {
        const auto path = getTestTempDirectory();
        const std::vector<v3s32> positions = {{4095, -4096, 2500}, {-4096, 4095, -2500}, {0, 0, 0}};
        {
            MapDatabaseSQLite3 db(path);
            db.beginSave();
            for (size_t i = 0; i < positions.size(); ++i)
                UASSERT(db.saveBlock(positions[i], "wide" + std::to_string(i)));
            db.endSave();
        }
        {
            MapDatabaseSQLite3 db(path);
            for (size_t i = 0; i < positions.size(); ++i) {
                std::string data;
                db.loadBlock(positions[i], &data);
                UASSERT(data == "wide" + std::to_string(i));
            }
            std::vector<v3s32> found;
            db.listAllLoadableBlocks(found);
            UASSERTEQ(size_t, found.size(), positions.size());
        }
        UASSERT(MapDatabase::getIntegerAsBlock(MapDatabase::getBlockAsInteger(v3s32(-2048, 2047, -1))) == v3s32(-2048, 2047, -1));
        EXCEPTION_CHECK(FileNotGoodException, MapDatabase::getBlockAsInteger(v3s32(2048, 0, 0)));
        EXCEPTION_CHECK(FileNotGoodException, MapDatabase::getBlockAsInteger(v3s32(0, -2049, 0)));
    }
    void metadata(IGameDef *gamedef) {
        NodeMetadataList source;
        v3s32 position(-65535, 40000, 65535);
        auto entry = new NodeMetadata(gamedef->idef());
        entry->setString("identity", "far-location");
        source.set(position, entry);
        std::stringstream stream;
        source.serialize(stream, SER_FMT_VER_HIGHEST_WRITE, true, true);
        UASSERTEQ(int, static_cast<unsigned char>(stream.str()[0]), 3);
        NodeMetadataList restored;
        restored.deSerialize(stream, gamedef->idef(), true);
        UASSERT(restored.get(position));
        UASSERT(restored.get(position)->getString("identity") == "far-location");
        std::stringstream legacy;
        writeU8(legacy, 2); writeU16(legacy, 1);
        writeV3S16(legacy, v3s16(-31000, 0, 31000));
        entry->serialize(legacy, 2, true);
        NodeMetadataList old;
        old.deSerialize(legacy, gamedef->idef(), true);
        UASSERT(old.get(v3s32(-31000, 0, 31000))->getString("identity") == "far-location");
        UASSERTEQ(int, SER_FMT_VER_HIGHEST_WRITE, 30);
        UASSERT(ser_ver_supported_read(29));
        UASSERT(!ser_ver_supported_read(31));
    }
    void blockPersistence(IGameDef *gamedef) {
        const v3s32 blockpos(-4096, 2500, 4095), local(1, 2, 3);
        MapBlock source(blockpos, gamedef);
        source.setNode(local, MapNode(CONTENT_AIR, 14, 7));
        auto meta = new NodeMetadata(gamedef->idef());
        meta->setString("persistent-id", "actor-or-location");
        source.m_node_metadata.set(local, meta);
        source.setNodeTimer(NodeTimer(30.0f, 5.0f, local));
        StaticObject object;
        object.type = 7;
        object.pos = intToFloat(v3s32(-65535, 40000, 65535), BS);
        object.data = "persistent-object";
        source.m_static_objects.insert(0, object);
        std::stringstream bytes;
        source.serialize(bytes, 30, true, -1);
        MapBlock restored(blockpos, gamedef);
        restored.deSerialize(bytes, 30, true);
        UASSERT(restored.getNodeNoCheck(local.X, local.Y, local.Z) == MapNode(CONTENT_AIR, 14, 7));
        UASSERT(restored.m_node_metadata.get(local)->getString("persistent-id") == "actor-or-location");
        UASSERTEQ(float, restored.getNodeTimer(local).timeout, 30.0f);
        UASSERTEQ(float, restored.getNodeTimer(local).elapsed, 5.0f);
        UASSERTEQ(size_t, restored.m_static_objects.getStoredSize(), 1);
        const auto &saved = restored.m_static_objects.getAllStored()[0];
        UASSERT(saved.pos == object.pos && saved.data == object.data);
    }
    void areas() {
        VectorAreaStore store;
        Area area(v3s32(-65535, 40000, 40001), v3s32(-40000, 40010, 65535));
        area.data = "location";
        area.id = 123;
        UASSERT(store.insertArea(&area));
        std::stringstream encoded;
        store.serialize(encoded);
        const auto bytes = encoded.str();
        VectorAreaStore restored;
        restored.deserialize(encoded);
        UASSERT(restored.getArea(123));
        UASSERT(restored.getArea(123)->minedge == area.minedge);
        std::stringstream truncated(bytes.substr(0, bytes.size() - 4));
        EXCEPTION_CHECK(SerializationError, restored.deserialize(truncated));
        VectorAreaStore oversized;
        area.data.assign(65536, 'x');
        UASSERT(oversized.insertArea(&area));
        std::stringstream output;
        EXCEPTION_CHECK(SerializationError, oversized.serialize(output));
        std::stringstream legacy;
        writeU8(legacy, 0); writeU16(legacy, 1);
        writeV3S16(legacy, v3s16(-31000, 0, 0));
        writeV3S16(legacy, v3s16(31000, 1, 1)); writeU16(legacy, 0);
        VectorAreaStore old;
        old.deserialize(legacy);
        UASSERTEQ(size_t, old.size(), 1);
    }
    void raycast(IGameDef *gamedef) {
        ContentFeatures custom;
        custom.name = "test:wide_custom_box";
        custom.drawtype = NDT_NODEBOX;
        custom.selection_box.type = NODEBOX_FIXED;
        custom.selection_box.fixed.emplace_back(4.975f, -4.0f, -4.0f, 6.0f, 4.0f, 4.0f);
        content_t custom_id = const_cast<NodeDefManager *>(gamedef->ndef())->set(custom.name, std::move(custom));
        for (s32 edge : {-65530, -40000, 40000, 65530}) {
            const v3s32 target(edge, edge, edge);
            FarTestEnvironment env(gamedef, target);
            for (v3s32 axis : {v3s32(1,0,0), v3s32(-1,0,0), v3s32(0,1,0), v3s32(0,-1,0), v3s32(0,0,1), v3s32(0,0,-1)}) {
                core::line3d<f32> line(intToFloat(target+axis*2, BS), intToFloat(target-axis*2, BS));
                RaycastState state(line, false, false, {});
                PointedThing hit;
                env.continueRaycast(&state, &hit);
                UASSERTEQ(int, hit.type, POINTEDTHING_NODE);
                UASSERT(hit.node_undersurface == target);
                UASSERT(hit.node_real_undersurface == target);
                UASSERT(hit.node_abovesurface == target+axis);
            }
            FarTestEnvironment custom_env(gamedef, target, custom_id);
            RaycastState state(core::line3d<f32>(intToFloat(target, BS), intToFloat(target+v3s32(2,0,0), BS)), false, false, {});
            PointedThing hit;
            custom_env.continueRaycast(&state, &hit);
            UASSERTEQ(int, hit.type, POINTEDTHING_NODE);
            UASSERT(hit.node_real_undersurface == target);
        }
    }
    void hashes() {
        std::set<u64> unique;
        const std::vector<s32> values = {-65535, -40000, -32769, -32768, -1, 0, 1, 32767, 32768, 40000, 65535};
        for (s32 x : values) for (s32 y : values) for (s32 z : values) {
            u64 hash = hashWorldNodePosition(v3s32(x, y, z));
            UASSERT(unique.insert(hash).second);
            UASSERT(static_cast<u64>(static_cast<double>(hash)) == hash);
            if (x >= -32768 && x <= 32767 && y >= -32768 && y <= 32767 && z >= -32768 && z <= 32767) {
                UASSERTEQ(u64, hash, ((u64)(z+32768)<<32) | ((u64)(y+32768)<<16) | (u64)(x+32768));
            } else {
                UASSERT(hash >= (1ULL << 51));
            }
        }
        EXCEPTION_CHECK(std::out_of_range, hashWorldNodePosition(v3s32(65536, 0, 0)));
    }
    void budgets() {
        VoxelManipulator vm;
        VoxelArea full(v3s32(-65535), v3s32(65535));
        EXCEPTION_CHECK(BaseException, vm.addArea(full));
        UASSERT(vm.m_data == nullptr);
        EXCEPTION_CHECK(InvalidPositionException, VoxelArea(v3s32(S32_MIN), v3s32(S32_MAX)));
        UASSERT(isNodeAreaWithinVolume(v3s32(40000, -40000, 65530), v3s32(40004, -39996, 65535), 150));
        UASSERT(!isNodeAreaWithinVolume(v3s32(-65535), v3s32(65535), 4000000));
        UASSERT(!isNodeAreaWithinVolume(v3s32(S32_MIN), v3s32(S32_MAX), U64_MAX));
        UASSERT(!isNodeAreaWithinVolume(v3s32(5), v3s32(4), 4000000));
    }
};
static TestWideWorld g_wide_world_test;
