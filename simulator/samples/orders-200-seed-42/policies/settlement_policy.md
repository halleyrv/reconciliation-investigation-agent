# Settlement and Cut-off Policy

Each gateway settles one batch per calendar day (cut-off 23:59:59 UTC). A batch nets the day's captured payments minus the refunds it absorbs and the fees of its payments.

Settlement lag: 2 business days

Bank holidays: 2026-10-09, 2026-10-20, 2026-10-28

Each batch is paid out as exactly one bank credit, dated the batch date plus the settlement lag. Business days are Monday to Friday, except the bank holidays listed above.
