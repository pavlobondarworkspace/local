# Center Pivot Simulator (Flask)

## Описание
Веб-приложение для симуляции работы машины кругового орошения (center-pivot) с интерактивной картой, анимацией и управлением параметрами.

## Быстрый старт локально
1. Установите зависимости:
   ```
   pip install -r requirements.txt
   ```
2. Запустите приложение:
   ```
   flask run
   ```
   или для продакшена:
   ```
   gunicorn app:app
   ```

## Деплой на Render.com
1. Загрузите все файлы проекта в новый репозиторий (или импортируйте на Render).
2. В настройках Render создайте новый Web Service:
   - **Environment**: Python 3.x
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
   - **Instance Type**: Starter (или выше)
   - **Root Directory**: (оставьте пустым, если app.py в корне)
3. Убедитесь, что в проекте есть файлы:
   - `app.py`
   - `requirements.txt`
   - `Procfile`
   - `templates/index.html`

## Структура проекта
```
main/
  app.py
  requirements.txt
  Procfile
  templates/
    index.html
```

## Особенности
- Нет folium/branca — только Flask и чистый JS (Leaflet) для максимальной производительности.
- Все обновления — через AJAX, без перезагрузки страницы.
- Для деплоя не требуется никаких переменных окружения.

---

Если возникнут вопросы — пишите! 