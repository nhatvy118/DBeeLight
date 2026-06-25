# English Test Prompts — E-Commerce Database

---

## PART 1: TABLE CREATION PROMPTS

Use these prompts to test if the app correctly generates CREATE TABLE statements.

---

**T01.** Create a table called `customers` with the following columns: an auto-increment integer primary key `id`, a required `full_name` varchar(100), a unique required `email` varchar(150), an optional `phone` varchar(20), an optional `city` varchar(50), and a `created_at` timestamp that defaults to the current time.

**T02.** Create a table called `categories` for product categories. It needs an auto-increment primary key `id`, a required `name` varchar(100), and a `parent_id` integer that references the `id` of the same `categories` table (self-referencing foreign key, nullable for top-level categories).

**T03.** Create a table called `products` with an auto-increment primary key `id`, a required `name` varchar(200), an optional `description` text, a required `price` decimal(12,2), a `stock` integer defaulting to 0, and a `category_id` integer that references `categories(id)`.

**T04.** Create a table called `suppliers` with an auto-increment primary key `id`, a required `name` varchar(150), an optional `email` varchar(150), an optional `phone` varchar(20), and an optional `country` varchar(50).

**T05.** Create a junction table called `product_suppliers` to represent a many-to-many relationship between products and suppliers. It should have `product_id` referencing `products(id)`, `supplier_id` referencing `suppliers(id)`, a `supply_price` decimal(12,2), and a composite primary key on (`product_id`, `supplier_id`).

**T06.** Create a table called `orders` with an auto-increment primary key `id`, a `customer_id` integer referencing `customers(id)`, a `status` varchar(20) defaulting to `'pending'`, a `total_amount` decimal(12,2), and a `created_at` timestamp defaulting to now.

**T07.** Create a table called `order_items` with an auto-increment primary key `id`, an `order_id` integer referencing `orders(id)`, a `product_id` integer referencing `products(id)`, a required `quantity` integer, and a required `unit_price` decimal(12,2).

**T08.** Create a table called `reviews` with an auto-increment primary key `id`, a `customer_id` referencing `customers(id)`, a `product_id` referencing `products(id)`, a `rating` integer constrained between 1 and 5, an optional `comment` text, and a `created_at` timestamp defaulting to now.

---

## PART 2: SQL QUERY TEST PROMPTS

### 🟢 LEVEL 1 — Basic SELECT, Filter, Sort

**P01.** Get a list of all customers sorted alphabetically by full name from A to Z.

**P02.** Find all products that are priced under 200000 and still have stock available (stock greater than 0).

**P03.** Get the 10 most expensive products.

**P04.** Find all orders with status "shipped".

**P05.** Count the total number of customers from the city "New York".

---

### 🟡 LEVEL 2 — JOIN (2 tables)

**P06.** Get a list of all orders along with the full name of the customer who placed each order.

**P07.** Show each product's name along with the name of its category.

**P08.** Find all products that have never received any review.

**P09.** Find the names of customers who have never placed any order.

**P10.** Get all orders along with the total quantity of items in each order.

---

### 🟠 LEVEL 3 — Multi-table JOIN + Aggregation

**P11.** Get the full order detail including: customer full name, product name, quantity, unit price, and line total (quantity × unit price).

**P12.** Calculate the total revenue grouped by month for the year 2026.

**P13.** Get the top 5 best-selling products by total quantity sold across all orders.

**P14.** Get the top 5 customers who have spent the most money, counting only orders with status "shipped".

**P15.** Calculate the average rating for each product, but only include products that have received at least 3 reviews.

**P16.** Get a list of all suppliers along with the number of products each supplier provides.

**P17.** Get each parent category and the count of child categories under it.

---

### 🔴 LEVEL 4 — Subquery, CTE, Window Function

**P18.** Find all products whose price is higher than the average price of the category they belong to.

**P19.** Get customers who have placed more than 3 orders and whose total spending exceeds 5000000.

**P20.** For each customer, get their most recent order along with the order status.

**P21.** Rank products within each category by revenue using a window function (RANK or ROW_NUMBER).

**P22.** Find pairs of products that were purchased together in the same order at least 2 times.

**P23.** Calculate the percentage of total revenue contributed by each category compared to overall revenue.

**P24.** Get the full purchase history of customer with ID 5, including: product name, order date, quantity, unit price, and their review rating for that product (if any).

---

### 🟣 LEVEL 5 — Complex / Edge Cases

**P25.** Find products that have never been sold (not appearing in any order item) but still have stock remaining.

**P26.** Find customers who have left a review for a product they never actually purchased (data anomaly).

**P27.** Calculate the running total of daily revenue for June 2026.

**P28.** For each supplier, get the product with the lowest supply price that they provide.

**P29.** Retrieve the full category tree (parent → child → grandchild) recursively using WITH RECURSIVE.

**P30.** Detect orders where the `total_amount` stored in the `orders` table does not match the sum calculated from `order_items` (quantity × unit_price).

---

## QUICK REFERENCE — PROMPT BY TEST GOAL

| Goal | Prompts |
|---|---|
| Smoke test | T01–T08, P01, P06, P11 |
| Table creation only | T01–T08 |
| Basic queries | P01–P05 |
| JOIN correctness | P06–P10 |
| Aggregation & grouping | P12–P17 |
| Subquery / CTE / Window | P18–P24 |
| Edge cases & data quality | P25–P30 |
| Full regression | T01–T08 + P01–P30 |
