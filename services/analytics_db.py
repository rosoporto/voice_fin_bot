from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.models import Transaction, TransactionType


class _Base(DeclarativeBase):
    pass


class _TransactionRecord(_Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[str]
    amount: Mapped[float]
    category: Mapped[str]
    type: Mapped[str]
    raw_text: Mapped[str]


class SQLiteAnalyticsService:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        self._sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine, expire_on_commit=False
        )

    async def init_db(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(_Base.metadata.create_all)

    async def save_transactions(self, transactions: list[Transaction]) -> None:
        if not transactions:
            return
        records = [
            _TransactionRecord(
                timestamp=t.timestamp.isoformat(),
                amount=t.amount,
                category=t.category,
                type=t.type.value,
                raw_text=t.raw_text,
            )
            for t in transactions
        ]
        async with self._sessions() as session:
            session.add_all(records)
            await session.commit()

    async def get_category_stats(
        self, transaction_type: TransactionType = TransactionType.expense
    ) -> list[tuple[str, float]]:
        async with self._sessions() as session:
            result = await session.execute(
                select(_TransactionRecord.category, func.sum(_TransactionRecord.amount))
                .where(_TransactionRecord.type == transaction_type.value)
                .group_by(_TransactionRecord.category)
                .order_by(func.sum(_TransactionRecord.amount).desc())
            )
            return [(row[0], float(row[1])) for row in result.all()]

    async def get_totals(self) -> dict[str, float]:
        async with self._sessions() as session:
            result = await session.execute(
                select(_TransactionRecord.type, func.sum(_TransactionRecord.amount))
                .group_by(_TransactionRecord.type)
            )
            totals = {t.value: 0.0 for t in TransactionType}
            for row in result.all():
                totals[row[0]] = float(row[1])
            return totals

    async def clear(self) -> None:
        async with self._sessions() as session:
            await session.execute(delete(_TransactionRecord))
            await session.commit()
