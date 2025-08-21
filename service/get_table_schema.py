import os
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError
from .database_service import DatabaseService

def get_database_fingerprint(db_config: Dict) -> str:
    """Generates a fingerprint for the database configuration."""
    config_str = json.dumps(db_config, sort_keys=True)
    return hashlib.md5(config_str.encode()).hexdigest()

def get_cache_file_path(db_config: Dict) -> str:
    """Gets the cache file path based on the database configuration."""
    script_dir = os.path.dirname(__file__)
    cache_dir = os.path.join(script_dir, '..', 'cache')
    os.makedirs(cache_dir, exist_ok=True)
    fingerprint = get_database_fingerprint(db_config)
    return os.path.join(cache_dir, f"schema_cache_{fingerprint}.json")

def load_cache(cache_file_path: str) -> Optional[Dict]:
    """Loads schema information from a cache file."""
    try:
        if os.path.exists(cache_file_path):
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (IOError, json.JSONDecodeError) as e:
        print(f"Cache load failed: {e}")
    return None

def save_cache(cache_file_path: str, schema_data: Dict) -> None:
    """Saves schema information to a cache file."""
    try:
        with open(cache_file_path, 'w', encoding='utf-8') as f:
            json.dump(schema_data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Cache save failed: {e}")

def is_cache_valid(cache_file_path: str, max_age_hours: int = 24) -> bool:
    """Checks if the cache is valid based on its age."""
    cached_data = load_cache(cache_file_path)
    if not cached_data or 'timestamp' not in cached_data:
        return False
    
    try:
        timestamp = datetime.fromisoformat(cached_data['timestamp'])
        return datetime.now() - timestamp < timedelta(hours=max_age_hours)
    except (ValueError, TypeError):
        return False

def extract_database_info(db_config: Dict) -> Dict[str, Any]:
    """Extracts detailed information from the database."""
    try:
        db_service = DatabaseService(db_config)
        engine = db_service.get_engine()
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        
        if not table_names:
            raise ValueError("No tables found in the database.")

        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "database_config": db_config,
            "tables": {},
            "relationships": [],
            "table_summary": {}
        }

        for table_name in table_names:
            columns = inspector.get_columns(table_name)
            
            column_definitions = [f"  `{col['name']}` {col['type']}" for col in columns]
            create_table_sql = "CREATE TABLE `{}` (\n{}\n);".format(table_name, ',\n'.join(column_definitions))
            
            column_info = [{
                "name": col['name'], "type": str(col['type']),
                "nullable": col.get('nullable', True),
                "default": str(col.get('default')) if col.get('default') is not None else None
            } for col in columns]
            
            cache_data["tables"][table_name] = {
                "create_sql": create_table_sql, "columns": column_info,
                "column_count": len(columns)
            }
            
            col_names = [col["name"] for col in column_info]
            description = f"Table {table_name} has {len(columns)} columns: {', '.join(col_names[:5])}"
            if len(columns) > 5:
                description += "..."
            cache_data["table_summary"][table_name] = {
                "column_names": col_names, "column_count": len(columns),
                "description": description
            }

        for table_name in table_names:
            for fk in inspector.get_foreign_keys(table_name):
                cache_data["relationships"].append({
                    "from_table": table_name, "from_columns": fk['constrained_columns'],
                    "to_table": fk['referred_table'], "to_columns": fk['referred_columns'],
                    "description": f"`{table_name}`.`{', '.join(fk['constrained_columns'])}` can be joined with `{fk['referred_table']}`.`{', '.join(fk['referred_columns'])}`"
                })

        return cache_data

    except (SQLAlchemyError, ValueError) as e:
        raise RuntimeError(f"Error getting table schema: {e}")

def get_table_overview(db_config: Dict, force_refresh: bool = False, use_relationship_filter: bool = False) -> str:
    """
    Gets an overview of the database tables, using cache if available.
    Can optionally filter to show only tables with relationships.
    """
    cache_file_path = get_cache_file_path(db_config)
    
    formatter = format_table_overview_for_selection if use_relationship_filter else format_table_overview

    if not force_refresh and is_cache_valid(cache_file_path):
        print("📋 Loading table schema overview from cache...")
        cache_data = load_cache(cache_file_path)
        if cache_data:
            return formatter(cache_data)
    
    print("🔄 Extracting table schema information from the database...")
    try:
        schema_data = extract_database_info(db_config)
        save_cache(cache_file_path, schema_data)
        return formatter(schema_data)
    except RuntimeError as e:
        return str(e)

def format_table_overview(cache_data: Dict) -> str:
    """Formats the cached data into a simplified string overview."""
    overview_parts = []
    
    for table_name, table_data in cache_data.get("tables", {}).items():
        columns = table_data.get("columns", [])
        if not columns:
            continue
        
        columns_str = ", ".join([f"`{col['name']}` ({col['type']})" for col in columns])
        overview_parts.append(f"-- Table: `{table_name}`")
        overview_parts.append(f"-- Columns: {columns_str}")

    if cache_data.get("relationships"):
        overview_parts.append("\n-- Relationships:")
        for rel in cache_data["relationships"]:
            overview_parts.append(f"-- {rel['description']}")
    
    return "\n".join(overview_parts)


def format_table_overview_for_selection(cache_data: Dict) -> str:
    """
    Formats the cached data into a string overview, but only includes tables that have relationships.
    """
    overview_parts = []
    
    # First, find all tables that are part of any relationship
    related_tables = set()
    relationships = cache_data.get("relationships", [])
    if not relationships:
        # If there are no relationships, return an empty string or some indicator.
        # Or alternatively, fall back to the old format. For now, let's return a specific message.
        return "No relationships found between tables. Unable to provide a filtered view."

    for rel in relationships:
        related_tables.add(rel['from_table'])
        related_tables.add(rel['to_table'])

    # Now, build the overview string for only these tables
    for table_name in sorted(list(related_tables)): # Sorting for consistent output
        if table_name in cache_data.get("tables", {}):
            table_data = cache_data["tables"][table_name]
            columns = table_data.get("columns", [])
            if not columns:
                continue
            
            columns_str = ", ".join([f"`{col['name']}` ({col['type']})" for col in columns])
            overview_parts.append(f"-- Table: `{table_name}`")
            overview_parts.append(f"-- Columns: {columns_str}")

    # Add the relationships section at the end
    if relationships:
        overview_parts.append("\n-- Relationships:")
        for rel in relationships:
            overview_parts.append(f"-- {rel['description']}")
    
    return "\n".join(overview_parts)

def get_simplified_schemas_for_tables(db_config: Dict, table_names: List[str]) -> str:
    """Gets the simplified schema for specific tables."""
    cache_file_path = get_cache_file_path(db_config)
    cache_data = load_cache(cache_file_path)
    
    if not cache_data:
        return "Error: Cache data not found. Please run 'Get Table Overview' first."

    overview_parts = []
    
    for table_name in table_names:
        if table_name in cache_data.get("tables", {}):
            table_data = cache_data["tables"][table_name]
            columns = table_data.get("columns", [])
            if not columns:
                continue
            
            columns_str = ", ".join([f"`{col['name']}` ({col['type']})" for col in columns])
            overview_parts.append(f"-- Table: `{table_name}`")
            overview_parts.append(f"-- Columns: {columns_str}")

    # Filter relationships to only include those relevant to the selected tables
    relevant_relationships = [
        rel["description"] for rel in cache_data.get("relationships", [])
        if rel["from_table"] in table_names and rel["to_table"] in table_names
    ]
    
    if relevant_relationships:
        overview_parts.append("\n-- Relationships:")
        for rel_desc in relevant_relationships:
            overview_parts.append(f"-- {rel_desc}")
            
    return "\n".join(overview_parts)

def get_specific_table_schemas(db_config: Dict, table_names: List[str]) -> str:
    """Gets the detailed schema for specific tables."""
    cache_file_path = get_cache_file_path(db_config)
    cache_data = load_cache(cache_file_path)
    
    if not cache_data:
        return "Error: Cache data not found. Please run get_table_overview() first."
    
    detailed_schemas = [
        cache_data["tables"][table_name]["create_sql"]
        for table_name in table_names if table_name in cache_data["tables"]
    ]
    
    relevant_relationships = [
        rel["description"] for rel in cache_data.get("relationships", [])
        if rel["from_table"] in table_names or rel["to_table"] in table_names
    ]
    
    if relevant_relationships:
        detailed_schemas.append("\n/*\nForeign Key Relationships:\n" + "\n".join(f"-- {rel}" for rel in relevant_relationships) + "\n*/")
    
    return "\n\n".join(detailed_schemas)

def clear_cache(db_config: Optional[Dict] = None) -> None:
    """Clears cache files."""
    script_dir = os.path.dirname(__file__)
    cache_dir = os.path.join(script_dir, '..', 'cache')
    
    if not os.path.exists(cache_dir):
        print("Cache directory does not exist.")
        return
    
    if db_config:
        cache_file_path = get_cache_file_path(db_config)
        if os.path.exists(cache_file_path):
            os.remove(cache_file_path)
            print(f"✅ Cleared cache: {cache_file_path}")
    else:
        cache_files = [f for f in os.listdir(cache_dir) if f.startswith("schema_cache_")]
        for cache_file in cache_files:
            os.remove(os.path.join(cache_dir, cache_file))
        print(f"✅ Cleared {len(cache_files)} cache files.")
