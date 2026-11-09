# Database backends

Deepforge qualifies SQLite for the expanded coordinate envelope. Mapblocks use
independent x, y and z key columns. Legacy packed keys are readable only within
their supported coordinate range. Do not enable an unqualified backend for a
wide-coordinate world.

Keep the map, player, authentication and mod-storage databases with the world.
Back up an offline world before changing backend or serialization format.
The native network protocol is 32001 and new mapblocks use format 30, so clients
and servers must use compatible Deepforge builds.

The optional Python platform has its own SQLite database for identities,
controllers, memory, schedules and script state. Its transactions do not span
engine map or inventory storage. Keep engine command receipts with the matching
platform namespace. Use a new namespace and database for an independent copy.
