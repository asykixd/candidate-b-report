from __future__ import annotations

import csv
import io
import shutil
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from report import Contract, DataError, Ledger, Payment, Work, build_report, load_ledger, main, read_money

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORT_DAY = date(2026, 11, 10)


class AccountingReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = load_ledger(DATA_DIR)

    def test_reference_report_reconciles_contracts_and_works(self) -> None:
        first, second = build_report(self.ledger, REPORT_DAY)
        expected = (
            (first, 31_500_000, 1_500_000, 28_500_000, 20_000_000),
            (second, 7_500_000, 2_500_000, 1_500_000, 4_000_000),
        )
        for balance, net, unallocated, contract_due, work_due in expected:
            with self.subTest(contract=balance.contract.contract_id):
                self.assertEqual(balance.net_paid, net)
                self.assertEqual(balance.unallocated, unallocated)
                self.assertEqual(sum(row.paid for row in balance.works) + unallocated, net)
                self.assertEqual(balance.contract.amount - net, contract_due)
                self.assertEqual(sum(row.due for row in balance.works), work_due)

        direct = next(row for row in first.works if row.work.work_id == "W-14")
        self.assertEqual((direct.direct, direct.from_pool, direct.due), (1_500_000, 8_500_000, 0))
        cancelled = next(row for row in first.works if row.work.work_id == "W-13")
        self.assertEqual((cancelled.status, cancelled.paid, cancelled.due), ("cancelled", 0, 0))
        self.assertEqual((second.works[-1].status, second.works[-1].paid), ("planned", 0))

    def test_contract_signing_payment_and_refund_are_inclusive(self) -> None:
        before_signing = build_report(self.ledger, date(2026, 8, 24))
        just_signed = build_report(self.ledger, date(2026, 8, 25))
        advance_paid = build_report(self.ledger, date(2026, 9, 1))
        before_refund = build_report(self.ledger, date(2026, 9, 9))
        on_refund = build_report(self.ledger, date(2026, 9, 10))
        self.assertEqual(before_signing, [])
        self.assertEqual(just_signed[0].net_paid, 0)
        self.assertEqual(advance_paid[0].net_paid, 30_000_000)
        self.assertEqual(before_refund[0].net_paid, 35_000_000)
        self.assertEqual(on_refund[0].net_paid, 30_000_000)

    def test_acceptance_cancellation_and_later_payment_are_inclusive(self) -> None:
        before = build_report(self.ledger, date(2026, 10, 11))[0]
        after = build_report(self.ledger, date(2026, 10, 12))[0]
        self.assertEqual((before.works[2].status, after.works[2].status), ("planned", "cancelled"))
        accepted = build_report(self.ledger, date(2026, 11, 11))[1]
        self.assertEqual(accepted.works[-1].status, "done")
        self.assertEqual(accepted.works[-1].paid, 2_500_000)
        self.assertEqual(accepted.unallocated, 0)
        paid = build_report(self.ledger, date(2026, 11, 12))[1]
        self.assertEqual(paid.net_paid, 9_500_000)
        self.assertEqual(paid.unallocated, 500_000)

    def test_pool_fills_earliest_acceptances_after_direct_payments(self) -> None:
        older_day = date(2026, 11, 9)
        ledger = Ledger(
            [Contract("D", "A", 302, older_day)],
            [
                Work("A", "D", "Latest", 100, REPORT_DAY, None),
                Work("C", "D", "Same date, later ID", 100, older_day, None),
                Work("B", "D", "First", 100, older_day, None),
            ],
            [Payment("P1", "D", None, 101, REPORT_DAY, None), Payment("P2", "D", "B", 1, REPORT_DAY, None)],
        )
        balance = build_report(ledger, REPORT_DAY)[0]
        self.assertEqual(
            [(w.work.work_id, w.from_pool) for w in balance.works], [("A", 0), ("B", 99), ("C", 2)]
        )

    def test_direct_payments_on_planned_cancelled_and_overpaid_works_are_preserved(self) -> None:
        ledger = Ledger(
            [Contract("D", "A", 240, REPORT_DAY)],
            [
                Work("A", "D", "Accepted", 100, REPORT_DAY, None),
                Work("B", "D", "Planned", 100, None, None),
                Work("C", "D", "Cancelled", 100, None, REPORT_DAY),
            ],
            [
                Payment("P1", "D", "A", 120, REPORT_DAY, None),
                Payment("P2", "D", "B", 60, REPORT_DAY, None),
                Payment("P3", "D", "C", 40, REPORT_DAY, None),
                Payment("P4", "D", None, 30, REPORT_DAY, None),
            ],
        )
        balance = build_report(ledger, REPORT_DAY)[0]
        self.assertEqual(
            [(w.paid, w.due, w.overpaid) for w in balance.works], [(120, 0, 20), (60, 40, 0), (40, 0, 0)]
        )
        self.assertEqual((balance.net_paid, balance.unallocated), (250, 30))

    def test_money_is_exact_and_excess_precision_is_refused(self) -> None:
        self.assertEqual(read_money("10000000000000000.01", "amount"), 1_000_000_000_000_000_001)
        self.assertEqual(read_money("0.1", "amount") + read_money("0.2", "amount"), 30)
        for value in ("1.001", "-2.00", "NaN", "1e2"):
            with self.subTest(value=value), self.assertRaises(DataError):
                read_money(value, "amount")

    def test_rejects_payment_linked_to_another_contract(self) -> None:
        with TemporaryDirectory() as folder:
            copy = Path(folder)
            for path in DATA_DIR.glob("*.csv"):
                shutil.copyfile(path, copy / path.name)
            payment_path = copy / "payments.csv"
            with payment_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.reader(stream))
            rows[-1][2] = "W-11"
            with payment_path.open("w", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerows(rows)
            with self.assertRaisesRegex(DataError, "P-8: работа 'W-11' не относится к договору"):
                load_ledger(copy)

    def test_cli_renders_report_and_handles_invalid_input(self) -> None:
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(["--as-of", "2026-11-10"]), 0)
        output = stdout.getvalue()
        self.assertIn("# Отчёт по оплате на 10.11.2026", output)
        self.assertIn("100 000,00", output)
        self.assertIn("Нераспределённые платежи — 25 000,00", output)
        with redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(main(["--as-of", "2026-02-30"]), 2)
        self.assertIn("Ошибка: --as-of: укажите дату в формате ГГГГ-ММ-ДД", stderr.getvalue())
