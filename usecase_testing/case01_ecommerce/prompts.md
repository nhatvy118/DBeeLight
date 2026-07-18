# Case Study 1: E-Commerce — Test Prompts (20 operations)

Schema: `customers`, `categories`, `products`, `suppliers`, `product_suppliers`, `orders`, `order_items`, `reviews`.
Setup: run `schema.sql` first, then import each file in `seed_data/` with **append to existing table** mode, in this order: `categories`, `customers`, `suppliers`, `products`, `orders`, `order_items`, `reviews`, `product_suppliers`.
Route split: 8 `db_readonly` / 4 `db_general` / 4 `chart` / 2 `db_mutation` / 2 `db_create_table` (balanced default).

## db_readonly (8)

1. Get a list of all customers sorted alphabetically by full name.
2. Find all products priced under 200,000 that still have stock available.
3. Get the 10 most expensive products.
4. Find all orders with status "shipped".
5. Get a list of all orders along with the full name of the customer who placed each order.
6. Show each product's name along with the name of its category.
7. Get the top 5 best-selling products by total quantity sold.
8. Get each parent category along with the count of its child categories.

## db_general (4 — schema explanation / multi-step analysis)

9. How many columns does the `orders` table have, and what does each one represent?
10. What does the `status` column in the `orders` table mean, and what values can it take?
11. What's the revenue trend month over month for 2026 — is it increasing or decreasing?
12. Compare total revenue between the Electronics and Fashion categories — which is performing better, and why might that be?

## chart (4)

13. Show a bar chart of total revenue by product category.
14. Show a pie chart of order count distribution by order status.
15. Show a bar chart of the top 5 best-selling products by quantity sold.
16. Show a pie chart of revenue share by supplier.

## db_mutation (2)

17. Update the price of "iPhone 15" to 21,000,000.
18. Change the status of order ID 4 from "pending" to "cancelled".

## db_create_table (2)

19. Create a table called `wishlists` to track which products a customer has saved: an auto-increment primary key `id`, `customer_id` referencing `customers(id)`, `product_id` referencing `products(id)`, and an `added_at` timestamp defaulting to now.
20. Create a table called `coupons` with an auto-increment primary key `id`, a unique required `code` varchar(30), a `discount_percent` decimal(5,2), a `valid_until` date, and an `is_active` boolean defaulting to true.
