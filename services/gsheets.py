import asyncio
from collections.abc import Callable
from typing import TypeVar

import gspread
import gspread.exceptions
from google.oauth2.service_account import Credentials
from gspread import Spreadsheet, Worksheet
from gspread.exceptions import WorksheetNotFound

from core.models import Transaction

T = TypeVar("T")

TRANSACTION_HEADERS = ["timestamp", "amount", "category", "type", "raw_text"]
CATEGORY_HEADERS = ["category_name"]


class GSheetsService:
    def __init__(
        self,
        service_account_file: str,
        spreadsheet_id: str,
        transactions_sheet: str,
        categories_sheet: str,
    ) -> None:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        credentials = Credentials.from_service_account_file(service_account_file, scopes=scopes)
        self.client = gspread.Client(auth=credentials)  # fix #8: authorize() deprecated
        self.spreadsheet_id = spreadsheet_id
        self.transactions_sheet = transactions_sheet
        self.categories_sheet = categories_sheet
        self._spreadsheet: Spreadsheet | None = None

    async def ensure_schema(self) -> None:
        transactions = await self._worksheet(self.transactions_sheet, rows=1000, cols=5)
        categories = await self._worksheet(self.categories_sheet, rows=1000, cols=1)
        await self._ensure_headers(transactions, TRANSACTION_HEADERS)
        await self._ensure_headers(categories, CATEGORY_HEADERS)

    async def get_categories(self) -> set[str]:
        worksheet = await self._worksheet(self.categories_sheet, rows=1000, cols=1)
        values = await self._run(worksheet.col_values, 1)
        return {value.strip() for value in values[1:] if value.strip()}

    async def add_category(self, category: str) -> None:
        # fix #6: removed redundant get_categories() call — caller already deduplicates
        worksheet = await self._worksheet(self.categories_sheet, rows=1000, cols=1)
        await self._run(worksheet.append_row, [category], value_input_option="USER_ENTERED")

    async def append_transactions(self, transactions: list[Transaction]) -> None:
        if not transactions:
            return
        worksheet = await self._worksheet(self.transactions_sheet, rows=1000, cols=5)
        await self._run(
            worksheet.append_rows,
            [transaction.to_sheet_row() for transaction in transactions],
            value_input_option="USER_ENTERED",
        )

    async def clear_all(self) -> None:
        # fix #1: clear categories first — if it fails, transactions are still intact
        categories = await self._worksheet(self.categories_sheet, rows=1000, cols=1)
        transactions = await self._worksheet(self.transactions_sheet, rows=1000, cols=5)
        await self._clear_and_restore_headers(categories, CATEGORY_HEADERS)
        await self._clear_and_restore_headers(transactions, TRANSACTION_HEADERS)

    async def _spreadsheet_client(self) -> Spreadsheet:
        if self._spreadsheet is None:
            self._spreadsheet = await self._run(self.client.open_by_key, self.spreadsheet_id)
        return self._spreadsheet

    async def _worksheet(self, title: str, rows: int, cols: int) -> Worksheet:
        spreadsheet = await self._spreadsheet_client()
        try:
            return await self._run(spreadsheet.worksheet, title)
        except WorksheetNotFound:
            return await self._run(spreadsheet.add_worksheet, title=title, rows=rows, cols=cols)

    async def _ensure_headers(self, worksheet: Worksheet, headers: list[str]) -> None:
        current_headers = await self._run(worksheet.row_values, 1)
        if current_headers[: len(headers)] != headers:
            await self._run(
                worksheet.update,
                range_name="A1",
                values=[headers],
                value_input_option="USER_ENTERED",
            )

    async def _clear_and_restore_headers(self, worksheet: Worksheet, headers: list[str]) -> None:
        await self._run(worksheet.clear)
        await self._run(
            worksheet.update,
            range_name="A1",
            values=[headers],
            value_input_option="USER_ENTERED",
        )

    @staticmethod
    async def _run(func: Callable[..., T], *args: object, **kwargs: object) -> T:
        # fix #5: retry on transient Google API errors (429, 5xx)
        last_exc: Exception = RuntimeError("unreachable")
        delay = 1.0
        for attempt in range(3):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except gspread.exceptions.APIError as exc:
                status = exc.response.status_code
                if status != 429 and status < 500:
                    raise
                last_exc = exc
            if attempt < 2:
                await asyncio.sleep(delay)
                delay *= 2
        raise last_exc
