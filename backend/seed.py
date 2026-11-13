"""Заполняет БД 5 случайными пользователями. Запуск:
    python -m backend.seed
"""
import random
import sqlite3

import bcrypt

from backend.db import get_connection, init_db

NAMES = [
    "айгуль", "булат", "вильдан", "гузель", "динияр",
    "elena", "farit", "gulnara", "ildar", "yulia",
    "карина", "марат", "нурлан", "ольга", "радик",
    "sveta", "тимур", "ульяна", "фанур", "шамиль",
]

CITIES = ["Уфа", "Стерлитамак", "Салават", "Нефтекамск", "Октябрьский", "Туймазы"]

SCHOOLS = [
    "МБОУ СОШ № 1",
    "МБОУ СОШ № 5",
    "МБОУ Лицей № 2",
    "МБОУ Гимназия № 3",
    "МБОУ СОШ № 17",
    "МБОУ Башкирская гимназия",
]

GRADES = ["5А", "5Б", "6А", "6Б", "7А", "7Б", "8А", "8Б", "9А", "10А", "11А"]


def random_password() -> str:
    return "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=12))


def seed(count: int = 5) -> None:
    init_db()
    conn = get_connection()
    added = 0
    try:
        for _ in range(count):
            base = random.choice(NAMES)
            username = f"{base}_{random.randint(100, 999)}"
            password = random_password()
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

            level = random.randint(1, 10)
            points = level * random.randint(50, 200) + random.randint(0, 100)

            city = random.choice(CITIES)
            school = random.choice(SCHOOLS)
            grade = random.choice(GRADES)

            try:
                conn.execute(
                    "INSERT INTO users "
                    "(username, password_hash, level, points, city, school, grade) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (username, pw_hash, level, points, city, school, grade),
                )
                added += 1
            except sqlite3.IntegrityError:
                # ник занят — пропускаем
                continue
        conn.commit()
    finally:
        conn.close()
    print(f"Добавлено пользователей: {added}")


if __name__ == "__main__":
    seed(5)