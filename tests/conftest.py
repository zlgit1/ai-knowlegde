"""pytest 配置：加载 .env + 屏蔽警告 + 注册自定义标记"""
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv

# 确保项目根目录在 sys.path 上，使 pipeline 模块可导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

warnings.filterwarnings("ignore", category=Warning, message="unknown register.*mark")


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 标记为慢速测试，需调用 LLM API")
