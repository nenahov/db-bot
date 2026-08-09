from cryptography.fernet import Fernet, InvalidToken


class PasswordCipher:
    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, password: str) -> str:
        return self._fernet.encrypt(password.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Не удалось расшифровать пароль подключения") from exc
