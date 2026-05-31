# Сборка дистрибутива

## 1. .exe (PyInstaller)

На машине **Windows 11** с Python 3.11+:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-build.txt
python packaging/build_exe.py
```

Готовое приложение: `dist\TBot\TBot.exe`. Папка содержит все DLL и можно её
архивировать как «portable» сборку.

## 2. Установочный .exe (Inno Setup)

1. Скачайте [Inno Setup 6+](https://jrsoftware.org/isinfo.php) и установите.
2. После шага 1 выполните:
   ```powershell
   iscc packaging\installer.iss
   ```
3. Получите `dist\TBot-Setup.exe` — это «нормальный» Windows-инсталлятор
   с ярлыками, деинсталлятором и поддержкой обновления.

## 3. Возможные предупреждения SmartScreen

Неподписанный `.exe` Windows SmartScreen может пометить как «неизвестное
приложение». Варианты:
- Подписать exe сертификатом code-signing (рекомендуется для продакшна).
- Пользователь жмёт «Подробнее → Выполнить в любом случае».

## 4. Иконка

Положите `tbot/resources/app.ico` (256×256) — PyInstaller подхватит автоматически.
