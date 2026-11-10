from alembic import context
from sqlalchemy import create_engine

from recon.bootstrap.settings import database_url

url = context.config.get_main_option("sqlalchemy.url") or database_url()
engine = create_engine(url)
with engine.connect() as connection:
    context.configure(connection=connection, transaction_per_migration=True)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
