# Data specification

This document defines the two input tables every partner prepares, and the cleaning and sample rules the pipeline applies to them. It describes what the code in `tasks/` does. Where the coordinators plan to change a rule, the planned change is listed under [Open points](#open-points) with a link to its issue.

## Input tables

Each partner prepares two tables, in CSV or Stata `.dta`, and places them in `tasks/raw_data/`. File names and extensions are set in `tasks/config/config.yaml`.

### Firm-to-firm transactions

One row per seller, buyer and year.

| Field | Description | Type | Preparation before the run |
|---|---|---|---|
| `year` | Calendar year of the sales | Integer | Aggregate monthly or quarterly records to calendar years. |
| `vat_i` | VAT ID of the seller | Number or string | Can be anonymised, but must match `vat` in the firm table. |
| `vat_j` | VAT ID of the buyer | Number or string | Same as `vat_i`. |
| `sales_ij` | Value of sales from seller to buyer in the year, in euro, excluding VAT | Float | Drop observations below the national reporting threshold, so that the threshold does not bias the distributions. |

### Firm level data

One row per firm and year.

| Field | Description | Type | Preparation before the run |
|---|---|---|---|
| `year` | Calendar year | Integer | Annualise to calendar years if the fiscal year differs. |
| `vat` | VAT ID of the firm | Number or string | Same identifier as in the transaction table. The VAT ID is the unit of the firm. Ignore VAT units and ownership links. |
| `nace` | NACE Rev. 2 code, 4 digits or more | Integer or string | Map other classifications to NACE Rev. 2 and keep the crosswalk. If a firm reports several codes in a year, keep the main activity (largest share of sales). |
| `turnover` | Turnover in euro (code 70 in Belgian annual accounts) | Float | Annualise to calendar years if the fiscal year differs. |
| `inputs_total` | Total material and services inputs in euro (codes 60 and 61 in Belgian annual accounts) | Float | Same as `turnover`. |

Each partner documents which national account codes it uses for `turnover` and `inputs_total`.

## What the pipeline does

Task 2 (`tasks/task2_clean_data/`) applies the following rules, in this order.

1. **Zero values:** drops transactions with `sales_ij` equal to zero and firm-years with `turnover` equal to zero.
2. **Giant component:** per year, keeps only the transactions within the largest weakly connected component of the network.
3. **NACE codes:** truncates codes longer than four digits to four digits, and assigns each firm to one of six broad industries from its 2-digit code.
4. **Merge:** attaches firm data to every seller and buyer in the transaction table. Firms that appear in the network but have no firm data stay in the sample, with missing `turnover` and `inputs_total` before step 5.
5. **Turnover:** replaces missing turnover by the firm's network sales, and sets turnover to network sales where network sales exceed reported turnover. Sales to final demand are turnover minus network sales.
6. **Inputs:** replaces missing or non-positive inputs by the firm's network purchases, and sets inputs to network purchases where network purchases exceed reported inputs.
7. **Final demand for inverses:** where turnover equals network sales, adds 1 euro to turnover when computing technical coefficients, so that the input-output inverses converge.

Capital goods are not separated from intermediate inputs. Panel gaps are not filled.

## Open points

These rules are planned or under discussion, and the code does not apply them yet. Each has an issue.

- Remove duplicate observations in both tables ([#12](https://github.com/glennmagerman/ChaMP-multicountry-b2b/issues/12)).
- Drop the financial sector, NACE 64 to 66 ([#13](https://github.com/glennmagerman/ChaMP-multicountry-b2b/issues/13)). Banks file annual accounts but do not charge VAT on most of their sales, so the sector's network is incomplete.
- Decide how to treat network firms without annual accounts ([#14](https://github.com/glennmagerman/ChaMP-multicountry-b2b/issues/14)). Step 5 sets their turnover to network sales, so they sell all their output to other firms by construction, which places them far upstream.
- Impose positive value added (turnover above inputs), or flag firms that violate it ([#15](https://github.com/glennmagerman/ChaMP-multicountry-b2b/issues/15)).
- Read NACE codes reported at the 2-digit level only correctly ([#16](https://github.com/glennmagerman/ChaMP-multicountry-b2b/issues/16)). Step 3 currently turns them into NACE 00.
