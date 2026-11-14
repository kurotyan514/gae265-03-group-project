"""Gmail 網頁上某封信的連結：寄出的信在寄件備份，草稿用 compose 打開來編輯。

7 號寄出或建立草稿時給畫面連結，平台在理賠頁、送件結果頁重新組連結，都用這裡，網址規則只有一份。
草稿要用「草稿裡那封信的編號」，草稿編號本身打不開。
"""

from typing import Literal
from urllib.parse import quote

GMAIL_WEB = "https://mail.google.com/"


def gmail_url(email: str, kind: Literal["sent", "draft"], message_id: str) -> str:
    """用 authuser 指定帳號：瀏覽器同時登入好幾個 Google 帳號時，才會開在寄件的那個帳號。"""
    account = quote(email, safe="")
    message = quote(message_id, safe="")
    folder = f"sent/{message}" if kind == "sent" else f"drafts?compose={message}"
    return f"{GMAIL_WEB}mail/?authuser={account}#{folder}"


def is_gmail_url(url: str | None) -> bool:
    """只放行 Gmail 網頁的連結，畫面才不會出現連到別處的連結。"""
    return bool(url) and str(url).startswith(GMAIL_WEB)
