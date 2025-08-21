import os
import logging
from typing import Dict, Any, List
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DatabaseService:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.engine = self._create_engine()

    def _create_engine(self):
        db_type = self.config.get('database_type')
        logging.info(f"Attempting to create database engine for type: {db_type}")
        try:
            if db_type == 'sqlite':
                script_dir = os.path.dirname(__file__)
                data_dir = os.path.join(script_dir, '..', 'data')
                db_filename = self.config['database_path']
                full_db_path = os.path.join(data_dir, db_filename)
                
                if not os.path.isfile(full_db_path):
                    raise FileNotFoundError(f"Database file not found: {full_db_path}")
                
                engine = create_engine(f"sqlite:///{full_db_path}")
                logging.info("Successfully created SQLite engine.")
                return engine

            elif db_type == 'mysql':
                conn_str = f"mysql+pymysql://{self.config['user']}:{self.config['password']}@{self.config['host']}:{self.config['port']}/{self.config['database']}"
                engine = create_engine(conn_str, pool_pre_ping=True)
                logging.info("Successfully created MySQL engine.")
                return engine
            
            elif db_type == 'postgresql':
                conn_str = f"postgresql://{self.config['username']}:{self.config['password']}@{self.config['host']}:{self.config['port']}/{self.config['database_name']}"
                engine = create_engine(conn_str, pool_pre_ping=True)
                logging.info("Successfully created PostgreSQL engine.")
                return engine

            elif db_type == 'sqlserver':
                conn_str = f"mssql+pyodbc://{self.config['user']}:{self.config['password']}@{self.config['host']}:{self.config['port']}/{self.config['database']}?driver=ODBC+Driver+17+for+SQL+Server"
                engine = create_engine(conn_str, pool_pre_ping=True)
                logging.info("Successfully created SQL Server engine.")
                return engine
            else:
                logging.error(f"Unsupported database type: '{db_type}'")
                raise ValueError(f"Unsupported database type: '{db_type}'")
        except SQLAlchemyError as e:
            logging.error(f"Failed to create database engine: {e}", exc_info=True)
            raise ConnectionError(f"Failed to connect to the database: {e}")

    def test_connection(self) -> bool:
        try:
            with self.engine.connect() as connection:
                logging.info(f"Successfully connected to the database: {self.config.get('database_type')}")
                return True
        except Exception as e:
            logging.error(f"Database connection test failed: {e}", exc_info=True)
            return False

    def get_table_names(self) -> List[str]:
        try:
            inspector = inspect(self.engine)
            return inspector.get_table_names()
        except SQLAlchemyError as e:
            raise RuntimeError(f"Failed to get table names: {e}")

    def get_engine(self):
        return self.engine
