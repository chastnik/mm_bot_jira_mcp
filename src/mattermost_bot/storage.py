"""Безопасное хранение данных пользователей."""

import base64
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2

logger = logging.getLogger(__name__)


class Storage:
    """Класс для работы с базой данных и шифрованием."""

    def __init__(self, db_path: str, encryption_key: Optional[str] = None):
        """Инициализация хранилища.

        Args:
            db_path: Путь к файлу базы данных
            encryption_key: Ключ для шифрования (если None, будет сгенерирован)
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Инициализация шифрования
        if encryption_key:
            key = encryption_key.encode()
        else:
            # Генерируем ключ из файла или создаем новый
            key_file = self.db_path.parent / ".encryption_key"
            if key_file.exists():
                key = key_file.read_bytes()
            else:
                key = Fernet.generate_key()
                key_file.write_bytes(key)
                key_file.chmod(0o600)  # Только для владельца

        # Деривируем ключ для Fernet
        kdf = PBKDF2(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"mattermost_bot_salt",
            iterations=100000,
        )
        key_material = kdf.derive(key[:32] if len(key) >= 32 else key.ljust(32, b"0"))
        self.cipher = Fernet(base64.urlsafe_b64encode(key_material))

        self._init_db()

    def _init_db(self) -> None:
        """Инициализация базы данных."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mm_user_id TEXT NOT NULL UNIQUE,
                    jira_username TEXT,
                    jira_password_encrypted TEXT,
                    confluence_username TEXT,
                    confluence_password_encrypted TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            conn.commit()

    def _encrypt(self, plaintext: str) -> str:
        """Зашифровать текст.

        Args:
            plaintext: Открытый текст

        Returns:
            Зашифрованный текст в base64
        """
        if not plaintext:
            return ""
        return self.cipher.encrypt(plaintext.encode()).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """Расшифровать текст.

        Args:
            ciphertext: Зашифрованный текст в base64

        Returns:
            Расшифрованный текст
        """
        if not ciphertext:
            return ""
        return self.cipher.decrypt(ciphertext.encode()).decode()

    def save_user_credentials(
        self,
        mm_user_id: str,
        jira_username: Optional[str] = None,
        jira_password: Optional[str] = None,
        confluence_username: Optional[str] = None,
        confluence_password: Optional[str] = None,
    ) -> None:
        """Сохранить учетные данные пользователя.

        Args:
            mm_user_id: ID пользователя в Mattermost
            jira_username: Логин Jira
            jira_password: Пароль Jira
            confluence_username: Логин Confluence
            confluence_password: Пароль Confluence
        """
        with sqlite3.connect(self.db_path) as conn:
            # Проверяем, существует ли пользователь
            cursor = conn.execute(
                "SELECT user_id FROM users WHERE mm_user_id = ?", (mm_user_id,)
            )
            existing = cursor.fetchone()

            jira_encrypted = self._encrypt(jira_password) if jira_password else None
            confluence_encrypted = (
                self._encrypt(confluence_password) if confluence_password else None
            )

            if existing:
                # Обновляем существующего пользователя
                update_fields = []
                params = []

                if jira_username is not None:
                    update_fields.append("jira_username = ?")
                    params.append(jira_username)
                if jira_password is not None:
                    update_fields.append("jira_password_encrypted = ?")
                    params.append(jira_encrypted)
                if confluence_username is not None:
                    update_fields.append("confluence_username = ?")
                    params.append(confluence_username)
                if confluence_password is not None:
                    update_fields.append("confluence_password_encrypted = ?")
                    params.append(confluence_encrypted)

                update_fields.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                params.append(mm_user_id)

                conn.execute(
                    f"""
                    UPDATE users
                    SET {', '.join(update_fields)}
                    WHERE mm_user_id = ?
                """,
                    params,
                )
            else:
                # Создаем нового пользователя
                conn.execute(
                    """
                    INSERT INTO users (
                        mm_user_id, jira_username, jira_password_encrypted,
                        confluence_username, confluence_password_encrypted
                    ) VALUES (?, ?, ?, ?, ?)
                """,
                    (
                        mm_user_id,
                        jira_username,
                        jira_encrypted,
                        confluence_username,
                        confluence_encrypted,
                    ),
                )
            conn.commit()
            logger.info(f"Сохранены учетные данные для пользователя {mm_user_id}")

    def get_user_credentials(
        self, mm_user_id: str
    ) -> dict[str, Optional[str]]:
        """Получить учетные данные пользователя.

        Args:
            mm_user_id: ID пользователя в Mattermost

        Returns:
            Словарь с учетными данными:
            - jira_username
            - jira_password
            - confluence_username
            - confluence_password
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT jira_username, jira_password_encrypted,
                       confluence_username, confluence_password_encrypted
                FROM users WHERE mm_user_id = ?
            """,
                (mm_user_id,),
            )
            row = cursor.fetchone()

            if not row:
                return {
                    "jira_username": None,
                    "jira_password": None,
                    "confluence_username": None,
                    "confluence_password": None,
                }

            jira_username, jira_encrypted, confluence_username, confluence_encrypted = (
                row
            )

            return {
                "jira_username": jira_username,
                "jira_password": (
                    self._decrypt(jira_encrypted) if jira_encrypted else None
                ),
                "confluence_username": confluence_username,
                "confluence_password": (
                    self._decrypt(confluence_encrypted) if confluence_encrypted else None
                ),
            }

    def user_exists(self, mm_user_id: str) -> bool:
        """Проверить, существует ли пользователь.

        Args:
            mm_user_id: ID пользователя в Mattermost

        Returns:
            True если пользователь существует
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM users WHERE mm_user_id = ?", (mm_user_id,)
            )
            return cursor.fetchone() is not None

    def has_jira_credentials(self, mm_user_id: str) -> bool:
        """Проверить, есть ли у пользователя учетные данные Jira.

        Args:
            mm_user_id: ID пользователя в Mattermost

        Returns:
            True если есть учетные данные Jira
        """
        creds = self.get_user_credentials(mm_user_id)
        return bool(creds["jira_username"] and creds["jira_password"])

    def has_confluence_credentials(self, mm_user_id: str) -> bool:
        """Проверить, есть ли у пользователя учетные данные Confluence.

        Args:
            mm_user_id: ID пользователя в Mattermost

        Returns:
            True если есть учетные данные Confluence
        """
        creds = self.get_user_credentials(mm_user_id)
        return bool(
            creds["confluence_username"] and creds["confluence_password"]
        )

