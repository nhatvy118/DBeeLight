# Case Study 1: E-Commerce — Test Prompts (50 operations)

Schema: `customers`, `categories`, `products`, `suppliers`, `product_suppliers`, `orders`, `order_items`, `reviews`.
Setup: run `schema.sql` first, then import each file in `seed_data/` with **append to existing table** mode, in this order: `categories`, `customers`, `suppliers`, `products`, `orders`, `order_items`, `reviews`, `product_suppliers`.

Lưu ý dữ liệu: `seed_data/orders.xlsx` không có cột `created_at`, nên sau khi import mọi đơn hàng sẽ nhận cùng một timestamp (giờ import, do `DEFAULT NOW()`) — mọi câu hỏi theo tháng/ngày dựa trên `orders.created_at` sẽ không có ý nghĩa cho tới khi seed data được bổ sung cột này.

## 1. Basic Analytical Queries (15)

1. [CŨ] Get a list of all customers sorted alphabetically by full name.
2. [CŨ] Find all products priced under 200,000 that still have stock available.
3. [CŨ] Get the 10 most expensive products.
4. [CŨ] Find all orders with status "shipped".
5. [CŨ] Get a list of all orders along with the full name of the customer who placed each order.
6. [CŨ] Show each product's name along with the name of its category.
7. [CŨ] Get the top 5 best-selling products by total quantity sold.
8. [CŨ] Get each parent category along with the count of its child categories.
9. [MỚI] List all suppliers based in Vietnam.
10. [MỚI] Find all customers who live in "Ho Chi Minh City".
11. [MỚI] Get all reviews with a rating of 5 stars.
12. [MỚI] Find all products that are currently out of stock.
13. [MỚI] Get a list of order items along with the product name for order ID 1.
14. [MỚI] Show all customers along with the number of orders they've placed.
15. [MỚI] Find the 5 most recent reviews, newest first.

## 2. Advanced Analytical Queries (12)

1. [MỚI] Find customers who have never placed an order.
2. [MỚI] Find products that have never been ordered.
3. [MỚI] For each customer, show their total spend and rank them from highest to lowest spender.
4. [MỚI] Find the top 3 categories by average order value.
5. [MỚI] Show each product along with its average rating and total number of reviews, sorted by average rating descending.
6. [MỚI] Find customers who have spent more than the average total spend across all customers.
7. [MỚI] For each category, find the best-selling product (by total quantity sold) within that category.
8. [MỚI] Find the supplier who offers the lowest average supply price across all products they supply.
9. [MỚI] Show each category along with the percentage of total revenue it contributes.
10. [MỚI] Find products where the supply price from at least one supplier exceeds the product's selling price.
11. [MỚI] For each customer, find the product they most recently ordered.
12. [MỚI] For each customer, compare their most recent order total to their own average order total, and flag those whose latest order is above their average.

## 3. Database Analysis (8)

1. [CŨ] How many columns does the `orders` table have, and what does each one represent?
2. [CŨ] What does the `status` column in the `orders` table mean, and what values can it take?
3. [CŨ→MỚI] Compare average order value across different order statuses — which status is associated with the highest-value orders? 
4. [CŨ] Compare total revenue between the Electronics and Fashion categories — which is performing better, and why might that be?
5. [MỚI] Describe the `product_suppliers` table and explain the purpose of its composite primary key.
6. [MỚI] What's the relationship between the `products` and `categories` tables, and how does the self-referencing `parent_id` work?
7. [MỚI] Analyze customer retention — what proportion of customers have placed more than one order?
8. [MỚI] Which product category has the highest average review rating, and does that correlate with its sales volume?

## 4. Data Visualization (5)

1. [CŨ] Show a bar chart of total revenue by product category.
2. [CŨ] Show a pie chart of order count distribution by order status.
3. [CŨ] Show a bar chart of the top 5 best-selling products by quantity sold.
4. [CŨ] Show a pie chart of revenue share by supplier.
5. [MỚI] Show a scatter plot of product price versus average rating.

## 5. Database Modification (5)

1. [CŨ] Update the price of "iPhone 15" to 21,000,000.
2. [CŨ] Change the status of order ID 4 from "pending" to "cancelled".
3. [MỚI] Delete the review with ID 12.
4. [MỚI] Increase the stock of "Samsung Galaxy S24" by 50 units after a new shipment.
5. [MỚI] Please put all Electronics products on a 10% discount — including phones, laptops, and anything else that sits under Electronics in the category tree.

## 6. Table Creation (2)

1. [CŨ] Create a table called `wishlists` to track which products a customer has saved: an auto-increment primary key `id`, `customer_id` referencing `customers(id)`, `product_id` referencing `products(id)`, and an `added_at` timestamp defaulting to now.
2. [CŨ] Create a table called `coupons` with an auto-increment primary key `id`, a unique required `code` varchar(30), a `discount_percent` decimal(5,2), a `valid_until` date, and an `is_active` boolean defaulting to true.

## 7. Representative Edge Cases (3)

1. [MỚI] Show me all orders with status "returned". *(this status doesn't exist in the schema — tests how the system handles an invalid value / returns an empty result.)*
2. [MỚI] Find all products in the "Furniture" category. *(this category most likely isn't in the seed data — tests empty-result handling instead of fabricating data.)*
3. [MỚI] Delete the entire `customers` table. *(a destructive request outside normal operation scope — tests guardrails / confirmation requirements.)*
