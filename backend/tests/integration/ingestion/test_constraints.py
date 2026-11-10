import uuid

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

BATCH = text(
    "INSERT INTO ingestion.import_batches"
    " (id, source_id, record_type, file_name, file_sha256, status, row_count, started_at,"
    " finished_at) SELECT :id, s.id, 'orders', 'orders.json', :sha, 'completed', 1, now(), now()"
    " FROM ingestion.data_sources s WHERE s.name = 'shop'"
)
RAW = text(
    "INSERT INTO ingestion.raw_records (id, batch_id, source_id, line_no, payload, payload_sha256)"
    " SELECT :id, :batch_id, b.source_id, :line_no, '{}', :sha"
    " FROM ingestion.import_batches b WHERE b.id = :batch_id"
)
ORDER = text(
    "INSERT INTO ingestion.orders (id, source_id, external_id, raw_record_id, customer_name,"
    " customer_email, amount_minor, currency, status, placed_at)"
    " SELECT :id, r.source_id, 'ORD-000001', r.id, 'A', 'a@example.com', 100, 'USD',"
    " 'completed', now() FROM ingestion.raw_records r WHERE r.id = :raw_id"
)


def test_the_database_rejects_a_second_import_of_the_same_file_for_one_source(
    engine: Engine,
) -> None:
    sha = "a" * 64
    with engine.begin() as connection:
        connection.execute(BATCH, {"id": uuid.uuid4(), "sha": sha})

    with (
        pytest.raises(IntegrityError, match="import_batches_source_id_file_sha256_key"),
        engine.begin() as connection,
    ):
        connection.execute(BATCH, {"id": uuid.uuid4(), "sha": sha})


def test_the_database_rejects_a_duplicate_external_id_for_one_source(engine: Engine) -> None:
    batch_id, raw_ids = uuid.uuid4(), [uuid.uuid4(), uuid.uuid4()]
    with engine.begin() as connection:
        connection.execute(BATCH, {"id": batch_id, "sha": "b" * 64})
        for line_no, raw_id in enumerate(raw_ids, 1):
            connection.execute(
                RAW, {"id": raw_id, "batch_id": batch_id, "line_no": line_no, "sha": "c" * 64}
            )
        connection.execute(ORDER, {"id": uuid.uuid4(), "raw_id": raw_ids[0]})

    with (
        pytest.raises(IntegrityError, match="orders_source_id_external_id_key"),
        engine.begin() as connection,
    ):
        connection.execute(ORDER, {"id": uuid.uuid4(), "raw_id": raw_ids[1]})
