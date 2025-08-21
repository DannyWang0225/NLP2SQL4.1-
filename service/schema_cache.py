import os
import json
from typing import Dict, List, Optional

class SchemaCache:
    def __init__(self, cache_dir: str = "schema_cache"):
        self.cache_dir = os.path.join(os.path.dirname(__file__), '..', cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Cache files
        self.tables_file = os.path.join(self.cache_dir, "tables.json")
        self.relationships_file = os.path.join(self.cache_dir, "relationships.json")
        self.schemas_dir = os.path.join(self.cache_dir, "table_schemas")
        os.makedirs(self.schemas_dir, exist_ok=True)

    def save_table_list(self, tables: List[str]) -> None:
        """Save list of all tables"""
        with open(self.tables_file, 'w', encoding='utf-8') as f:
            json.dump(tables, f, ensure_ascii=False, indent=2)

    def save_relationships(self, relationships: List[Dict]) -> None:
        """Save table relationships"""
        with open(self.relationships_file, 'w', encoding='utf-8') as f:
            json.dump(relationships, f, ensure_ascii=False, indent=2)

    def save_table_schema(self, table_name: str, schema: str) -> None:
        """Save schema for a single table"""
        file_path = os.path.join(self.schemas_dir, f"{table_name}.sql")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(schema)

    def get_table_list(self) -> Optional[List[str]]:
        """Get list of all tables"""
        try:
            with open(self.tables_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def get_relationships(self) -> Optional[List[Dict]]:
        """Get table relationships"""
        try:
            with open(self.relationships_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    def get_table_schema(self, table_name: str) -> Optional[str]:
        """Get schema for a single table"""
        file_path = os.path.join(self.schemas_dir, f"{table_name}.sql")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return None

    def get_schemas_for_tables(self, table_names: List[str]) -> str:
        """Get combined schema for specified tables"""
        schemas = []
        for table in table_names:
            schema = self.get_table_schema(table)
            if schema:
                schemas.append(schema)
        
        relationships = self.get_relationships() or []
        rel_text = []
        for rel in relationships:
            if rel["table"] in table_names and rel["referred_table"] in table_names:
                rel_text.append(rel["description"])

        final_schema = "\n\n".join(schemas)
        if rel_text:
            final_schema += "\n\n/*\nForeign Key Relationships:\n" + "\n".join(rel_text) + "\n*/"
        
        return final_schema
