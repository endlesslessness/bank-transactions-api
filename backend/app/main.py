"""Точка входа приложения Bank Transactions API."""

from fastapi import FastAPI

app = FastAPI(
    title="Bank Transactions API",
    version="0.1.0",
)
