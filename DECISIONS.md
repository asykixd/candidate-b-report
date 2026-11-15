# Decisions

The report reconstructs the end of a calendar day from the rows in the provided export. The allocation is an accounting assumption to confirm with the accountant.

## Report date and signed contracts

- Options include filtering by export status, filtering by entry date, or using dates of the underlying events.
- Use the event dates up to and including the report date. Treat the export as the known list of work items and include a contract from its signing date. The work export has no creation date or price history. A payment entered after the fact still counts from its `paid_at` date.
- If the report should show only information recorded by that date, backdated payments and work added or repriced later can change earlier reports. The work export would need change history to apply that policy.

## Payments, refunds, and purpose

- Options include counting queued payments, counting all rows marked paid, or using net cash by `paid_at` and `refunded_at`.
- Count cash from `paid_at`. A refund removes the entire payment from `refunded_at` because the export has no separate refund amount. Queued payments have no cash effect. Use the explicit work ID for assignments and treat the free-text purpose as context. This counts the payment for shooting materials against the work it references.
- If partial refunds exist, the report needs the actual refund amounts. If queued payments are commitments or materials are reimbursed outside the contract, they need a separate measure and the balances may change.

## Contract-level payments without a work ID

- Options include spreading them proportionally across all works, filling accepted works in order, or leaving the entire pool unassigned.
- First credit explicit payments to their work items. Then use the pool for accepted work in acceptance-date order, breaking ties by work ID and stopping at each price. Show the remaining pool as unallocated. Acceptance is the only dated evidence in the export that a work item is ready to be settled.
- If advances should cover planned work or be split proportionally, work-level amounts and the unallocated balance will change. Net cash per contract will stay the same. The allocation is recalculated for the requested date, so new direct payments, cancellations, or refunds can change which work items get the pool.

## Planned and cancelled work

- Options include hiding cancelled rows, treating their listed price as payable, or showing them with their original price and zero due after cancellation.
- Keep every work row for traceability. Treat work as planned until acceptance and include its unpaid part in the active-work balance. Show a separate accepted-work balance to distinguish those amounts. After cancellation, keep the listed price visible and set due to zero. Preserve any payment explicitly tied to a planned or cancelled work and flag money tied to cancellations.
- If a cancellation fee applies, the work balance will be too low until the fee is entered. If linked payments need to be transferred or refunded, the allocation will change once there is an accounting entry for that movement.

## Contract total and overpayments

- Options include deriving the contract total from active work prices or showing the signed amount and the current work total separately.
- Use the signed amount for the contract balance and the item prices for work balances. Show gaps between the two. Remaining amounts stop at zero and excess cash is reported separately. Preserve all linked cash on its referenced work and keep any unused pool visible to reconcile net cash.
- If scope changes also change the contract amount, the signed amount must be updated from the amendment. If excess payments automatically offset other debts, the balance per work will change. Subtracting the displayed unallocated sum from the displayed work balance requires a separate accounting decision.

## Input validation and precision

- Options include skipping questionable rows, guessing their intended value, or stopping and naming the problem.
- Stop on invalid dates or amounts, contradictory status and event dates, duplicate IDs, and broken references. Import UTF-8 CSV with standard quoting and use integer kopecks for all calculations. This prevents an ambiguous row from silently changing reported totals.
- If the export legitimately represents negative adjustments, partial refunds, or additional statuses, the parser will need the corresponding rules before it can report them.
