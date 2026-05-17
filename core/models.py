from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class TransactionType(StrEnum):
    income = "income"
    expense = "expense"


class AITransaction(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    category: str | None = Field(default=None, min_length=1, max_length=64)
    type: TransactionType | None = None
    raw_text: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("category")
    @classmethod
    def normalize_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized[:64] if normalized else None

    @field_validator("raw_text")
    @classmethod
    def normalize_raw_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized[:256] if normalized else None

    @property
    def is_complete(self) -> bool:
        return self.amount is not None and self.category is not None and self.type is not None


class AITransactionBatch(BaseModel):
    transactions: list[AITransaction] = Field(default_factory=list)

    @classmethod
    def from_payload(cls, payload: object) -> "AITransactionBatch":
        if isinstance(payload, list):
            return cls(transactions=[AITransaction.model_validate(item) for item in payload])

        if isinstance(payload, dict) and "transactions" in payload:
            return cls.model_validate(payload)

        return cls(transactions=[AITransaction.model_validate(payload)])

    @property
    def complete_transactions(self) -> list[AITransaction]:
        return [transaction for transaction in self.transactions if transaction.is_complete]


class Transaction(BaseModel):
    timestamp: datetime
    amount: float = Field(gt=0)
    category: str = Field(min_length=1, max_length=64)
    type: TransactionType
    raw_text: str = Field(min_length=1)

    def to_sheet_row(self) -> list[str | float]:
        return [
            self.timestamp.isoformat(timespec="seconds"),
            self.amount,
            self.category,
            self.type.value,
            self.raw_text,
        ]


class ProcessResult(BaseModel):
    transactions: list[Transaction] = Field(min_length=1)
    categories_created: list[str] = Field(default_factory=list)

    @property
    def transaction(self) -> Transaction:
        return self.transactions[0]

    @property
    def total_amount(self) -> float:
        return sum(transaction.amount for transaction in self.transactions)
