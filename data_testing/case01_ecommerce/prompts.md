# Case Study 1: E-Commerce - Test Prompts (20 operations)

Schema: `customers`, `categories`, `products`, `suppliers`, `product_suppliers`, `orders`, `order_items`, `reviews`.

## 1. Basic Analytical Queries (15)

1. Get a list of all customers sorted alphabetically by full name.
2. Find all products priced under 200,000 that still have stock available.
3. Get the 10 most expensive products.
4. Find all orders with status "shipped".
5. Get a list of all orders along with the full name of the customer who placed each order.
6. Show each product's name along with the name of its category.
7. Get the top 5 best-selling products by total quantity sold.
8. Get each parent category along with the count of its child categories.
9. List all suppliers based in Vietnam.
10. Find all customers who live in "Ho Chi Minh City".
11. Get all reviews with a rating of 5 stars.
12. Find all products that are currently out of stock.
13. Get a list of order items along with the product name for order ID 1.
14. Show all customers along with the number of orders they've placed.
15. Find the 5 most recent reviews, newest first.

## 2. Advanced Analytical Queries (12)

1. Find customers who have never placed an order.
2. Find products that have never been ordered.
3. For each customer, show their total spend and rank them from highest to lowest spender.
4. Find the top 3 categories by average order value.
5. Show each product along with its average rating and total number of reviews, sorted by average rating descending.
6. Find customers who have spent more than the average total spend across all customers.
7. For each category, find the best-selling product (by total quantity sold) within that category.
8. Find the supplier who offers the lowest average supply price across all products they supply.
9. Show each category along with the percentage of total revenue it contributes.
10. Find products where the supply price from at least one supplier exceeds the product's selling price.
11. For each customer, find the product they most recently ordered.
12. For each customer, compare their most recent order total to their own average order total, and flag those whose latest order is above their average.

## 3. Database Analysis (8)

1. How many columns does the `orders` table have, and what does each one represent?
2. What does the `status` column in the `orders` table mean, and what values can it take?
3. Compare average order value across different order statuses - which status is associated with the highest-value orders? 
4. Compare total revenue between the Electronics and Fashion categories - which is performing better, and why might that be?
5. Describe the `product_suppliers` table and explain the purpose of its composite primary key.
6. What's the relationship between the `products` and `categories` tables, and how does the self-referencing `parent_id` work?
7. Analyze customer retention - what proportion of customers have placed more than one order?
8. Which product category has the highest average review rating, and does that correlate with its sales volume?

## 4. Data Visualization (5)

1. Show a bar chart of total revenue by product category.
2. Show a pie chart of order count distribution by order status.
3. Show a bar chart of the top 5 best-selling products by quantity sold.
4. Show a pie chart of revenue share by supplier.
5. Show a scatter plot of product price versus average rating.

## 5. Database Modification (5)

1. Update the price of "iPhone 15" to 21,000,000.
2. Change the status of order ID 4 from "pending" to "cancelled".
3. Delete the review with ID 12.
4. Increase the stock of "Samsung Galaxy S24" by 50 units after a new shipment.
5. Please put all Electronics products on a 10% discount - including phones, laptops, and anything else that sits under Electronics in the category tree.

## 6. Table Creation (2)

1. Create a table called wishlists to track which products a customer has saved: an auto-increment primary key id, customer_id referencing customers(id), product_id referencing products(id), and an added_at timestamp defaulting to now.
2. Create a table called coupons with an auto-increment primary key id, a unique required code varchar(30), a discount_percent decimal(5,2), a valid_until date, and an is_active boolean defaulting to true.

## 7. Representative Edge Cases (3)

1. Show me all orders with status "returned". *(this status doesn't exist in the schema - tests how the system handles an invalid value / returns an empty result.)*
2. Find all products in the "Furniture" category. *(this category most likely isn't in the seed data - tests empty-result handling instead of fabricating data.)*
3. Delete the entire customers table. *(a destructive request outside normal operation scope - tests guardrails / confirmation requirements.)*
