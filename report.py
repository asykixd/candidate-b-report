from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypeVar


class DataError(ValueError):
    """The export contains an invalid or ambiguous record."""


@dataclass(frozen=True)
class Contract:
    contract_id: str
    contractor: str
    amount: int
    signed_at: date


@dataclass(frozen=True)
class Work:
    work_id: str
    contract_id: str
    title: str
    price: int
    completed_at: date | None
    cancelled_at: date | None

    def status_on(self, as_of: date) -> str:
        if self.cancelled_at and self.cancelled_at <= as_of:
            return "cancelled"
        if self.completed_at and self.completed_at <= as_of:
            return "done"
        return "planned"


@dataclass(frozen=True)
class Payment:
    payment_id: str
    contract_id: str
    work_id: str | None
    amount: int
    paid_at: date | None
    refunded_at: date | None

    def settled_on(self, as_of: date) -> bool:
        return (
            self.paid_at is not None
            and self.paid_at <= as_of
            and (self.refunded_at is None or self.refunded_at > as_of)
        )


@dataclass(frozen=True)
class Ledger:
    contracts: list[Contract]
    works: list[Work]
    payments: list[Payment]


@dataclass(frozen=True)
class WorkBalance:
    work: Work
    status: str
    direct: int
    from_pool: int

    @property
    def paid(self) -> int:
        return self.direct + self.from_pool

    @property
    def due(self) -> int:
        if self.status == "cancelled":
            return 0
        return max(0, self.work.price - self.paid)

    @property
    def overpaid(self) -> int:
        if self.status == "cancelled":
            return 0
        return max(0, self.paid - self.work.price)


@dataclass(frozen=True)
class ContractBalance:
    contract: Contract
    works: list[WorkBalance]
    net_paid: int
    unallocated: int


def read_date(value: str, column: str) -> date:
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise DataError(f"{column}: expected a date in YYYY-MM-DD format") from error
    if result.isoformat() != value:
        raise DataError(f"{column}: expected a date in YYYY-MM-DD format")
    return result


def read_optional_date(value: str, column: str) -> date | None:
    return read_date(value, column) if value else None


def read_money(value: str, column: str) -> int:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", value):
        raise DataError(f"{column}: expected nonnegative rubles with up to two decimal places")
    rubles, _, kopecks = value.partition(".")
    return int(rubles) * 100 + int(kopecks.ljust(2, "0"))


def required(row: dict[str, str], column: str) -> str:
    if not row[column]:
        raise DataError(f"{column}: value is required")
    return row[column]


def parse_contract(row: dict[str, str]) -> Contract:
    return Contract(
        required(row, "contract_id"),
        required(row, "contractor"),
        read_money(row["amount"], "amount"),
        read_date(row["signed_at"], "signed_at"),
    )


def parse_work(row: dict[str, str]) -> Work:
    completed = read_optional_date(row["completed_at"], "completed_at")
    cancelled = read_optional_date(row["cancelled_at"], "cancelled_at")
    status = row["status"]
    expected_status = "cancelled" if cancelled else "done" if completed else "planned"
    if status != expected_status:
        raise DataError(f"status {status!r} does not match completed_at and cancelled_at")
    if completed and cancelled and completed > cancelled:
        raise DataError("completed_at is after cancelled_at")
    return Work(
        required(row, "work_id"),
        required(row, "contract_id"),
        required(row, "title"),
        read_money(row["price"], "price"),
        completed,
        cancelled,
    )


def parse_payment(row: dict[str, str]) -> Payment:
    read_date(row["created_at"], "created_at")
    paid = read_optional_date(row["paid_at"], "paid_at")
    refunded = read_optional_date(row["refunded_at"], "refunded_at")
    status = row["status"]
    expected_status = "refunded" if refunded else "paid" if paid else "queued"
    if status != expected_status:
        raise DataError(f"status {status!r} does not match paid_at and refunded_at")
    if refunded and (paid is None or refunded < paid):
        raise DataError("refunded_at requires a paid_at on or before the refund date")
    return Payment(
        required(row, "payment_id"),
        required(row, "contract_id"),
        row["work_id"] or None,
        read_money(row["amount"], "amount"),
        paid,
        refunded,
    )


Record = TypeVar("Record", Contract, Work, Payment)


def read_table(
    path: Path, columns: str, id_column: str, parse: Callable[[dict[str, str]], Record]
) -> list[Record]:
    expected = set(columns.split())
    seen: set[str] = set()
    records: list[Record] = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream, strict=True)
            headers = reader.fieldnames or []
            if set(headers) != expected or len(headers) != len(expected):
                raise DataError(f"{path.name}: expected columns {columns}")
            for raw in reader:
                location = f"{path.name}:{reader.line_num}"
                if None in raw or any(value is None for value in raw.values()):
                    raise DataError(f"{location}: incorrect number of columns")
                row = {key: value.strip() for key, value in raw.items()}
                try:
                    record = parse(row)
                except DataError as error:
                    raise DataError(f"{location}: {error}") from error
                identifier = row[id_column]
                if identifier in seen:
                    raise DataError(f"{location}: duplicate {id_column} {identifier!r}")
                seen.add(identifier)
                records.append(record)
    except (OSError, UnicodeError, csv.Error) as error:
        raise DataError(f"{path}: {error}") from error
    return records


def load_ledger(data_dir: Path) -> Ledger:
    contracts = read_table(
        data_dir / "contracts.csv", "contract_id contractor amount signed_at", "contract_id", parse_contract
    )
    works = read_table(
        data_dir / "works.csv",
        "work_id contract_id title price status completed_at cancelled_at",
        "work_id",
        parse_work,
    )
    payments = read_table(
        data_dir / "payments.csv",
        "payment_id contract_id work_id purpose amount status created_at paid_at refunded_at",
        "payment_id",
        parse_payment,
    )
    contract_ids = {item.contract_id for item in contracts}
    works_by_id = {item.work_id: item for item in works}
    for work in works:
        if work.contract_id not in contract_ids:
            raise DataError(f"works.csv: {work.work_id}: unknown contract {work.contract_id!r}")
    for payment in payments:
        if payment.contract_id not in contract_ids:
            raise DataError(f"payments.csv: {payment.payment_id}: unknown contract {payment.contract_id!r}")
        if payment.work_id is not None:
            work = works_by_id.get(payment.work_id)
            if work is None or work.contract_id != payment.contract_id:
                raise DataError(
                    f"payments.csv: {payment.payment_id}: work {payment.work_id!r} "
                    f"does not belong to contract {payment.contract_id!r}"
                )
    return Ledger(contracts, works, payments)


def allocate_contract(
    contract: Contract, works: list[Work], payments: list[Payment], as_of: date
) -> ContractBalance:
    direct: Counter[str] = Counter()
    pool = 0
    for payment in payments:
        if payment.settled_on(as_of):
            if payment.work_id is None:
                pool += payment.amount
            else:
                direct[payment.work_id] += payment.amount
    net_paid = pool + sum(direct.values())

    statuses = {work.work_id: work.status_on(as_of) for work in works}
    accepted = (work for work in works if statuses[work.work_id] == "done")
    from_pool: dict[str, int] = {}
    # Preserve explicit assignments even when they exceed the price. Only the
    # unlinked pool is capped and applied in historical acceptance order.
    for work in sorted(accepted, key=lambda item: (item.completed_at or date.max, item.work_id)):
        amount = min(pool, max(0, work.price - direct[work.work_id]))
        from_pool[work.work_id] = amount
        pool -= amount

    balances = [
        WorkBalance(work, statuses[work.work_id], direct[work.work_id], from_pool.get(work.work_id, 0))
        for work in sorted(works, key=lambda item: item.work_id)
    ]
    return ContractBalance(contract, balances, net_paid, pool)


def build_report(ledger: Ledger, as_of: date) -> list[ContractBalance]:
    works: dict[str, list[Work]] = defaultdict(list)
    payments: dict[str, list[Payment]] = defaultdict(list)
    for work in ledger.works:
        works[work.contract_id].append(work)
    for payment in ledger.payments:
        payments[payment.contract_id].append(payment)
    return [
        allocate_contract(contract, works[contract.contract_id], payments[contract.contract_id], as_of)
        for contract in sorted(ledger.contracts, key=lambda item: item.contract_id)
        if contract.signed_at <= as_of
    ]


def rubles(kopecks: int) -> str:
    whole, fraction = divmod(abs(kopecks), 100)
    sign = "−" if kopecks < 0 else ""
    return f"{sign}{whole:,}".replace(",", " ") + f",{fraction:02d}"


def escape_cell(value: str) -> str:
    return " ".join(value.splitlines()).replace("\\", "\\\\").replace("|", "\\|")


def render_contract(balance: ContractBalance) -> list[str]:
    contract = balance.contract
    labels = {"done": "Принята", "planned": "Ожидает приёмки", "cancelled": "Отменена"}
    lines = [f"## {escape_cell(contract.contract_id)} · {escape_cell(contract.contractor)}", ""]
    if balance.works:
        lines += [
            "| Работа | Статус | Цена | Выплачено | Из них напрямую | Осталось оплатить | Переплата |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in balance.works:
            work = row.work
            cells = [
                escape_cell(f"{work.work_id} · {work.title}"),
                labels[row.status],
                rubles(work.price),
                rubles(row.paid),
                rubles(row.direct),
                rubles(row.due),
                rubles(row.overpaid),
            ]
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("В выгрузке нет работ по этому договору.")

    active = [row for row in balance.works if row.status != "cancelled"]
    active_price = sum(row.work.price for row in active)
    due_on_contract = contract.amount - balance.net_paid
    totals = {
        "Сумма договора": contract.amount,
        "Стоимость действующих работ": active_price,
        "Выплачено по договору за вычетом возвратов": balance.net_paid,
        "Из них отражено в строках работ": sum(row.paid for row in balance.works),
        "Нераспределённые платежи": balance.unallocated,
        "Осталось по сумме договора": max(0, due_on_contract),
        "Осталось по действующим работам": sum(row.due for row in active),
        "Из них по уже принятым работам": sum(row.due for row in active if row.status == "done"),
    }
    lines += ["", *(f"- {label} — {rubles(amount)}" for label, amount in totals.items())]
    if contract.amount != active_price:
        difference = rubles(abs(contract.amount - active_price))
        direction = "выше" if contract.amount > active_price else "ниже"
        lines.append(f"- Сумма договора {direction} стоимости действующих работ на {difference}.")
    if due_on_contract < 0:
        lines.append(f"- Выплаты сверх суммы договора — {rubles(-due_on_contract)}.")
    cancelled_paid = sum(row.paid for row in balance.works if row.status == "cancelled")
    if cancelled_paid:
        lines.append(f"- По отменённым работам выплачено {rubles(cancelled_paid)}. Уточните судьбу выплат.")
    return lines


def render_report(balances: Sequence[ContractBalance], as_of: date) -> str:
    lines = [
        f"# Отчёт по оплате на {as_of:%d.%m.%Y}",
        "",
        "Суммы в рублях. Общие платежи зачтены по датам приёмки. "
        "Прямые платежи оставлены за указанными работами.",
    ]
    if not balances:
        lines += ["", "На указанную дату подписанных договоров нет."]
    for balance in balances:
        lines += ["", *render_contract(balance)]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a payment report from the accounting export.")
    parser.add_argument("--as-of", required=True, help="report date, inclusive (YYYY-MM-DD)")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    args = parser.parse_args(argv)
    try:
        as_of = read_date(args.as_of, "--as-of")
        balances = build_report(load_ledger(args.data_dir), as_of)
    except DataError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    print(render_report(balances, as_of))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
