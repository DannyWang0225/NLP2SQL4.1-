# service/generate_visualization.py
import json
from typing import List, Dict, Any, Optional
from .llm_service import call_llm_api

# --- Chart generation components ---

def _infer_column_types(data: List[Dict[str, Any]]) -> Dict[str, str]:
    """从数据中推断列的类型（数值型、类别型、时间型）。"""
    if not data:
        return {}
    
    types = {}
    sample_row = data[0]
    for col, value in sample_row.items():
        # 优先识别时间/日期相关字段
        if 'date' in col.lower() or 'time' in col.lower():
            types[col] = 'temporal'
        elif isinstance(value, (int, float)) and 'id' not in col.lower():
            types[col] = 'numerical'
        elif isinstance(value, str) or 'id' in col.lower():
            types[col] = 'categorical'
        else:
            types[col] = 'other'
    return types

def _create_bar_chart_option(data: List[Dict[str, Any]], cat_col: str, num_col: str, title: str) -> Dict[str, Any]:
    """生成ECharts柱状图的配置。"""
    try:
        sorted_data = sorted(data, key=lambda x: x[num_col], reverse=True)
    except (TypeError, ValueError):
        sorted_data = data

    if len(sorted_data) > 15:
        sorted_data = sorted_data[:15]
        title += " (Top 15)"

    categories = [row[cat_col] for row in sorted_data]
    values = [row[num_col] for row in sorted_data]
    
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        "xAxis": {
            "type": "category", 
            "data": categories, 
            "axisLabel": {"interval": 0, "rotate": 30}
        },
        "yAxis": {"type": "value"},
        "series": [{"name": num_col, "type": "bar", "data": values, "label": {"show": True, "position": "top"}}],
        "grid": {"containLabel": True, "left": "10%", "right": "10%", "bottom": "15%"}
    }

def _create_line_chart_option(data: List[Dict[str, Any]], cat_col: str, num_col: str, title: str) -> Dict[str, Any]:
    """生成ECharts折线图的配置。"""
    categories = [row[cat_col] for row in data]
    values = [row[num_col] for row in data]
    
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "xAxis": {
            "type": "category", 
            "boundaryGap": False,
            "data": categories
        },
        "yAxis": {"type": "value"},
        "series": [{"name": num_col, "type": "line", "data": values, "smooth": True}]
    }

def _create_pie_chart_option(data: List[Dict[str, Any]], cat_col: str, num_col: str, title: str) -> Dict[str, Any]:
    """生成ECharts饼图的配置。"""
    chart_data = [{"value": row[num_col], "name": row[cat_col]} for row in data]
    
    return {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "item", "formatter": "{a} <br/>{b} : {c} ({d}%)"},
        "legend": {"orient": "vertical", "left": "left"},
        "series": [{
            "name": cat_col,
            "type": "pie",
            "radius": "50%",
            "data": chart_data,
            "emphasis": {
                "itemStyle": {
                    "shadowBlur": 10,
                    "shadowOffsetX": 0,
                    "shadowColor": "rgba(0, 0, 0, 0.5)"
                }
            }
        }]
    }

def generate_chart_option(data_results: List[Dict[str, Any]], user_question: str) -> Optional[Dict[str, Any]]:
    """
    使用LLM分析数据和用户问题，以智能生成一个合适的ECharts图表配置。
    """
    if not data_results or len(data_results) < 2:
        print("数据不足，无法生成图表。")
        return None

    col_types = _infer_column_types(data_results)
    data_sample = data_results[:5] # 只取前5行作为样本

    prompt = f"""### 角色
你是一位顶尖的数据可视化专家。

### 任务
根据用户的提问和查询出的数据，设计最合适的图表配置。你需要决定使用哪种图表类型、图表标题以及使用哪些列作为维度和指标。

### 分析指南
1.  **理解用户意图**:
    *   用户想看**趋势**变化吗？（例如“随时间推移”、“增长情况”） -> **折线图 (line)**
    *   用户想**比较**不同类别的数据吗？（例如“各部门”、“不同产品”） -> **柱状图 (bar)**
    *   用户想看**构成**或**占比**吗？（例如“市场份额”、“用户来源分布”） -> **饼图 (pie)**
2.  **选择合适的列**:
    *   **维度/类别轴 (x_axis_column)**: 通常是文本、日期或ID，如`部门名称`、`日期`。
    *   **指标/数值轴 (y_axis_column)**: 必须是数字，如`销售额`、`员工数量`。
3.  **生成标题**: 创建一个简洁、清晰，能准确概括图表内容的标题。

### 输入信息

#### 1. 用户原始问题
{user_question}

#### 2. 数据列名与推断类型
{json.dumps(col_types, indent=2, ensure_ascii=False)}

#### 3. 数据样本 (前5行)
{json.dumps(data_sample, indent=2, ensure_ascii=False)}

### 输出要求
你必须返回一个JSON对象，包含以下字段：
- `chart_type`: 字符串，从 ["bar", "line", "pie"] 中选择。
- `title`: 字符串，图表的标题。
- `x_axis_column`: 字符串，作为x轴或类别的列名。
- `y_axis_column`: 字符串，作为y轴或数值的列名。

**示例输出**:
```json
{{
  "chart_type": "bar",
  "title": "各部门平均薪资对比",
  "x_axis_column": "department_name",
  "y_axis_column": "average_salary"
}}
```

### 你的图表配置 (JSON格式):
"""
    
    # 调用LLM获取图表配置建议
    llm_output = call_llm_api(prompt, is_json_output=True)
    
    try:
        chart_config = json.loads(llm_output)
        chart_type = chart_config.get("chart_type")
        title = chart_config.get("title", user_question)
        cat_col = chart_config.get("x_axis_column")
        num_col = chart_config.get("y_axis_column")

        # 确保所有必要信息都存在
        if not all([chart_type, title, cat_col, num_col]):
            raise ValueError("LLM返回的配置不完整。")
        
        # 确保列名存在于数据中
        if cat_col not in data_results[0] or num_col not in data_results[0]:
             raise ValueError(f"LLM选择的列 ({cat_col}, {num_col}) 不在数据中。")

        # 根据LLM选择的图表类型，调用相应的创建函数
        if chart_type == 'bar':
            return _create_bar_chart_option(data_results, cat_col, num_col, title)
        elif chart_type == 'line':
            return _create_line_chart_option(data_results, cat_col, num_col, title)
        elif chart_type == 'pie':
            return _create_pie_chart_option(data_results, cat_col, num_col, title)
        else:
            print(f"警告: LLM返回了不支持的图表类型 '{chart_type}'，将默认使用柱状图。")
            return _create_bar_chart_option(data_results, cat_col, num_col, title)

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        print(f"警告: 解析LLM图表配置失败 ({e})，将回退到默认柱状图生成逻辑。")
        # Fallback to a simple logic if LLM fails
        col_types = _infer_column_types(data_results)
        numerical_cols = [col for col, type in col_types.items() if type == 'numerical']
        categorical_cols = [col for col, type in col_types.items() if type == 'categorical']
        if categorical_cols and numerical_cols:
            return _create_bar_chart_option(data_results, categorical_cols[0], numerical_cols[0], user_question)
        return None
