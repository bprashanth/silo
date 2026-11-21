# Messy NGO workbook benchmark cases

These eight cases test extraction and analysis from realistic, deliberately
messy Indian NGO finance and field-work files. Each case contains a
deterministic `gen.py`, generated inputs under `files/`, an answer manifest in
`case.json`, and an independent `verify.py`.

Run all cases with:

```bash
PY=/home/beeps/src/github.com/bprashanth/musings/tg-bridge/.venv/bin/python
for case in subtotals offset_headers two_tables formulas_no_cache mixed_units big_ledger field_log multi_file; do
  "$PY" "$case/gen.py"
  "$PY" "$case/verify.py"
done
```

## `subtotals`

A monthly expense ledger with monthly subtotal rows, blank separators, and a
grand total.

1. Excluding every monthly subtotal and the grand total row, what was total
   actual expenditure from April through September 2025, in INR?
2. Excluding subtotal and grand-total rows, how much was spent on Jal Jeevan
   Saathi in Maharashtra from April through September 2025, in INR?
3. How many underlying expense transactions (rows with an EXP- transaction ID,
   not subtotal rows) were recorded for Poshan Shakti?
4. After excluding all subtotal and grand-total rows, which district had the
   highest total actual expenditure?
5. What percentage of total underlying expenditure was funded by Azim Premji
   Foundation? Exclude all subtotal and grand-total rows and report the
   percentage to two decimal places.
6. After excluding monthly subtotal and grand-total rows, which programme had
   the highest total actual expenditure?

## `offset_headers`

A wide programme-by-month workbook with three note rows and merged, two-level
quarter/month headers.

1. Using only the programme detail rows (not the PORTFOLIO TOTAL row), what was
   total spend from April through September 2025, in INR? Treat `-`, `–`, and
   blanks as zero.
2. For programme rows whose Lead State is Maharashtra, what was total Q1 FY
   2025–26 spend (April, May, and June), in INR? Treat `-`, `–`, and blanks as
   zero.
3. How many programme detail rows reported spending greater than zero in August
   2025? Treat `-`, `–`, and blanks as zero and exclude PORTFOLIO TOTAL.
4. Which programme had the highest total spend across April through September
   2025? Use programme detail rows only and treat `-`, `–`, and blanks as zero.
5. What percentage of total April–September spend occurred in Q2 FY 2025–26
   (July, August, and September)? Use detail rows only, treat zero markers as
   zero, and report to two decimal places.
6. Which Funding Partner supported the highest combined April–September spend
   across its programme detail rows? Treat zero markers as zero and exclude
   PORTFOLIO TOTAL.

## `two_tables`

One worksheet contains an approved-budget table and a donor-receipts table with
a different schema; a second worksheet contains notes.

1. What is the total approved FY 2025-26 budget in INR across all
   programme-district rows? Do not add the displayed TOTAL APPROVED row.
2. How much donor receipt income in INR was credited for the Jal Jeevan Saathi
   programme?
3. How many distinct Receipt IDs in the donor-receipts table have Donor Type
   exactly `Foreign Grant`?
4. Which donor has the highest total receipt amount when all of that donor's
   receipt rows are combined?
5. What percentage of the total approved budget has been received across all
   donor receipts? Report 100 × total receipts / total approved budget, rounded
   to two decimals, and exclude both displayed total rows.

## `formulas_no_cache`

An invoice register whose line totals, monthly subtotals, and grand total are
live formulas without cached values.

1. What is the total invoice spend in INR? Calculate each invoice line as
   Quantity × Unit Rate, and ignore monthly subtotal and grand total rows.
2. What is the total computed spend in INR for Community Nutrition in Odisha,
   using Quantity × Unit Rate for each invoice line?
3. How many distinct invoice IDs are funded by rows whose Funding Type is
   exactly `Government Scheme`? Count invoice detail rows only.
4. Which district has the highest total computed spend after calculating
   Quantity × Unit Rate for every invoice?
5. What percentage of total computed invoice spend is funded by rows whose
   Funding Type is `Foreign Grant`? Use Quantity × Unit Rate and round to two
   decimals.

## `mixed_units`

A disbursement register with mixed INR units, three date formats, blank
separators, and repeated headers.

1. What is the total disbursed amount? Use INR; L/lakh = 100,000, Cr =
   10,000,000, k = 1,000, and treat blank, `-`, and `NA` amounts as zero.
2. How much was disbursed to Maternal & Child Health from 1 April through 30
   June 2025 inclusive? Dates are YYYY-MM-DD, DD/MM/YYYY (day first), or D Mon
   YYYY. Use the stated INR conversion and missing-value rules.
3. How many Odisha records have a non-zero amount? Treat blank, `-`, and `NA`
   as zero and count records, not distinct amounts.
4. Which donor or scheme has the highest total disbursed amount? Use the stated
   INR conversion and missing-value rules.
5. What percentage of the total disbursed amount went to Karnataka? Return a
   percentage from 0 to 100 and use the stated INR conversion and missing-value
   rules.
6. Which programme received the highest total disbursed amount? Use the stated
   INR conversion and missing-value rules.

## `big_ledger`

A 20,000-row national ledger split between field expenses and salary registers,
plus a cost-centre lookup required to answer the questions.

For every question, normalize cost-centre codes by trimming spaces and matching
case-insensitively to the Cost Centre Lookup, exclude unmapped codes, and include
only Posted field expenses and Paid salary lines after trimming and
case-normalizing status.

1. What is the combined eligible field-expense and salary total in INR?
2. What is the combined eligible amount for Maternal and Child Health in
   Odisha?
3. How many eligible transaction lines map to Barmer district across both
   registers? Count field and payroll lines, not employees.
4. Which programme has the highest combined eligible amount across both
   registers?
5. For Rural Livelihoods, what percentage of its combined eligible amount comes
   from the salary register? Return a percentage from 0 to 100.
6. Which district has the highest combined eligible amount across both
   registers?

## `field_log`

A field-staff beneficiary visit log with inconsistent village case and spacing,
duplicate Visit IDs, blank separators, and mixed INR cells.

For every question, normalize village names by trimming outer whitespace,
collapsing internal whitespace, and comparing case-insensitively; deduplicate
Visit ID by keeping its first spreadsheet occurrence.

1. What is the total number of people reached (women + men + children)?
2. How many women were reached by Health & Nutrition visits in Odisha?
3. How many distinct retained visits took place in Gadchiroli district?
4. Which village reached the most people in total? Report the normalized
   village in title case.
5. What percentage of retained visits require follow-up? Round to two decimal
   places.
6. Treat numeric and ₹/comma-formatted travel cells as INR. What was the total
   travel reimbursement for Water Security visits in Maharashtra?

## `multi_file`

A beneficiary roster CSV and a separately formatted payments workbook joined
on Beneficiary ID.

For every question, include only Paid payments after trimming whitespace and
matching case-insensitively, and exclude payment rows whose Beneficiary ID is
absent from the CSV.

1. Treat numeric and ₹/comma-formatted amounts as INR. What is the total paid
   amount?
2. What total amount was paid to Girls' Education beneficiaries in Odisha?
3. How many distinct beneficiaries received at least one included paid
   payment?
4. Which programme received the highest total paid amount?
5. What percentage of all beneficiaries listed in the CSV received at least
   one included paid payment? Round to two decimal places.
6. What total amount did Azim Premji Foundation pay to beneficiaries whose CSV
   gender is Woman?
