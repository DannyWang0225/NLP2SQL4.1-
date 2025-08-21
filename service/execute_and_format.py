import re
from typing import List, Dict, Any, Tuple
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from .database_service import DatabaseService

def execute_queries_and_format_with_dependencies(config: Dict[str, Any], execution_plan: Dict) -> List[Dict[str, Any]]:
    """
    Executes queries with dependencies and returns results, including raw data and formatted text.
    This version uses SQLAlchemy for database interaction, supporting multiple database types.
    """
    try:
        db_service = DatabaseService(config)
        engine = db_service.get_engine()
    except (FileNotFoundError, ValueError, ConnectionError) as e:
        return [{"description": "Database Connection Error", "formatted_text": f"Error: {e}", "raw_results": [], "error": str(e)}]

    with engine.connect() as connection:
        step_results_for_deps = {}
        output_results = []
        
        execution_steps = execution_plan.get("execution_plan", [])
        
        for step_info in execution_steps:
            step_id = step_info["step"]
            query_id = step_info["query_id"]
            sql_template = step_info["sql"]
            depends_on = step_info.get("depends_on", [])
            description = step_info.get("description", f"Executing query {step_id}")

            sql_query, params = _resolve_query_parameters(sql_template, step_results_for_deps, depends_on)

            if sql_query is None:
                error_msg = f"Step {step_id} ({description}): Execution failed because a dependent query returned no results."
                output_results.append({"description": description, "formatted_text": error_msg, "raw_results": [], "error": "Dependency resolution failed"})
                continue
            
            print(f"Executing SQL: {sql_query} with params: {params}")
            
            try:
                result_proxy = connection.execute(text(sql_query), params)
                
                raw_results = [dict(row._mapping) for row in result_proxy]
                step_results_for_deps[query_id] = raw_results
                
                if raw_results:
                    formatted_text = _format_step_result(step_info, raw_results)
                    output_results.append({
                        "description": description,
                        "formatted_text": formatted_text,
                        "raw_results": raw_results
                    })
                else:
                    msg = f"Step {step_id} ({description}): No matching data found"
                    output_results.append({"description": description, "formatted_text": msg, "raw_results": []})
                    
            except SQLAlchemyError as e:
                error_msg = f"Step {step_id} failed to execute: {e}\nSQL: {sql_query}"
                output_results.append({"description": description, "formatted_text": error_msg, "raw_results": [], "error": str(e)})

        return output_results

def _resolve_query_parameters(sql_template: str, step_results: Dict, depends_on: List[str]) -> Tuple[str, Dict]:
    """
    Resolves parameter placeholders in the SQL template with actual query results
    using parameter binding to prevent SQL injection.
    """
    params = {}
    parameter_pattern = r'\{\{([^}]+)\}\}'
    
    def replacer(match):
        param_name = match.group(1)
        if param_name in params:
            return f":{param_name}"

        param_value = _extract_parameter_value(param_name, step_results, depends_on)
        
        if param_value is None:
            raise ValueError(f"Could not resolve parameter: {param_name}")
            
        params[param_name] = param_value
        return f":{param_name}"

    try:
        sql_query = re.sub(parameter_pattern, replacer, sql_template)
        return sql_query, params
    except ValueError as e:
        print(f"Parameter resolution failed: {e}")
        return None, None

def _extract_parameter_value(param_name: str, step_results: Dict, depends_on: List[str]) -> Any:
    """
    Extracts a parameter value from the results of a previous step.
    It handles both single values and lists of values for 'IN' clauses.
    """
    # Determine if the parameter is expected to be a list (e.g., for an IN clause)
    is_list_parameter = param_name.endswith(('_ids', '_id', 's'))

    values = []
    for dep_query_id in depends_on:
        if dep_query_id in step_results:
            dep_results = step_results[dep_query_id]
            if not dep_results:
                continue

            for row in dep_results:
                # For non-list parameters, look for an exact match and return the first one found.
                if not is_list_parameter:
                    if param_name in row:
                        return row[param_name]
                    # Fallback for single-column results if no exact name match
                    if len(row) == 1:
                        return list(row.values())[0]

                # For list parameters, aggregate values.
                else:
                    # Case 1: Result has only one column. The most reliable scenario.
                    if len(row) == 1:
                        values.append(list(row.values())[0])
                        continue
                    
                    # Case 2: An exact column name match exists.
                    if param_name in row:
                        values.append(row[param_name])
                        continue

                    # Case 3: Try to guess the column name by singularizing the parameter.
                    # (e.g., param 'user_ids' -> column 'user_id', param 'products' -> column 'product')
                    guess = param_name
                    if guess.endswith('_ids'):
                        guess = guess[:-4] + '_id'  # user_ids -> user_id
                    elif guess.endswith('s'):
                        guess = guess[:-1] # products -> product
                    
                    if guess in row:
                        values.append(row[guess])
                        continue
    
    if is_list_parameter:
        if not values:
            # Return None if no values were found, allowing the caller to handle it.
            return None
        # Use tuple for immutability, which is good practice for parameters.
        # Using set() removes duplicates.
        return tuple(set(values))

    # If a non-list parameter was not found, return None.
    return None


def _format_step_result(step_info: Dict, raw_results: List[Dict]) -> str:
    """格式化单个步骤的查询结果，并动态调整列宽。"""
    step_id = step_info["step"]
    description = step_info.get("description", f"查询步骤 {step_id}")
    
    if not raw_results:
        return f"步骤 {step_id} ({description}): 未找到数据"
    
    columns = list(raw_results[0].keys())
    result_lines = [f"步骤 {step_id} - {description}: (共 {len(raw_results)} 条记录)"]
    
    try:
        col_widths = {col: max(len(col), max((len(str(row.get(col, ''))) for row in raw_results), default=0)) for col in columns}
        header = " | ".join([f"{col:{col_widths[col]}}" for col in columns])
        result_lines.append(header)
        result_lines.append("-" * len(header))
        
        for row in raw_results:
            row_data = " | ".join([f"{str(row.get(col, '')):<{col_widths[col]}}" for col in columns])
            result_lines.append(row_data)
    except Exception:
        # 如果格式化出错，回退到简单模式
        header = " | ".join(columns)
        result_lines.append(header)
        for row in raw_results:
            result_lines.append(" | ".join([str(val) for val in row.values()]))

    return "\n".join(result_lines)
