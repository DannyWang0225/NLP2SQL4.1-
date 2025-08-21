import json
from typing import List, Dict, Any, Optional
from .llm_service import call_llm_api
from .prompt_templates import (
    REFINE_USER_PROMPT_TEMPLATE,
    TABLE_SELECTION_PROMPT_TEMPLATE,
    SQL_GENERATION_WITH_DEPENDENCIES_PROMPT_TEMPLATE,
    FINAL_SQL_VALIDATION_PROMPT_TEMPLATE,
    SYNTHESIZE_ANSWER_PROMPT_TEMPLATE
)
try:
    from .generate_visualization import generate_chart_option
    from .get_table_schema import get_specific_table_schemas
except ImportError:
    from generate_visualization import generate_chart_option
    from get_table_schema import get_specific_table_schemas


def _translate_sql_for_dialect(sql_query: str, db_type: str) -> str:
    """
    根据目标数据库类型，转换SQL查询中的特定函数。

    Args:
        sql_query (str): 原始SQL查询语句
        db_type (str): 目标数据库类型 (例如, 'sqlite', 'mysql')

    Returns:
        str: 转换后的SQL查询语句
    """
    if db_type.lower() == 'sqlite':
        # 定义常见的非SQLite函数到SQLite函数的映射
        translations = {
            "CURDATE()": "date('now')",
            "NOW()": "datetime('now', 'localtime')",
            "YEAR(CURDATE())": "strftime('%Y', 'now')",
            "DATE_FORMAT(date_column, '%Y-%m')": "strftime('%Y-%m', date_column)", # 示例
        }
        
        # 简单的字符串替换，对于更复杂的场景可能需要正则表达式
        for non_sqlite_func, sqlite_func in translations.items():
            # 使用不区分大小写的替换
            import re
            # 使用正则表达式以不区分大小写的方式替换，并保留原始大小写（如果可能）
            # 这里简化处理，直接替换为小写版本
            sql_query = re.sub(re.escape(non_sqlite_func), sqlite_func, sql_query, flags=re.IGNORECASE)

    # 如果是mysql或其他类型，可以添加相应的转换规则
    # else if db_type.lower() == 'mysql':
    #     ...

    return sql_query


def refine_user_prompt(detailed_schema, natural_language_prompt):
    """
    Refines the user's natural language question into a clearer, more direct question
    suitable for data analysis, based on the database structure.
    
    Args:
        detailed_schema (str): The database table structure information.
        natural_language_prompt (str): The user's natural language question.
        
    Returns:
        str: The refined, more specific question.
    """
    prompt = REFINE_USER_PROMPT_TEMPLATE.format(
        detailed_schema=detailed_schema,
        natural_language_prompt=natural_language_prompt
    )
    refined_question = call_llm_api(prompt)
    return refined_question


def select_relevant_tables(table_names: List[str], user_question: str) -> List[str]:
    """
    Uses the LLM to select relevant tables from a list of table names based on the user's question.
    
    Args:
        table_names (List[str]): A list of all available table names.
        user_question (str): The user's natural language question.
        
    Returns:
        List[str]: A list of table names deemed relevant by the LLM.
    """
    prompt = TABLE_SELECTION_PROMPT_TEMPLATE.format(
        table_names=table_names,
        user_question=user_question
    )
    
    model_output = call_llm_api(prompt, is_json_output=True)
    
    try:
        result_json = json.loads(model_output)
        if "relevant_tables" in result_json and isinstance(result_json["relevant_tables"], list):
            # Filter the results to ensure only valid table names are returned
            valid_tables = [table for table in result_json["relevant_tables"] if table in table_names]
            return valid_tables
        else:
            print(f"Warning: LLM failed to return relevant tables in the expected format. Output: {model_output}")
            return []
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Warning: Error parsing relevant tables list: {e}. LLM Output: {model_output}")
        return []

def generate_sql_with_dependencies(db_config, table_overview, refined_prompt, relevant_tables: List[str], last_error: Optional[str] = None):
    """
    生成具有依赖关系的SQL查询序列，支持查询间数据传递。
    此版本会先智能选择相关表，然后获取详细的表结构，以提高SQL生成质量。
    
    Args:
        db_config (dict): 数据库连接配置
        table_overview (str): 数据库中所有表的概览信息
        refined_prompt (str): 经过用户确认的、精炼后的分析问题
        relevant_tables (List[str]): The list of relevant tables determined by the caller.
        last_error (Optional[str]): 上一次SQL验证失败的原因

    Returns:
        dict: 包含查询计划和依赖关系的完整结构
    """
    # 1. 智能选择相关表
    print("   - 步骤 1/2: 智能分析相关数据表...")
    # This part is now handled in app.py before calling this function.
    # We expect detailed_schema to be passed in directly.
    # relevant_tables = _select_relevant_tables(table_overview, refined_prompt)
    detailed_schema = table_overview # Assuming the pre-filtered schema is passed as table_overview
    
    optimization_info = {}
    if not relevant_tables:
        print("   - 警告: 未能识别出相关表，将使用概览信息继续。")
        detailed_schema = table_overview
        optimization_info = {
            "tables_selected": "N/A (fallback)",
            "optimization_ratio": "0%"
        }
    else:
        try:
            total_tables = len([line for line in table_overview.split('\n') if line.strip().startswith('•')])
            optimization_ratio = f"{len(relevant_tables)}/{total_tables}" if total_tables > 0 else "100%"
            optimization_info = {
                "tables_selected": relevant_tables,
                "optimization_ratio": optimization_ratio
            }
            print(f"   - 识别出 {len(relevant_tables)} 个相关表: {', '.join(relevant_tables)}")
        except Exception:
            # Handle cases where table_overview format is unexpected
            optimization_info = { "tables_selected": relevant_tables, "optimization_ratio": "N/A" }

        # 2. 获取这些表的详细结构
        detailed_schema = get_specific_table_schemas(db_config, relevant_tables)
        if "错误" in detailed_schema:
            print(f"   - 警告: 获取详细表结构失败 ({detailed_schema})，将使用概览信息继续。")
            detailed_schema = table_overview # Fallback to overview

    print("   - 步骤 2/2: 基于详细表结构生成SQL执行计划...")
    
    # 3. 使用详细的表结构来生成SQL
    # 根据数据库类型调整Prompt
    db_type = db_config.get("database_type", "sqlite").lower()
    if db_type == 'sqlite':
        sql_dialect_guidance = "生成的SQL必须遵循 **SQLite** 语法。例如，获取当前年份应使用 `strftime('%Y', 'now')` 而不是 `YEAR(CURDATE())`。"
    elif db_type == 'mysql':
        sql_dialect_guidance = "生成的SQL必须遵循 **MySQL** 语法。例如，获取当前日期可使用 `CURDATE()`。"
    else:
        sql_dialect_guidance = f"生成的SQL必须遵循 **{db_type}** 的语法。"

    error_feedback_prompt = ""
    if last_error:
        error_feedback_prompt = f"""### Last Failure Lesson
The SQL you generated last time failed validation for the following reason:
**{last_error}**
Please analyze this error carefully and ensure it is completely corrected in this generation!
"""

    prompt = SQL_GENERATION_WITH_DEPENDENCIES_PROMPT_TEMPLATE.format(
        sql_dialect_guidance=sql_dialect_guidance,
        error_feedback_prompt=error_feedback_prompt,
        detailed_schema=detailed_schema,
        refined_prompt=refined_prompt
    )
    
    model_output = call_llm_api(prompt, is_json_output=True)
    
    try:
        result_json = json.loads(model_output)
        
        # 验证返回结果的结构
        required_keys = ["execution_plan", "tables_used", "total_steps", "has_dependencies"]
        for key in required_keys:
            if key not in result_json:
                raise ValueError(f"模型返回的JSON缺少 '{key}' 键。")
        
        # 验证execution_plan结构
        if not isinstance(result_json["execution_plan"], list):
            raise ValueError("execution_plan 必须是列表格式")
            
        for i, step in enumerate(result_json["execution_plan"]):
            step_required_keys = ["step", "query_id", "description", "sql", "depends_on", "table_used"]
            for key in step_required_keys:
                if key not in step:
                    raise ValueError(f"执行计划第{i+1}步缺少 '{key}' 键")
            
            # 在这里应用SQL方言转换
            original_sql = step["sql"]
            translated_sql = _translate_sql_for_dialect(original_sql, db_config.get("database_type", "sqlite"))
            step["sql"] = translated_sql
        
        # 附加优化信息
        result_json["optimization_info"] = optimization_info
        
        return result_json
        
    except (json.JSONDecodeError, ValueError) as e:
        return f"错误：解析模型返回的JSON失败。模型原始输出: '{model_output}'. 错误详情: {e}"


def generate_sql_list(db_config, table_overview, refined_prompt, original_user_question):
    """
    为了保持向后兼容，保留原有的函数接口。
    实际调用新的generate_sql_with_dependencies函数。
    """
    # TODO: This function is likely broken after refactoring.
    # The new `generate_sql_with_dependencies` requires `relevant_tables`.
    # This compatibility wrapper does not have access to it.
    # This needs to be fixed if this function is still in use.
    # For now, passing an empty list to avoid crashing.
    relevant_tables = []
    # 调用新的函数获取完整的执行计划
    execution_plan = generate_sql_with_dependencies(db_config, table_overview, refined_prompt, relevant_tables)
    
    if isinstance(execution_plan, str):
        return execution_plan
    
    # 转换为原有格式以保持兼容性
    try:
        sql_queries = []
        tables_used = execution_plan.get("tables_used", [])
        
        for step in execution_plan.get("execution_plan", []):
            sql_queries.append(step.get("sql", ""))
        
        # 同时返回执行计划信息（新增）
        return {
            "sql_queries": sql_queries,
            "tables_used": tables_used,
            "execution_plan": execution_plan  # 新增：完整的执行计划
        }
        
    except Exception as e:
        return f"错误：转换执行计划格式失败: {e}"


def validate_final_sql_result(table_schema, refined_prompt, sql_queries, tables_used, execution_plan=None):
    """
    验证最终SQL结果是否正确，支持依赖关系验证。
    
    Args:
        table_schema (str): 数据库表结构信息
        refined_prompt (str): 精炼后的问题
        original_user_question (str): 用户原始问题
        sql_queries (list): 最终确定的SQL查询列表
        tables_used (list): 最终确定的表名列表
        execution_plan (dict): 执行计划信息（可选）
        
    Returns:
        dict: 包含验证结果的字典
    """
    # 格式化SQL查询和表名用于展示
    formatted_sql_queries = "\n".join([f"{i+1}. {sql}" for i, sql in enumerate(sql_queries)])
    formatted_tables = ", ".join(tables_used)
    
    # 如果有执行计划，添加依赖关系信息
    dependency_info = ""
    if execution_plan and execution_plan.get("has_dependencies"):
        dependency_info = "\n\n### Query Dependencies\n"
        for step in execution_plan.get("execution_plan", []):
            depends_on = step.get("depends_on", [])
            if depends_on:
                dependency_info += f"Step {step['step']}: Depends on {', '.join(depends_on)}\n"
            else:
                dependency_info += f"Step {step['step']}: Independent query\n"
    
    prompt = FINAL_SQL_VALIDATION_PROMPT_TEMPLATE.format(
        table_schema=table_schema,
        refined_prompt=refined_prompt,
        formatted_tables=formatted_tables,
        formatted_sql_queries=formatted_sql_queries,
        dependency_info=dependency_info if dependency_info else "无依赖关系"
    )
    
    validation_result = call_llm_api(prompt, is_json_output=True)
    
    try:
        result_json = json.loads(validation_result)
        
        # 验证返回结果的结构
        if "is_valid" not in result_json:
            raise ValueError("模型返回的JSON缺少 'is_valid' 键。")
        
        return result_json
        
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "is_valid": False,
            "reason": f"解析验证结果失败: {e}"
        }


def synthesize_answer(user_question, execution_results: List[Dict[str, Any]], execution_plan=None):
    """
    根据多份数据结果，并结合自动生成的图表，合成对用户问题的自然语言回答。
    
    Args:
        user_question (str): 用户的原始问题
        execution_results (list): 包含每一步的描述、格式化文本和原始数据的字典列表
        execution_plan (dict): 执行计划信息（可选）
        
    Returns:
        str: 对用户问题的自然语言回答，可能包含一个用于前端渲染的图表JSON代码块。
    """
    # 1. 提取所有格式化后的文本结果，用于构建给大模型的上下文
    formatted_data = "\n\n".join([res.get("formatted_text", "") for res in execution_results if res.get("formatted_text")])
    
    # 2. 从执行结果中提取最适合可视化的原始数据（通常是最后一个有数据的步骤）
    data_for_visualization = None
    for result in reversed(execution_results):
        if result.get("raw_results"):
            data_for_visualization = result.get("raw_results")
            break

    # 3. 调用可视化模块，尝试生成图表配置
    chart_option = None
    if data_for_visualization is not None:
        chart_option = generate_chart_option(data_for_visualization, user_question)

    # 4. 构建查询说明和给大模型的提示
    query_explanations = ""
    if execution_plan and "execution_plan" in execution_plan:
        query_explanations = "\n\n### 查询说明\n"
        for i, step in enumerate(execution_plan["execution_plan"]):
            query_explanations += f"查询{i+1}: {step.get('description', '数据查询')}\n"
    
    chart_info_for_llm = ""
    if chart_option:
        chart_type = chart_option.get("series", [{}])[0].get("type", "chart")
        chart_title = chart_option.get("title", {}).get("text", "Data Analysis Chart")
        chart_info_for_llm = (
            f"\n### Additional Information\n"
            f"In addition to the text summary, the system has automatically generated a {chart_type} titled '{chart_title}'. "
            f"Please interpret the data in your response and naturally guide the user to view this chart."
        )

    prompt = SYNTHESIZE_ANSWER_PROMPT_TEMPLATE.format(
        user_question=user_question,
        query_explanations=query_explanations,
        formatted_data=formatted_data,
        chart_info_for_llm=chart_info_for_llm if chart_info_for_llm else "如果系统生成了图表，请自然地引导用户查看图表以获得更直观的感受。"
    )
    # 5. 调用大模型生成文本部分的回答
    final_answer_text = call_llm_api(prompt)

    # 6. 将文本回答和图表JSON代码块组合成最终输出
    if chart_option:
        # 按照前端约定的格式，将图表配置包裹在带有'chart'键的json代码块中
        chart_json_block = f"```json\n{{ \"chart\": {json.dumps(chart_option, ensure_ascii=False, indent=2)} }}\n```"
        final_answer = f"{final_answer_text}\n\n{chart_json_block}"
    else:
        final_answer = final_answer_text
        
    return final_answer
