# Case Study 10: Real Estate Management — Test Prompts (20 operations)

Schema: `owners`, `agents`, `properties`, `tenants`, `leases`, `payments`, `maintenance_requests`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `owners`, `agents`, `properties`, `tenants`, `leases`, `payments`, `maintenance_requests`.
Route split: 8 `db_readonly` / 4 `db_general` / 4 `chart` / 2 `db_mutation` / 2 `db_create_table` (balanced default).

## db_readonly (8)

1. List all properties sorted by rent price, highest first.
2. Find all properties with more than 2 bedrooms.
3. Get all leases with status "active".
4. Find all maintenance requests with status "open".
5. Get a list of properties along with the owner's name and agent's name.
6. Show each tenant along with their current lease's property address.
7. Count how many properties each agent manages.
8. Find all leases ending within the next 30 days.

## db_general (4 — schema explanation / multi-step analysis)

9. Describe the `leases` table — how many columns does it have, and what does the `status` column mean?
10. What does the `property_type` column in `properties` represent, and what values can it take?
11. What's the trend in maintenance requests per month — is it increasing?
12. Compare rent revenue between property types — which type generates the most revenue per unit, and why might that be?

## chart (4)

13. Show a bar chart of total rent revenue by agent.
14. Show a pie chart of properties by property type.
15. Show a bar chart of number of maintenance requests by status.
16. Show a line chart of total rent payments collected per month.

## db_mutation (2)

17. Update the status of lease ID 5 from "active" to "ended".
18. Update the status of maintenance request ID 3 from "open" to "resolved".

## db_create_table (2)

19. Create a table called `inspections` with an auto-increment primary key `id`, `property_id` referencing `properties(id)`, an `inspection_date` date, an `inspector_name` varchar(150), and a `notes` text.
20. Create a table called `utility_bills` with an auto-increment primary key `id`, `lease_id` referencing `leases(id)`, a `utility_type` varchar(30), an `amount` decimal(10,2), and a `billing_month` varchar(7).
