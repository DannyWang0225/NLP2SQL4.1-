# -*- coding: utf-8 -*-
import os

# LLM (Large Language Model) aiconfig
LLM_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

# Database config
# support 'sqlite', 'mysql', 'postgresql'
DATABASE_CONFIG = {
    'database_type': 'sqlite',
    'database_path': 'enterprise_database.db'
}

# enterprise_database.db
# sales_database.db
# inventory.db
