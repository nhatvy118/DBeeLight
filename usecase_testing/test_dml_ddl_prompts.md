# DML & DDL Test Prompts — E-Commerce Schema

Tables in scope: `customers`, `categories`, `products`, `suppliers`,
`product_suppliers`, `orders`, `order_items`, `reviews`

---

## PART 1 — DDL (Schema Modification)

### Add / Modify Columns

**DDL01.** Add a new column `loyalty_points` (integer, default 0) to the `customers` table.

**DDL02.** Add a `discount_percent` column (decimal 5,2) to the `products` table with a default value of 0 and a CHECK constraint ensuring the value is between 0 and 100.

**DDL03.** Add a `shipped_at` timestamp column (nullable) to the `orders` table.

**DDL04.** Change the data type of the `phone` column in `customers` from VARCHAR(20) to VARCHAR(30). (only for Postgres, SQLite only type TEXT)

**DDL05.** Rename the column `full_name` in `customers` to `name`.

### Add / Drop Constraints

**DDL06.** Add a UNIQUE constraint on the `email` column in `suppliers`.

**DDL07.** Add a CHECK constraint to `orders` ensuring `total_amount` must be greater than 0.

**DDL08.** Add a CHECK constraint to `order_items` ensuring `quantity` must be at least 1.

**DDL09.** Drop the CHECK constraint on `rating` from the `reviews` table.

**DDL10.** Add a NOT NULL constraint to the `city` column in `customers`. *(Edge case: will fail if existing rows have NULL city)*

### Add / Drop Indexes

**DDL11.** Create an index on the `status` column in `orders` to speed up filtering by order status.

**DDL12.** Create a composite index on (`customer_id`, `created_at`) in `orders`.

**DDL13.** Drop the index on `status` in `orders`.

### Add / Drop Tables

**DDL14.** Create a new table called `promotions` with columns: `id` (serial PK), `code` varchar(50) unique not null, `discount_percent` decimal(5,2), `valid_from` date, `valid_to` date.

**DDL15.** Drop the `promotions` table.

---

## PART 2 — DML: INSERT (Happy Path)

**INS01.** Insert a new customer with full_name "John Doe", email "john@example.com", phone "0123456789", city "Ha Noi".

**INS02.** Insert a top-level category named "Sports" (no parent).

**INS03.** Insert a child category named "Outdoor" under the "Sports" category.

**INS04.** Insert a new product named "Running Shoes" priced at 850000, stock 30, under the "Outdoor" category.

**INS05.** Insert a new supplier named "SportZone", email "sport@zone.com", country "Vietnam".

**INS06.** Insert a product-supplier relationship: "Running Shoes" is supplied by "SportZone" at a supply price of 500000.

**INS07.** Insert a new order for customer "John Doe" with status "pending" and total_amount 850000.

**INS08.** Insert an order item: the order above contains 1 unit of "Running Shoes" at unit_price 850000.

**INS09.** Insert a review: customer "John Doe" gives "Running Shoes" a rating of 5 with comment "Excellent quality".

**INS10.** Insert 3 new customers in a single statement (batch insert).

---

## PART 3 — DML: INSERT (Constraint Violations — Expected to Fail)

**INS_ERR01. [UNIQUE violation]** Insert a customer with the same email as an existing customer (e.g., email "john@example.com" again).

**INS_ERR02. [NOT NULL violation]** Insert a product without providing a `name` (name is NOT NULL).

**INS_ERR03. [NOT NULL violation]** Insert an order without a `total_amount`.

**INS_ERR04. [FK violation]** Insert a product with a `category_id` that does not exist in the `categories` table (e.g., category_id = 9999).

**INS_ERR05. [FK violation]** Insert an order with a `customer_id` that does not exist in the `customers` table.

**INS_ERR06. [FK violation]** Insert an order_item referencing an `order_id` that does not exist.

**INS_ERR07. [FK violation]** Insert an order_item referencing a `product_id` that does not exist.

**INS_ERR08. [CHECK violation]** Insert a review with a rating of 6 (violates CHECK rating BETWEEN 1 AND 5).

**INS_ERR09. [CHECK violation]** Insert a review with a rating of 0.

**INS_ERR10. [Duplicate PK]** Insert a product_supplier row with the same (product_id, supplier_id) pair that already exists in `product_suppliers`.

---

## PART 4 — DML: UPDATE (Happy Path)

**UPD01.** Update the city of customer "John Doe" to "Da Nang".

**UPD02.** Increase the price of all products in the "Electronics" category by 10%.

**UPD03.** Set the stock of product "Running Shoes" to 0 (out of stock).

**UPD04.** Change the status of all "pending" orders that were created more than 30 days ago to "cancelled".

**UPD05.** Update the `total_amount` of a specific order to match the recalculated sum from its order_items (quantity × unit_price).

**UPD06.** Update the supply price of "Running Shoes" from supplier "SportZone" to 520000.

**UPD07.** Set `shipped_at` to the current timestamp for all orders with status "shipped".

**UPD08.** Apply a 5% discount to all products that have never been ordered (stock > 0 but not in any order_items).

---

## PART 5 — DML: UPDATE (Constraint Violations — Expected to Fail)

**UPD_ERR01. [UNIQUE violation]** Update a customer's email to an email address already used by another customer.

**UPD_ERR02. [NOT NULL violation]** Update a product's `name` to NULL.

**UPD_ERR03. [FK violation]** Update an order's `customer_id` to an ID that does not exist in `customers`.

**UPD_ERR04. [CHECK violation]** Update a review's rating to -1.

**UPD_ERR05. [CHECK violation]** Update an order's total_amount to -500 (violates CHECK total_amount > 0, if constraint DDL07 was applied).

---

## PART 6 — DML: DELETE (Happy Path)

**DEL01.** Delete the review left by customer "John Doe" on "Running Shoes".

**DEL02.** Delete all order_items belonging to a specific order (before deleting the order itself).

**DEL03.** Delete the order created for customer "John Doe".

**DEL04.** Delete all products that are out of stock (stock = 0) and have never been ordered.

**DEL05.** Delete the product-supplier relationship between "Running Shoes" and "SportZone".

**DEL06.** Delete all cancelled orders older than 1 year.

---

## PART 7 — DML: DELETE (Constraint Violations — Expected to Fail)

**DEL_ERR01. [FK violation]** Delete a customer who still has existing orders.

**DEL_ERR02. [FK violation]** Delete a product that still appears in at least one order_item.

**DEL_ERR03. [FK violation]** Delete a category that still has products assigned to it.

**DEL_ERR04. [FK violation]** Delete an order that still has order_items referencing it.

**DEL_ERR05. [FK violation]** Delete a supplier that still has rows in `product_suppliers`.

---

## PART 8 — MIXED / ADVANCED SCENARIOS

**MIX01.** A customer wants to cancel their most recent order: update the order status to "cancelled" and restore the stock quantity for each product in that order back to `products.stock`.

**MIX02.** Move all products from the "Outdoor" category to the "Sports" parent category, then delete the now-empty "Outdoor" category.

**MIX03.** A supplier goes out of business: delete all their entries from `product_suppliers`, then delete the supplier record.

**MIX04.** Merge two duplicate customers (same name, different emails) into one: keep the record with more orders, reassign all orders and reviews from the duplicate to the kept record, then delete the duplicate. *(Tests FK reassignment before delete)*

**MIX05.** Bulk-insert 10 order_items for a single order using a single INSERT statement with multiple value rows.

---

## COVERAGE MATRIX

| Constraint Type | Insert ✓ | Insert ✗ | Update ✓ | Update ✗ | Delete ✓ | Delete ✗ |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| NOT NULL | INS01–INS10 | INS_ERR02, INS_ERR03 | UPD01–UPD08 | UPD_ERR02 | — | — |
| UNIQUE | INS01 | INS_ERR01 | UPD01 | UPD_ERR01 | — | — |
| CHECK | INS09 | INS_ERR08, INS_ERR09 | UPD07 | UPD_ERR04, UPD_ERR05 | — | — |
| FK (child→parent) | INS06–INS09 | INS_ERR04–INS_ERR07 | UPD05, UPD06 | UPD_ERR03 | DEL05 | DEL_ERR05 |
| FK (parent has children) | — | — | — | — | DEL01–DEL06 | DEL_ERR01–DEL_ERR05 |
| Duplicate PK / Composite PK | INS06 | INS_ERR10 | UPD06 | — | DEL05 | — |
