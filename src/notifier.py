"""
Notifier — sends Email via SMTP (configured through environment variables).

Environment variables expected:
  SMTP_HOST   (default: smtp.gmail.com)
  SMTP_PORT   (default: 587)
  SMTP_USER   sender email address
  SMTP_PASS   app password / API key

All methods are no-ops (log only) when credentials are missing,
so the system degrades gracefully during development / testing.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_RISK_DISCLAIMER = (
    "\n\n⚠️ 風險提示：本通知所有內容僅供資訊整理與研究參考，"
    "不構成投資建議。股票投資有風險，過去績效不代表未來獲利。"
)


class Notifier:

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_pass: Optional[str] = None,
    ):
        self.smtp_host = smtp_host or os.environ.get("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(smtp_port or os.environ.get("SMTP_PORT", 587))
        self.smtp_user = smtp_user or os.environ.get("SMTP_USER", "")
        self.smtp_pass = smtp_pass or os.environ.get("SMTP_PASS", "")
        self._sent: List[Dict] = []   # audit log for testing

    # ── public API ────────────────────────────────────────────────────────────

    def send_trade_alert(self, order: Dict) -> bool:
        """Send real-time trade notification (called on each order)."""
        ticker = order.get("ticker", "?")
        side = order.get("side", "?").upper()
        shares = order.get("shares", 0)
        status = order.get("status", "?")
        acct = order.get("account_id", "")

        subject = f"[Trade Alert] {side} {ticker} {shares} shares — {status}"
        body = (
            f"帳戶: {acct}\n"
            f"動作: {side}\n"
            f"股票: {ticker}\n"
            f"股數: {shares}\n"
            f"狀態: {status}\n"
        )
        if status == "failed":
            body += f"錯誤: {order.get('error', 'unknown')}\n"
        body += _RISK_DISCLAIMER

        return self._send(subject, body)

    def send_daily_report(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        plain_body: str = "",
    ) -> bool:
        """Send the daily 6am report email."""
        return self._send(subject, plain_body or html_body,
                          html_body=html_body, to_email=to_email)

    # ── internals ─────────────────────────────────────────────────────────────

    def _send(
        self,
        subject: str,
        plain: str,
        html_body: str = "",
        to_email: str = "",
    ) -> bool:
        if not self.smtp_user or not self.smtp_pass:
            log.warning("SMTP credentials not set — email not sent: %s", subject)
            self._sent.append({"subject": subject, "sent": False, "reason": "no_credentials"})
            return False

        recipient = to_email or self.smtp_user
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.smtp_user
        msg["To"] = recipient
        msg.attach(MIMEText(plain, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(self.smtp_user, self.smtp_pass)
                smtp.sendmail(self.smtp_user, recipient, msg.as_string())
            log.info("Email sent: %s → %s", subject, recipient)
            self._sent.append({"subject": subject, "to": recipient, "sent": True})
            return True
        except Exception as exc:
            log.error("Failed to send email '%s': %s", subject, exc)
            self._sent.append({"subject": subject, "sent": False, "error": str(exc)})
            return False

    # ── test helpers ──────────────────────────────────────────────────────────

    def sent_subjects(self) -> List[str]:
        return [e["subject"] for e in self._sent]

    def last_sent(self) -> Optional[Dict]:
        return self._sent[-1] if self._sent else None
