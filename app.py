import streamlit as st
import json
import os
import sys
from typing import Dict, Any, List
import pandas as pd

# 添加service目录到路径
service_path = os.path.join(os.path.dirname(__file__), 'service')
if service_path not in sys.path:
    sys.path.append(service_path)

# 导入服务模块
from service.get_table_schema import get_table_overview, get_simplified_schemas_for_tables
from service.generate_sql import select_relevant_tables, refine_user_prompt, generate_sql_with_dependencies, validate_final_sql_result, synthesize_answer
from service.execute_and_format import execute_queries_and_format_with_dependencies
from service.database_service import DatabaseService
from config import DATABASE_CONFIG

# 页面配置
st.set_page_config(
    page_title="NLP-to-SQL Intelligent Query System",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 初始化session state
if 'db_config' not in st.session_state:
    st.session_state.db_config = DATABASE_CONFIG
if 'connected' not in st.session_state:
    st.session_state.connected = False
if 'table_list' not in st.session_state:
    st.session_state.table_list = []
if 'selected_tables' not in st.session_state:
    st.session_state.selected_tables = []
if 'table_overview' not in st.session_state:
    st.session_state.table_overview = ""

def connect_to_database():
    """测试数据库连接并获取表"""
    try:
        db_service = DatabaseService(st.session_state.db_config)
        if db_service.test_connection():
            st.session_state.connected = True
            st.session_state.table_list = db_service.get_table_names()
            st.success(f"✅ Connection successful! Found {len(st.session_state.table_list)} tables.")
        else:
            st.session_state.connected = False
            st.error("❌ Connection failed.")
    except Exception as e:
        st.session_state.connected = False
        st.error(f"❌ Connection failed: {e}")

# 主标题
st.title("🔍 NLP-to-SQL Intelligent Query System")
st.markdown("---")

# 侧边栏 - 数据库配置
with st.sidebar:
    st.header("📊 Database Connection")
    
    db_type = st.selectbox(
        "Database Type",
        options=['sqlite', 'mysql', 'postgresql', 'sqlserver'],
        index=['sqlite', 'mysql', 'postgresql', 'sqlserver'].index(st.session_state.db_config.get("database_type", "sqlite"))
    )
    st.session_state.db_config['database_type'] = db_type

    if db_type == 'sqlite':
        st.session_state.db_config['database_path'] = st.text_input(
            "Database File Path",
            value=st.session_state.db_config.get("database_path", "enterprise_database.db")
        )
    else:
        st.session_state.db_config['host'] = st.text_input("Host", value=st.session_state.db_config.get("host", "localhost"))
        st.session_state.db_config['port'] = st.number_input("Port", value=st.session_state.db_config.get("port", 3306))
        st.session_state.db_config['user'] = st.text_input("User", value=st.session_state.db_config.get("user", ""))
        st.session_state.db_config['password'] = st.text_input("Password", type="password", value=st.session_state.db_config.get("password", ""))
        st.session_state.db_config['database'] = st.text_input("Database", value=st.session_state.db_config.get("database", ""))

    if st.button("� Connect", use_container_width=True):
        connect_to_database()
    
    # 连接状态显示
    if st.session_state.connected:
        st.success("🟢 数据库已连接")
        if st.session_state.table_list:
            st.info(f"📋 发现 {len(st.session_state.table_list)} 个表")
    else:
        st.error("🔴 数据库未连接")

# 主内容区域
if st.session_state.connected:
    # 创建两列布局
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("📋 表选择")
        
        if st.session_state.table_list:
            # 全选/全不选按钮
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("✅ 全选"):
                    st.session_state.selected_tables = st.session_state.table_list.copy()
                    st.rerun()
            with col_b:
                if st.button("❌ 清空"):
                    st.session_state.selected_tables = []
                    st.rerun()
            
            # 表选择
            selected_tables = st.multiselect(
                "选择要查询的表：",
                options=st.session_state.table_list,
                default=st.session_state.selected_tables,
                help="选择您想要查询的表，系统将基于这些表生成SQL"
            )
            st.session_state.selected_tables = selected_tables
            
            if selected_tables:
                st.success(f"✅ 已选择 {len(selected_tables)} 个表")
                
                # 显示选中的表
                with st.expander("📊 查看选中的表", expanded=False):
                    for table in selected_tables:
                        st.write(f"• {table}")
                
                # 获取表结构概览
                # 获取表结构概览
                use_relationship_filter = st.checkbox("只显示有关联的表", True)
                if st.button("🔍 获取表结构概览"):
                    with st.spinner("正在获取表结构信息..."):
                        try:
                            # 获取表结构概览
                            table_overview = get_table_overview(
                                st.session_state.db_config,
                                use_relationship_filter=use_relationship_filter
                            )
                            st.session_state.table_overview = table_overview
                            st.success("✅ 表结构概览获取成功")
                        except Exception as e:
                            st.error(f"❌ 获取表结构失败: {e}")
                
                # 显示表结构概览
                if st.session_state.table_overview:
                    with st.expander("📋 表结构概览", expanded=True):
                        st.code(st.session_state.table_overview, language="sql")
        else:
            st.warning("⚠️ 未找到任何表，请检查数据库连接")
    
    with col2:
        st.subheader("🤖 智能查询")
        
        if st.session_state.selected_tables:
            # 查询输入
            question = st.text_area(
                "请输入您的查询问题：",
                height=100,
                placeholder="例如：查询销售额最高的前10个产品",
                help="用自然语言描述您想要查询的内容"
            )
            
            # 高级选项
            with st.expander("⚙️ 高级选项", expanded=False):
                force_refresh = st.checkbox("🔄 强制刷新缓存", help="重新获取最新的表结构信息")
                max_attempts = st.slider("🔁 最大重试次数", 1, 5, 3)
            
            # 查询按钮
            if st.button("🚀 开始查询", use_container_width=True):
                if question.strip():
                    # 创建结果容器
                    result_container = st.container()
                    
                    with result_container:
                        # 进度显示
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        log_container = st.expander("📋 执行日志", expanded=True)
                        
                        try:
                            with log_container:
                                # 1. 智能选择相关表
                                status_text.text("🧠 正在智能分析相关表...")
                                progress_bar.progress(10)
                                
                                all_table_names = st.session_state.table_list
                                relevant_tables = select_relevant_tables(all_table_names, question)
                                
                                if not relevant_tables:
                                    st.warning("⚠️ 未能自动识别出相关表，将使用所有选中的表。")
                                    relevant_tables = st.session_state.selected_tables
                                
                                st.write(f"✅ 识别出 {len(relevant_tables)} 个相关表: {', '.join(relevant_tables)}")
                                progress_bar.progress(20)

                                # 2. 获取精简的表结构
                                status_text.text("📊 正在获取精简表结构...")
                                simplified_schema = get_simplified_schemas_for_tables(
                                    st.session_state.db_config,
                                    relevant_tables
                                )
                                st.write("✅ 精简表结构获取完成")
                                with st.expander("查看用于生成SQL的精简表结构"):
                                    st.code(simplified_schema, language='sql')
                                progress_bar.progress(30)

                                # 3. 问题精炼
                                status_text.text(" refining question...")
                                refined_prompt = refine_user_prompt(simplified_schema, question)
                                st.write(f"🎯 精炼后的问题: {refined_prompt}")
                                progress_bar.progress(40)
                                
                                # 4. 生成和验证SQL
                                final_execution_plan = None
                                last_error = None
                                
                                for attempt in range(1, max_attempts + 1):
                                    st.write(f"🔄 第 {attempt}/{max_attempts} 轮 SQL生成...")
                                    status_text.text(f"⚙️ 正在生成SQL... (第{attempt}次尝试)")
                                    progress_bar.progress(40 + (attempt * 20))
                                    
                                    # 生成SQL
                                    execution_plan = generate_sql_with_dependencies(
                                        st.session_state.db_config,
                                        simplified_schema, # 使用精简后的schema
                                        refined_prompt,
                                        relevant_tables=relevant_tables,
                                        last_error=last_error
                                    )
                                    
                                    if isinstance(execution_plan, str):
                                        st.error(f"❌ 生成失败: {execution_plan}")
                                        continue
                                    
                                    # 验证SQL
                                    sql_list = [step.get('sql', '') for step in execution_plan.get("execution_plan", [])]
                                    tables_used = execution_plan.get("tables_used", [])
                                    
                                    validation_result = validate_final_sql_result(
                                        simplified_schema, # 使用精简后的schema
                                        refined_prompt,
                                        sql_list,
                                        tables_used,
                                        execution_plan=execution_plan
                                    )
                                    
                                    if validation_result.get("is_valid", False):
                                        st.write("✅ SQL验证通过")
                                        final_execution_plan = execution_plan
                                        break
                                    else:
                                        last_error = validation_result.get("reason", "未知原因")
                                        st.warning(f"⚠️ 验证失败: {last_error}")
                                
                                if not final_execution_plan:
                                    st.error("❌ 无法生成有效的SQL查询")
                                else:
                                    progress_bar.progress(80)
                                    status_text.text("🔄 正在执行查询...")
                                    
                                    # 4. 执行SQL
                                    st.write("🚀 开始执行SQL查询...")
                                    execution_results = execute_queries_and_format_with_dependencies(
                                        st.session_state.db_config,
                                        final_execution_plan
                                    )
                                    
                                    progress_bar.progress(90)
                                    status_text.text("📝 正在生成最终报告...")
                                    
                                    # 5. 生成最终答案
                                    final_answer = synthesize_answer(
                                        question,
                                        execution_results,
                                        execution_plan=final_execution_plan
                                    )
                                    
                                    progress_bar.progress(100)
                                    status_text.text("✅ 查询完成！")
                                    
                                    # 显示结果
                                    st.markdown("---")
                                    st.subheader("📊 查询结果")
                                    
                                    # 显示生成的SQL
                                    with st.expander("🔍 查看生成的SQL", expanded=False):
                                        if final_execution_plan:
                                            for i, step in enumerate(final_execution_plan.get("execution_plan", [])):
                                                st.write(f"**步骤 {i+1}: {step.get('description', 'N/A')}**")
                                                st.code(step.get('sql', 'N/A'), language='sql')
                                    
                                    # 显示最终答案
                                    st.markdown(final_answer)
                                    
                                    # 显示每个步骤的数据结果
                                    for result in execution_results:
                                        if result.get("raw_results"):
                                            st.write(f"**{result.get('description')}**")
                                            df = pd.DataFrame(result["raw_results"])
                                            st.dataframe(df, use_container_width=True)
                                            
                                            # 提供下载选项
                                            csv = df.to_csv(index=False)
                                            st.download_button(
                                                label=f"💾 Download {result.get('description')} as CSV",
                                                data=csv,
                                                file_name=f"query_result_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                                mime="text/csv"
                                            )
                                
                        except Exception as e:
                            st.error(f"❌ 查询过程中发生错误: {e}")
                else:
                    st.warning("⚠️ 请输入查询问题")
        else:
            st.info("👈 请先在左侧选择要查询的表")
else:
    st.info("👈 请先在左侧配置并连接数据库")

# 页脚
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center'>
        <p>🚀 NLP-to-SQL 智能查询系统 | 基于大语言模型的自然语言转SQL工具</p>
    </div>
    """,
    unsafe_allow_html=True
)
