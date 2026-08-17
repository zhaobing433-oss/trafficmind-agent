"""
消息推送工具模块
--------------
支持三种推送渠道：企业微信机器人、钉钉机器人、邮件 SMTP。
每个渠道独立异常处理，任一渠道失败不影响其他。
"""

import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from backend.config import (
    WECHAT_WEBHOOK_URL,
    DINGTALK_WEBHOOK_URL,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    SMTP_FROM,
    SMTP_TO,
)
from backend.tools.event_tools import safe_float


def _build_event_summary(result: Dict[str, Any]) -> Dict[str, str]:
    """从分析结果中提取关键字段，组装为推送消息数据。"""
    standard_event = result.get("standardEvent", {})
    return {
        "eventId": result.get("eventId", ""),
        "eventType": standard_event.get("eventTypeCn", ""),
        "roadName": standard_event.get("roadName", ""),
        "direction": standard_event.get("direction", ""),
        "avgSpeed": str(standard_event.get("avgSpeed", "")),
        "queueLength": str(standard_event.get("queueLength", "")),
        "durationMin": str(int(safe_float(standard_event.get("duration"), 0.0) / 60)),
        "riskScore": str(result.get("riskScore", "")),
        "riskLevel": result.get("riskLevel", ""),
        "status": result.get("status", ""),
        "analyzedAt": result.get("analyzedAt", ""),
        "suggestions": "\n".join(
            f"> {s}" for s in result.get("suggestions", [])
        ),
        "dispatchMessage": result.get("dispatchMessage", ""),
        "publicMessage": result.get("publicMessage", ""),
    }


# ==================== 企业微信 ====================


def _format_wechat_markdown(d: Dict[str, str]) -> str:
    """构建企业微信 Markdown 消息体。"""
    lines = [
        f"## 🚨 TrafficMind 交通事件告警",
        f"",
        f"**事件类型**：{d['eventType']}",
        f"**风险等级**：<font color=\"warning\">{d['riskLevel']}</font>（{d['riskScore']}分）",
        f"**事发路段**：{d['roadName']} {d['direction']}",
        f"**平均车速**：{d['avgSpeed']} km/h",
        f"**排队长度**：{d['queueLength']} 米",
        f"**持续时间**：{d['durationMin']} 分钟",
        f"**事件编号**：{d['eventId']}",
        f"**时间**：{d['analyzedAt']}",
        f"",
        f"### 处置建议",
        f"{d['suggestions']}",
        f"",
        f"### 公众提示",
        f">{d['publicMessage']}",
    ]
    return "\n".join(lines)


def send_wechat_work(result: Dict[str, Any]) -> bool:
    """
    通过企业微信机器人 Webhook 推送消息。

    Args:
        result: 完整的分析结果字典

    Returns:
        是否发送成功
    """
    if not WECHAT_WEBHOOK_URL:
        return False

    d = _build_event_summary(result)
    markdown_content = _format_wechat_markdown(d)

    payload = json.dumps(
        {
            "msgtype": "markdown",
            "markdown": {"content": markdown_content},
        },
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        req = Request(
            WECHAT_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urlopen(req, timeout=10)
        print("[Notify] 企业微信推送成功")
        return True
    except URLError as e:
        print(f"[Notify] 企业微信推送失败: {e}")
        return False


# ==================== 钉钉 ====================


def _format_dingtalk_markdown(d: Dict[str, str]) -> Dict[str, str]:
    """构建钉钉 Markdown 消息体。"""
    text = (
        f"## 🚨 TrafficMind 交通事件告警\n\n"
        f"**事件类型**：{d['eventType']}\n\n"
        f"**风险等级**：**{d['riskLevel']}**（{d['riskScore']}分）\n\n"
        f"**事发路段**：{d['roadName']} {d['direction']}\n\n"
        f"**平均车速**：{d['avgSpeed']} km/h\n\n"
        f"**排队长度**：{d['queueLength']} 米\n\n"
        f"**持续时间**：{d['durationMin']} 分钟\n\n"
        f"**事件编号**：{d['eventId']}\n\n"
        f"**时间**：{d['analyzedAt']}\n\n"
        f"---\n\n"
        f"### 处置建议\n\n{d['suggestions']}\n\n"
        f"### 公众提示\n\n> {d['publicMessage']}"
    )
    return {"title": f"TrafficMind - {d['riskLevel']} - {d['eventType']}", "text": text}


def send_dingtalk(result: Dict[str, Any]) -> bool:
    """
    通过钉钉机器人 Webhook 推送消息。

    Args:
        result: 完整的分析结果字典

    Returns:
        是否发送成功
    """
    if not DINGTALK_WEBHOOK_URL:
        return False

    d = _build_event_summary(result)
    md = _format_dingtalk_markdown(d)

    payload = json.dumps(
        {"msgtype": "markdown", "markdown": md},
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        req = Request(
            DINGTALK_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        urlopen(req, timeout=10)
        print("[Notify] 钉钉推送成功")
        return True
    except URLError as e:
        print(f"[Notify] 钉钉推送失败: {e}")
        return False


# ==================== 邮件 ====================


def send_email(result: Dict[str, Any]) -> bool:
    """
    通过 SMTP 发送邮件告警。

    Args:
        result: 完整的分析结果字典

    Returns:
        是否发送成功
    """
    if not (SMTP_HOST and SMTP_TO):
        return False

    d = _build_event_summary(result)
    subject = f"[TrafficMind] {d['riskLevel']} - {d['eventType']} - {d['roadName']}"

    body = (
        f"TrafficMind Agent 自动告警\n"
        f"{'=' * 40}\n\n"
        f"事件编号：{d['eventId']}\n"
        f"事件类型：{d['eventType']}\n"
        f"事发路段：{d['roadName']} {d['direction']}\n"
        f"风险等级：{d['riskLevel']}（{d['riskScore']}分）\n"
        f"处置状态：{d['status']}\n"
        f"分析时间：{d['analyzedAt']}\n\n"
        f"调度指令：\n{d['dispatchMessage']}\n\n"
        f"公众提示：{d['publicMessage']}\n"
    )

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_FROM or SMTP_USER
        msg["To"] = SMTP_TO
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(msg["From"], SMTP_TO, msg.as_string())

        print("[Notify] 邮件发送成功")
        return True
    except Exception as e:
        print(f"[Notify] 邮件发送失败: {e}")
        return False


# ==================== 推送编排 ====================


def notify_high_risk_event(result: Dict[str, Any]) -> Dict[str, bool]:
    """
    向所有已配置的渠道推送高风险事件告警。
    每个渠道独立运行，任一失败不影响其他。

    Args:
        result: 完整的分析结果字典

    Returns:
        {"wechat": True/False, "dingtalk": True/False, "email": True/False}
    """
    results = {
        "wechat": send_wechat_work(result),
        "dingtalk": send_dingtalk(result),
        "email": send_email(result),
    }

    success_count = sum(1 for v in results.values() if v)
    total_configured = sum(
        1 for k in results
        if (
            (k == "wechat" and WECHAT_WEBHOOK_URL)
            or (k == "dingtalk" and DINGTALK_WEBHOOK_URL)
            or (k == "email" and SMTP_HOST and SMTP_TO)
        )
    )

    if total_configured > 0:
        print(f"[Notify] 推送完成: {success_count}/{total_configured} 个渠道成功")

    return results
