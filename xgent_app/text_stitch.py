"""Persistence for the existing manual stitching buffer; never model history."""
import json


async def ensure(conn):
    await conn.execute('CREATE TABLE IF NOT EXISTS text_stitch_drafts ('
        'conversation_id TEXT NOT NULL,generation INTEGER NOT NULL,chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,'
        'id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(conversation_id,generation,chat_id,user_id))')


async def read(db,key):
    async with db._transaction() as conn:
        await ensure(conn)
        cursor=await conn.execute('SELECT id,payload FROM text_stitch_drafts WHERE conversation_id=? AND generation=? AND chat_id=? AND user_id=?',key)
        row=await cursor.fetchone();await cursor.close()
        return {'id':row['id'],**json.loads(row['payload'])} if row else None


async def write(db,key,identifier,payload):
    async with db._transaction() as conn:
        await ensure(conn)
        await db._validate_conversation_write(conn,key[0])
        await conn.execute('INSERT INTO text_stitch_drafts VALUES(?,?,?,?,?,?) '
            'ON CONFLICT(conversation_id,generation,chat_id,user_id) DO UPDATE SET id=excluded.id,payload=excluded.payload',
            (*key,identifier,json.dumps(payload,ensure_ascii=False)))


async def remove(db,key,identifier):
    async with db._transaction() as conn:
        await ensure(conn)
        await conn.execute('DELETE FROM text_stitch_drafts WHERE conversation_id=? AND generation=? AND chat_id=? AND user_id=? AND id=?',(*key,identifier))
