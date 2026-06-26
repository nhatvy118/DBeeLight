# Chart / Visualization Test Prompts — E-Commerce Database

> **Schema in scope:** `customers`, `categories`, `products`, `suppliers`,
> `product_suppliers`, `orders`, `order_items`, `reviews`
> Each prompt asks the agent to query the DB and render a chart from the result.

---

## PART 1 — BAR CHART

**BAR01.** Show a bar chart of total revenue by product category.

**BAR02.** Show a bar chart comparing total number of orders per region (North, South, East, West).

**BAR03.** Show a horizontal bar chart ranking all salespersons by total revenue, sorted descending.

**BAR04.** Show a grouped bar chart comparing total revenue vs total profit side by side for each product category.

**BAR05.** Show a stacked bar chart of order count by status (pending, paid, shipped, cancelled), broken down by category.

**BAR06.** Show a bar chart of the top 10 best-selling products by total quantity sold.

**BAR07.** Show a bar chart of the number of reviews per product, only for products with at least 1 review.

---

## PART 2 — LINE CHART

**LINE01.** Show a line chart of total revenue per month across all of 2026.

**LINE02.** Show a line chart of total number of orders per month in 2026.

**LINE03.** Show a multi-line chart comparing monthly revenue across the 3 product categories (Electronics, Desktops, Computers) on the same chart.

**LINE04.** Show a line chart of cumulative revenue (running total) from January to December 2025.

**LINE05.** Show a line chart of month-over-month revenue growth rate (%) for 2025.

**LINE06.** Show a line chart of average order value per month in 2025.

---

## PART 3 — PIE / DONUT CHART

**PIE01.** Show a pie chart of revenue share by product category.

**PIE02.** Show a pie chart of order count distribution by order status.

**PIE03.** Show a donut chart of total revenue contributed by each suppliers.

**PIE04.** Show a pie chart of revenue share by region.

**PIE05.** Show a pie chart of the number of products supplied by each supplier.

---

## PART 4 — SCATTER PLOT

**SCT01.** Show a scatter plot with `discount_%` on the X-axis and `revenue` on the Y-axis for all orders — to explore whether higher discounts correlate with higher revenue.

**SCT02.** Show a scatter plot with `quantity` on the X-axis and `unit_price` on the Y-axis, colored by product category.

**SCT03.** Show a scatter plot of `total_amount` (X-axis) vs number of items per order (Y-axis) to see if larger orders contain more items.

**SCT04.** Show a scatter plot of average rating (X-axis) vs total revenue (Y-axis) per product — to see if higher-rated products sell more.

---

## PART 5 — HEATMAP / CROSSTAB CHART

**HMP01.** Show a heatmap of total revenue by Region (rows) × Category (columns). Color intensity = revenue magnitude.

**HMP02.** Show a heatmap of order count by Month (rows) × Suppliers (columns).

**HMP03.** Show a heatmap of average review rating by Category (rows) × Region (columns).

---

## PART 6 — COMBO CHART (Bar + Line)

**CMB01.** Show a combo chart with monthly revenue as bars and profit margin (%) as a line on a secondary Y-axis.

**CMB02.** Show a combo chart with total orders per month as bars and average order value as a line.

**CMB03.** Show a combo chart comparing revenue (bar) and cumulative revenue (line) per month.

---

## PART 7 — EDGE CASES & ERROR HANDLING

**CHT_ERR01. [Empty result]** Show a bar chart of revenue by category — but filter for orders in year 2099 (no data exists). Verify the agent returns a clear "no data" message instead of crashing or rendering an empty chart silently.

**CHT_ERR02. [Single data point]** Show a line chart of monthly revenue but filter to only December 2025 (1 data point). Verify the agent handles a single-point line chart gracefully.

**CHT_ERR03. [NULL values]** Show a bar chart of average review rating per product — some products have no reviews (NULL avg). Verify nulls are either excluded or shown as 0 with a note.

**CHT_ERR04. [Too many categories]** Show a pie chart of revenue per product (all ~5+ products). Verify the agent either renders it correctly or warns that a pie chart with many slices is hard to read.

**CHT_ERR05. [Ambiguous column]** Ask for a chart of "sales over time" without specifying which column represents "sales" (revenue, profit, or quantity). Verify the agent asks for clarification or makes a reasonable default choice and states it.

**CHT_ERR06. [Invalid chart type]** Ask for a "radar chart of monthly revenue" — verify the agent either renders it or clearly explains it is not supported.

---

## COVERAGE MATRIX

| Chart Type | Prompts |
|---|---|
| Bar (vertical, horizontal, grouped, stacked) | BAR01–BAR07 |
| Line (single, multi-line, cumulative, growth rate) | LINE01–LINE06 |
| Pie / Donut | PIE01–PIE05 |
| Scatter plot | SCT01–SCT04 |
| Heatmap / Crosstab | HMP01–HMP03 |
| Combo (bar + line) | CMB01–CMB03 |
| Edge cases & error handling | CHT_ERR01–CHT_ERR06 |

---

## QUICK TEST GUIDE

| Goal | Prompts |
|---|---|
| Smoke test | BAR01, LINE01, PIE01 |
| Single-metric charts | BAR01–BAR07 |
| Time-series | LINE01–LINE06 |
| Proportion / share | PIE01–PIE05 |
| Correlation / distribution | SCT01–SCT04 |
| Multi-dimension | HMP01–HMP03, CMB01–CMB03 |
| Robustness | CHT_ERR01–CHT_ERR06 |
| Full regression | All prompts |
