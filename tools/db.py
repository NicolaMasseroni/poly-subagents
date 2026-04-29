"""Connessione psycopg2 condivisa per i tool del CEO agent."""

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv()


def get_conn():
    """Restituisce una nuova connessione psycopg2 a TimescaleDB/PostgreSQL."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "192.168.0.250"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "app"),
        user=os.getenv("DB_USER", "app"),
        password=os.getenv("DB_PASSWORD"),
    )
