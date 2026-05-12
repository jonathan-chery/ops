import psycopg2
from psycopg2 import sql

from ..models.config import DatabaseConfig


class DatabaseProvider:
    def __init__(self, config: DatabaseConfig):
        self.config = config

    def _connect(self, dbname: str = "postgres"):
        if not self.config.host:
            raise RuntimeError("Database host not configured")
        return psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.admin_user,
            password=self.config.admin_password,
            dbname=dbname,
            sslmode=self.config.ssl_mode,
        )

    def test_connection(self) -> bool:
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    return True
        except Exception:
            return False

    def ensure_database(self, db_name: str) -> bool:
        try:
            with self._connect() as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM pg_database WHERE datname=%s", (db_name,)
                    )
                    if cur.fetchone():
                        return False  # Already exists
                    cur.execute(
                        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name))
                    )
                    return True
        except Exception as e:
            raise RuntimeError(f"Failed to create database {db_name}: {e}")

    def ensure_user(self, username: str, password: str, db_name: str) -> bool:
        try:
            with self._connect() as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (username,))
                    if cur.fetchone():
                        # User exists, update password
                        cur.execute(
                            sql.SQL("ALTER USER {} WITH PASSWORD %s").format(
                                sql.Identifier(username)
                            ),
                            (password,),
                        )
                    else:
                        cur.execute(
                            sql.SQL("CREATE USER {} WITH PASSWORD %s").format(
                                sql.Identifier(username)
                            ),
                            (password,),
                        )
                    # Grant privileges
                    cur.execute(
                        sql.SQL("GRANT ALL PRIVILEGES ON DATABASE {} TO {}").format(
                            sql.Identifier(db_name), sql.Identifier(username)
                        )
                    )
                    return True
        except Exception as e:
            raise RuntimeError(f"Failed to create user {username}: {e}")
