import random
import paramiko
import asyncio
import json
from telegram import Bot
from datetime import datetime
import os  # <-- Add this line to import the os module

# === Конфигурация ===
CONFIG_FILE = "config.json"

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

config = load_config()
SERVERS = config["SERVERS"]
CPU_THRESHOLD = config["CPU_THRESHOLD"]
MEMORY_THRESHOLD = config["MEMORY_THRESHOLD"]
TELEGRAM_TOKEN = config["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = config["TELEGRAM_CHAT_ID"]
LOG_FILE = config["LOG_FILE"]

async def send_telegram_notification(message):
    """Отправляет уведомление в Telegram."""
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)

def save_metrics_to_log(metrics):
    """Сохраняет метрики в лог-файл."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps({"timestamp": str(datetime.now()), "metrics": metrics}, indent=2) + "\n")

def stop_service(service_name):
    """Останавливает службу."""
    os.system(f"sudo systemctl stop {service_name}")
    print(f"Служба {service_name} остановлена.")

def restart_service(service_name):
    """Перезапускает службу."""
    os.system(f"sudo systemctl restart {service_name}")
    print(f"Служба {service_name} перезапущена.")

async def check_server(server):
    """Проверяет состояние сервера через SSH."""
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=server["hostname"],
            port=22,
            username=server["username"],
            password=server["password"]
        )

        # Проверка загрузки CPU
        stdin, stdout, stderr = client.exec_command("top -bn1 | grep 'Cpu(s)'")
        cpu_line = stdout.read().decode().strip()

        if not cpu_line:
            raise ValueError("Команда 'top' вернула пустой результат.")

        try:
            cpu_usage = 100.0 - float([x for x in cpu_line.split(",") if "id" in x][0].split()[0])
        except (IndexError, ValueError):
            raise ValueError(f"Не удалось разобрать строку CPU: '{cpu_line}'")

        # Проверка использования памяти
        stdin, stdout, stderr = client.exec_command("free | grep Mem")
        mem_info = stdout.read().decode().split()

        if len(mem_info) < 3:
            raise ValueError("Команда 'free' вернула неожиданный результат.")

        memory_usage = round((int(mem_info[2]) / int(mem_info[1])) * 100, 2)

        client.close()
        return {"cpu": cpu_usage, "memory": memory_usage}

    except (paramiko.SSHException, ValueError) as e:
        return {"error": f"Ошибка: {str(e)}"}

async def monitor_servers():
    """Запускает процесс мониторинга всех серверов."""
    while True:
        for server in SERVERS:
            print(f"Проверка сервера: {server['hostname']}")
            result = await check_server(server)

            if "error" in result:
                print(f"Ошибка на сервере {server['hostname']}: {result['error']}")
            else:
                print(f"Результаты сервера {server['hostname']}: CPU {result['cpu']}%, Memory {result['memory']}%")
                save_metrics_to_log(result)

                # Отправка уведомлений и управление службами
                if result.get("cpu", 0) > CPU_THRESHOLD or result.get("memory", 0) > MEMORY_THRESHOLD:
                    message = (
                        f"⚠️ Проблема на сервере {server['hostname']}:\n"
                        f"CPU: {result['cpu']}%, Memory: {result['memory']}%"
                    )
                    await send_telegram_notification(message)

                    if "critical_service" in server and server["critical_service"]:
                        restart_service(server["critical_service"])

        # Ожидание перед следующим запросом
        print("Ожидание 15 секунд перед следующей проверкой...")
        await asyncio.sleep(15)

async def main():
    await monitor_servers()

if __name__ == "__main__":
    asyncio.run(main())

