"""Disposable synthetic schema, deliberately separate from production migrations."""

DDL = """
CREATE TABLE metadata (
    singleton BOOLEAN PRIMARY KEY CHECK (singleton),
    model TEXT NOT NULL, revision TEXT NOT NULL, dimensions INTEGER NOT NULL,
    configuration TEXT NOT NULL, generation BIGINT NOT NULL CHECK (generation > 0),
    CHECK (dimensions BETWEEN 1 AND 2000)
);
CREATE TABLE sources (
    binding TEXT NOT NULL, source_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0), epoch BIGINT NOT NULL CHECK (epoch >= 0),
    private BOOLEAN NOT NULL, excluded BOOLEAN NOT NULL, deleted BOOLEAN NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user','assistant','tool','system')),
    conversation_id TEXT NOT NULL, message_index INTEGER NOT NULL CHECK (message_index >= 0),
    turn_revision BIGINT NOT NULL CHECK (turn_revision > 0),
    PRIMARY KEY (binding,source_id),
    UNIQUE (binding,conversation_id,turn_revision,message_index)
);
CREATE TABLE memories (
    binding TEXT NOT NULL, memory_id TEXT NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0), text_hash TEXT NOT NULL,
    body TEXT, generation BIGINT NOT NULL CHECK (generation > 0),
    index_status TEXT NOT NULL CHECK (index_status IN ('pending','ready','invalid','deleted')),
    seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    PRIMARY KEY (binding,memory_id)
);
CREATE TABLE source_refs (
    binding TEXT NOT NULL, memory_id TEXT NOT NULL, position INTEGER NOT NULL,
    source_id TEXT NOT NULL, revision BIGINT NOT NULL, epoch BIGINT NOT NULL,
    private BOOLEAN NOT NULL, excluded BOOLEAN NOT NULL, deleted BOOLEAN NOT NULL,
    role TEXT NOT NULL,
    conversation_id TEXT NOT NULL, message_index INTEGER NOT NULL CHECK (message_index >= 0),
    turn_revision BIGINT NOT NULL CHECK (turn_revision > 0),
    PRIMARY KEY (binding,memory_id,position),
    UNIQUE (binding,memory_id,source_id),
    FOREIGN KEY (binding,memory_id) REFERENCES memories(binding,memory_id),
    FOREIGN KEY (binding,source_id) REFERENCES sources(binding,source_id)
);
CREATE INDEX source_refs_source ON source_refs(binding,source_id);
CREATE INDEX memories_scope_status ON memories(binding,index_status);
CREATE TABLE embeddings (
    binding TEXT NOT NULL, memory_id TEXT NOT NULL,
    memory_revision BIGINT NOT NULL, text_hash TEXT NOT NULL, generation BIGINT NOT NULL,
    model TEXT NOT NULL, revision TEXT NOT NULL, dimensions INTEGER NOT NULL,
    configuration TEXT NOT NULL, space_generation BIGINT NOT NULL,
    embedding public.vector NOT NULL,
    PRIMARY KEY (binding,memory_id),
    FOREIGN KEY (binding,memory_id) REFERENCES memories(binding,memory_id),
    CHECK (dimensions BETWEEN 1 AND 2000),
    CHECK (public.vector_dims(embedding)=dimensions)
);
"""

# MATERIALIZED prevents distance evaluation against an incompatible dimension.
# Every source must still equal the captured snapshot and remain eligible.
ELIGIBLE = """
SELECT m.memory_id,m.body,m.revision,m.text_hash,m.generation,m.seq,e.embedding
FROM memories m JOIN embeddings e
  ON e.binding=m.binding AND e.memory_id=m.memory_id
WHERE m.binding=%s AND m.index_status='ready'
  AND e.memory_revision=m.revision AND e.text_hash=m.text_hash
  AND e.generation=m.generation
  AND e.model=%s AND e.revision=%s AND e.dimensions=%s
  AND e.configuration=%s AND e.space_generation=%s
  AND EXISTS (SELECT 1 FROM source_refs r
              WHERE r.binding=m.binding AND r.memory_id=m.memory_id)
  AND NOT EXISTS (
    SELECT 1 FROM source_refs r LEFT JOIN sources s
      ON s.binding=r.binding AND s.source_id=r.source_id
    WHERE r.binding=m.binding AND r.memory_id=m.memory_id AND (
      s.source_id IS NULL OR s.revision<>r.revision OR s.epoch<>r.epoch
      OR s.private<>r.private OR s.excluded<>r.excluded OR s.deleted<>r.deleted
      OR s.role<>r.role OR s.private OR s.excluded OR s.deleted OR s.role<>'user'
      OR s.conversation_id<>r.conversation_id OR s.message_index<>r.message_index
      OR s.turn_revision<>r.turn_revision
    )
  )
"""

SEARCH = (
    "WITH eligible AS MATERIALIZED ("
    + ELIGIBLE
    + "), scored AS (SELECT *,embedding OPERATOR(public.<=>) %s::public.vector AS distance "
    "FROM eligible) SELECT memory_id,body,revision,text_hash,generation,1-distance AS score "
    "FROM scored WHERE distance<1 ORDER BY distance,seq DESC LIMIT %s"
)
