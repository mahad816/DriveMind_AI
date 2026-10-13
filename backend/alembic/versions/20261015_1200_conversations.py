"""Normal-account conversations and immutable ordered turn identities."""

from alembic import op
import sqlalchemy as sa

revision = "20261015_1200"
down_revision = "20261014_1200"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_query_history_id_owner", "query_history", ["id", "user_id"])
    op.create_unique_constraint(
        "uq_application_sessions_id_owner", "application_sessions", ["id", "user_id"]
    )
    op.execute("""
        CREATE TABLE conversations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title VARCHAR(256) NOT NULL DEFAULT 'New chat',
            title_is_manual BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata_version INTEGER NOT NULL DEFAULT 1,
            content_version BIGINT NOT NULL DEFAULT 0,
            next_sequence BIGINT NOT NULL DEFAULT 1,
            deleted_at TIMESTAMPTZ,
            create_request_id UUID NOT NULL,
            create_payload_hash BYTEA NOT NULL,
            CONSTRAINT uq_conversations_id_owner UNIQUE (id, owner_id),
            CONSTRAINT uq_conversations_create_request UNIQUE (owner_id, create_request_id),
            CONSTRAINT ck_conversations_title CHECK (char_length(title) BETWEEN 1 AND 256 AND title = btrim(title) AND title ~ '[^[:space:]]'),
            CONSTRAINT ck_conversations_versions CHECK (metadata_version > 0 AND content_version >= 0 AND next_sequence > 0),
            CONSTRAINT ck_conversations_payload_hash CHECK (octet_length(create_payload_hash) = 32)
        )
    """)
    op.execute(
        "CREATE INDEX ix_conversations_owner_activity ON conversations (owner_id, last_activity_at DESC, id DESC) WHERE deleted_at IS NULL"
    )
    op.execute("""
        CREATE FUNCTION conversation_owner_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.owner_id IS DISTINCT FROM OLD.owner_id THEN
                RAISE EXCEPTION 'Conversation owner is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_conversation_owner_immutable BEFORE UPDATE ON conversations FOR EACH ROW EXECUTE FUNCTION conversation_owner_immutable()"
    )
    op.execute("""
        CREATE TABLE conversation_turns (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_id UUID NOT NULL,
            conversation_id UUID NOT NULL,
            client_request_id UUID NOT NULL,
            payload_hash BYTEA NOT NULL,
            sequence BIGINT NOT NULL,
            original_question TEXT NOT NULL,
            operation VARCHAR(16) NOT NULL,
            source_turn_id UUID,
            history_end_sequence BIGINT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'RUNNING',
            execution_id UUID NOT NULL,
            execution_deadline TIMESTAMPTZ NOT NULL,
            initiating_session_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ,
            error_code VARCHAR(64),
            retrieval_count INTEGER NOT NULL DEFAULT 0,
            query_history_id UUID,
            CONSTRAINT fk_turns_conversation_owner FOREIGN KEY (conversation_id, owner_id) REFERENCES conversations(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT fk_turns_source_owner FOREIGN KEY (source_turn_id, conversation_id, owner_id) REFERENCES conversation_turns(id, conversation_id, owner_id),
            CONSTRAINT fk_turns_result_owner FOREIGN KEY (query_history_id, owner_id) REFERENCES query_history(id, user_id),
            CONSTRAINT fk_turns_session_owner FOREIGN KEY (initiating_session_id, owner_id) REFERENCES application_sessions(id, user_id),
            CONSTRAINT uq_turns_id_conversation_owner UNIQUE (id, conversation_id, owner_id),
            CONSTRAINT uq_turns_owner_request UNIQUE (owner_id, client_request_id),
            CONSTRAINT uq_turns_conversation_sequence UNIQUE (conversation_id, sequence),
            CONSTRAINT uq_turns_result UNIQUE (query_history_id),
            CONSTRAINT ck_turns_status CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED', 'INTERRUPTED')),
            CONSTRAINT ck_turns_operation CHECK (operation IN ('ASK', 'RETRY', 'REGENERATE')),
            CONSTRAINT ck_turns_source CHECK ((operation = 'ASK' AND source_turn_id IS NULL) OR (operation IN ('RETRY', 'REGENERATE') AND source_turn_id IS NOT NULL AND source_turn_id <> id)),
            CONSTRAINT ck_turns_sequence CHECK (sequence > 0 AND history_end_sequence >= 0 AND history_end_sequence < sequence),
            CONSTRAINT ck_turns_question CHECK (original_question ~ '[^[:space:]]'),
            CONSTRAINT ck_turns_payload_hash CHECK (octet_length(payload_hash) = 32),
            CONSTRAINT ck_turns_retrieval_count CHECK (retrieval_count >= 0),
            CONSTRAINT ck_turns_result CHECK ((status = 'COMPLETED') = (query_history_id IS NOT NULL)),
            CONSTRAINT ck_turns_terminal CHECK ((status = 'RUNNING' AND finished_at IS NULL AND error_code IS NULL) OR (status = 'COMPLETED' AND finished_at IS NOT NULL AND error_code IS NULL) OR (status IN ('FAILED', 'INTERRUPTED') AND finished_at IS NOT NULL AND error_code IS NOT NULL)),
            CONSTRAINT ck_turns_error_code CHECK (error_code IS NULL OR error_code ~ '^[A-Z][A-Z0-9_]{0,63}$'),
            CONSTRAINT ck_turns_deadline CHECK (execution_deadline > created_at)
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX uq_turns_running_conversation ON conversation_turns (conversation_id) WHERE status = 'RUNNING'"
    )
    op.execute("""
        CREATE FUNCTION conversation_turn_identity_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF ROW(NEW.id, NEW.owner_id, NEW.conversation_id, NEW.client_request_id,
                   NEW.payload_hash, NEW.sequence, NEW.original_question, NEW.operation,
                   NEW.source_turn_id, NEW.history_end_sequence, NEW.execution_id,
                   NEW.execution_deadline, NEW.initiating_session_id)
               IS DISTINCT FROM
               ROW(OLD.id, OLD.owner_id, OLD.conversation_id, OLD.client_request_id,
                   OLD.payload_hash, OLD.sequence, OLD.original_question, OLD.operation,
                   OLD.source_turn_id, OLD.history_end_sequence, OLD.execution_id,
                   OLD.execution_deadline, OLD.initiating_session_id) THEN
                RAISE EXCEPTION 'Conversation turn identity is immutable' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute(
        "CREATE TRIGGER trg_turn_identity_immutable BEFORE UPDATE ON conversation_turns FOR EACH ROW EXECUTE FUNCTION conversation_turn_identity_immutable()"
    )


def downgrade() -> None:
    # Order matches repository locking; prevent concurrent insertion after the check.
    op.execute("LOCK TABLE conversations, conversation_turns IN ACCESS EXCLUSIVE MODE")
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM conversations) OR EXISTS (SELECT 1 FROM conversation_turns)"
            )
        )
        .scalar()
    ):
        raise RuntimeError("Retain conversation records before downgrading")
    op.drop_table("conversation_turns")
    op.execute("DROP FUNCTION conversation_turn_identity_immutable()")
    op.drop_table("conversations")
    op.execute("DROP FUNCTION conversation_owner_immutable()")
    op.drop_constraint("uq_application_sessions_id_owner", "application_sessions", type_="unique")
    op.drop_constraint("uq_query_history_id_owner", "query_history", type_="unique")
