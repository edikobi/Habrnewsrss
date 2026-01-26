import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import List, Optional

from app.config import settings
from app.database import ContentItem, User

logger = logging.getLogger(__name__)

DIGEST_SUBJECT = "Ежедневная подборка образовательного контента"

def format_digest_html(user: User, items: List[ContentItem]) -> tuple[str, str]:
    """Format digest content as HTML and plaintext."""
    html_header = f"<h2>Здравствуйте, {user.username}!</h2><p>Ваша подборка на сегодня:</p><ul>"
    html_items = ""
    plain_items = f"Здравствуйте, {user.username}!\n\nВаша подборка на сегодня:\n\n"
    
    for item in items:
        html_items += f"<li><strong>{item.title}</strong> ({item.platform})<br>{item.description[:200]}...<br><a href='{item.url}'>Перейти к материалу</a></li><br>"
        plain_items += f"- {item.title} ({item.platform})\n  {item.url}\n\n"
        
    html_content = html_header + html_items + "</ul>"
    return html_content, plain_items

class EmailSender:
    """SMTP email service for sending user digests and notifications."""
    
    smtp_host: str = settings.smtp_host
    smtp_port: int = settings.smtp_port
    smtp_username: str = settings.smtp_username
    smtp_password: str = settings.smtp_password
    smtp_from: str = settings.smtp_from_email
    use_tls: bool = settings.smtp_use_tls

    def __init__(self):
        self._connection: Optional[smtplib.SMTP] = None

    def send_digest(self, user: User, items: List[ContentItem], email_override: Optional[str] = None) -> bool:
        """Send daily digest email to user with recommended content items."""
        if not items:
            return False

        missing = []
        if not self.smtp_host:
            missing.append('SMTP_HOST')
        if not self.smtp_port:
            missing.append('SMTP_PORT')
        if not self.smtp_from:
            missing.append('SMTP_FROM_EMAIL')

        if missing:
            import os
            try:
                env_exists = os.path.exists('.env')
                env_path = os.path.abspath('.env')

                error_msg = (
                    f"SMTP configuration incomplete. Missing environment variables: {', '.join(missing)}\n"
                    f"Required variables to set:\n"
                    f"- SMTP_HOST: SMTP server hostname (e.g., 'smtp.gmail.com')\n"
                    f"- SMTP_PORT: SMTP port (e.g., 587 for TLS)\n"
                    f"- SMTP_FROM_EMAIL: Sender email address\n"
                    f"- SMTP_USERNAME: Your email login (if authentication required)\n"
                    f"- SMTP_PASSWORD: Your email password or app password\n"
                    f"\nFor Gmail, create an app password: https://support.google.com/accounts/answer/185833\n"
                )

                if not env_exists:
                    error_msg += f"\nACTION REQUIRED: .env file not found. Please copy '.env.example' to '.env' in the project root and fill in the values."
                else:
                    error_msg += f"\nACTION REQUIRED: Please add the missing variables to your existing .env file at: {env_path}"

                logger.error(error_msg)
            except Exception:
                # Fallback to basic error if file system check fails
                logger.error(f"SMTP configuration incomplete. Missing: {', '.join(missing)}")

            return False

        recipient_email = email_override or (user.settings.email_digest if user.settings else None) or user.email

        try:
            message = self._create_digest_message(user, items, recipient_email)
            if self._connect():
                self._connection.send_message(message)
                self._disconnect()
                return True
            return False
        except smtplib.SMTPException as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def _connect(self) -> bool:
        """Establish SMTP connection."""
        try:
            self._connection = smtplib.SMTP(self.smtp_host, self.smtp_port)
            if self.use_tls:
                self._connection.starttls()
            if self.smtp_username:
                self._connection.login(self.smtp_username, self.smtp_password)
            return True
        except smtplib.SMTPException as e:
            logger.error(f"SMTP connection error: {e}")
            return False

    def _disconnect(self) -> None:
        """Close SMTP connection."""
        if self._connection:
            try:
                self._connection.quit()
            except:
                pass
            self._connection = None

    def _create_digest_message(self, user: User, items: List[ContentItem], recipient_email: Optional[str] = None) -> MIMEMultipart:
        """Create multipart email message."""
        message = MIMEMultipart("alternative")
        message["Subject"] = DIGEST_SUBJECT
        message["From"] = self.smtp_from
        message["To"] = recipient_email or user.email

        html_body, plain_body = format_digest_html(user, items)
        message.attach(MIMEText(plain_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

        return message
