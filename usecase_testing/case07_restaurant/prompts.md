# Case Study 7: Restaurant Reservation & Ordering — Test Prompts (20 operations)

Schema: `customers`, `tables`, `reservations`, `menu_items`, `orders`, `order_items`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `customers`, `tables`, `menu_items`, `reservations`, `orders`, `order_items`.
Route split: 8 `db_readonly` / 4 `db_general` / 4 `chart` / 2 `db_mutation` / 2 `db_create_table` (balanced default).

## db_readonly (8)

1. List all menu items sorted by price, highest first.
2. Find all reservations with status "confirmed" for today.
3. Get all tables with a capacity of at least 6.
4. Find all menu items in the "dessert" category.
5. Get a list of reservations along with the customer's full name and table number.
6. Show each order along with its total amount and reservation time.
7. Count how many reservations each table has had.
8. Find the top 5 best-selling menu items by quantity ordered.

## db_general (4 — schema explanation / multi-step analysis)

9. Describe the `reservations` table — how many columns does it have, and what does the `status` column mean?
10. What does the `location` column in `tables` represent, and what values can it take?
11. What's the trend in number of orders per week — is business growing?
12. Compare revenue between indoor and outdoor seating — which generates more, and why might that be?

## chart (4)

13. Show a bar chart of revenue by menu category.
14. Show a pie chart of reservations by status.
15. Show a bar chart of the top 5 best-selling menu items.
16. Show a line chart of number of orders per day this month.

## db_mutation (2)

17. Update the status of reservation ID 8 from "confirmed" to "seated".
18. Mark menu item "Beef Steak" as unavailable.

## db_create_table (2)

19. Create a table called `staff` with an auto-increment primary key `id`, a required `full_name` varchar(150), a `role` varchar(50), and a `hire_date` date.
20. Create a table called `feedback` with an auto-increment primary key `id`, `reservation_id` referencing `reservations(id)`, a `rating` integer constrained between 1 and 5, and an optional `comment` text.
