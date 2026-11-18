# Transaction Reconciliation Policy

Reconciliation compares independent sources record by record: orders from the shop, payments, refunds, fees and settlement batches from the gateway, authorizations from the back office and credits from the bank statement.

- Every order has exactly one captured payment, and the payment amount equals the order total.
- Every refund has an approved authorization that covers its amount.
- Every fee equals the gateway's fee schedule applied to its payment.
- A settlement batch nets its payments minus the refunds it absorbs and the fees of its payments.
- Each batch is paid out as exactly one bank credit for its net amount, dated the batch date plus the settlement lag in business days.

Settlement lag: 2 business days

Amounts are compared exactly in USD cents: there is no tolerance. A record that one source has and another lacks, an amount that differs, or a reference that points to the wrong record is a discrepancy to investigate, not an error to correct automatically.
