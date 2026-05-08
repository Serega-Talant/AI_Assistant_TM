FROM python:3.11-slim

WORKDIR /app

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем только исходный код — .env НЕ копируется в образ.
# Секреты передаются через переменные окружения в docker-compose.yml.
COPY *.py .

# Копируем папку с документами
COPY data ./data

# vector_db и sessions создаются через тома при запуске

EXPOSE 8501

CMD ["streamlit", "run", "app_streamlit.py", "--server.port=8501", "--server.address=0.0.0.0"]
