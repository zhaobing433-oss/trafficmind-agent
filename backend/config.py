"""
TrafficMind Agent 配置文件
----------------------
集中管理所有配置项：DeepSeek API、数据库路径、规则库路径等。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录
_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _BACKEND_DIR.parent

# 加载 .env 文件（优先项目根目录，兼容 backend/ 目录）
load_dotenv(_PROJECT_DIR / ".env")
load_dotenv(_BACKEND_DIR / ".env", override=False)  # backend/.env 不覆盖已有值

# -------------------- DeepSeek API 配置 --------------------

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# 是否启用大模型（API Key 存在且非空且非占位值）
LLM_ENABLED = bool(DEEPSEEK_API_KEY and DEEPSEEK_API_KEY != "your_api_key")

# -------------------- 路径配置 --------------------

DB_PATH = str(_BACKEND_DIR / "data" / "trafficmind.db")
RULES_PATH = str(_BACKEND_DIR / "data" / "rules" / "traffic_rules.md")

# -------------------- 风险评分配置 --------------------

# 事件类型基础分数
EVENT_BASE_SCORES = {
    "congestion": 20,
    "accident": 45,
    "illegal_parking": 20,
    "wrong_way": 40,
    "pedestrian_intrusion": 35,
    "signal_fault": 40,
    "vehicle_stopped": 25,
    "construction_block": 30,
}

# 风险等级阈值
RISK_LEVELS = [
    (30, "低风险"),
    (60, "中风险"),
    (80, "高风险"),
    (100, "重大风险"),
]

# 事件状态流转
EVENT_STATUSES = [
    "待研判",
    "待派单",
    "处置中",
    "已处置",
    "待复盘",
    "已归档",
]

# -------------------- 消息推送配置 --------------------

# 企业微信机器人 Webhook
WECHAT_WEBHOOK_URL = os.getenv("WECHAT_WEBHOOK_URL", "")

# 钉钉机器人 Webhook
DINGTALK_WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")

# 邮件 SMTP 配置
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
SMTP_TO = os.getenv("SMTP_TO", "")

# 触发推送的最低风险等级（默认"高风险"及以上）
HIGH_RISK_THRESHOLD = os.getenv("HIGH_RISK_THRESHOLD", "高风险")

# 是否启用消息推送（至少配置一个渠道才启用）
NOTIFY_ENABLED = bool(
    WECHAT_WEBHOOK_URL
    or DINGTALK_WEBHOOK_URL
    or (SMTP_HOST and SMTP_TO)
)
