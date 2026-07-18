# Case Study 9: Logistics & Warehouse — Test Prompts (20 operations)

Schema: `warehouses`, `products`, `inventory`, `carriers`, `routes`, `shipments`, `tracking_events`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `warehouses`, `products`, `inventory`, `carriers`, `routes`, `shipments`, `tracking_events`.
Route split: 6 `db_readonly` / 3 `db_general` / 7 `chart` / 2 `db_mutation` / 2 `db_create_table` — this domain places extra weight on chart operations given its rich time-series and operational data (Section 8.2).

## db_readonly (6)

1. List all warehouses sorted by capacity, highest first.
2. Find all products in the "Electronics" category.
3. Get all shipments with status "delayed".
4. Find all inventory records with quantity below 100.
5. Get a list of shipments along with the carrier's name and destination city.
6. Count how many shipments each carrier has handled.

## db_general (3 — schema explanation / multi-step analysis)

7. Describe the `shipments` table — how many columns does it have, and what does the `status` column mean?
8. What's the trend in shipment volume per month — is throughput increasing?
9. Compare delivery performance across carriers — which carrier has the highest delayed-shipment rate, and why might that be?

## chart (7)

10. Show a bar chart of total inventory quantity by warehouse.
11. Show a pie chart of shipments by status.
12. Show a bar chart of number of shipments per carrier.
13. Show a line chart of number of shipments per month in 2026.
14. Show a bar chart of the top 5 routes by distance.
15. Show a pie chart of products by category.
16. Show a bar chart of inventory quantity by product category.

## db_mutation (2)

17. Update the status of shipment ID 15 from "in_transit" to "delivered".
18. Update the quantity of inventory record ID 8 to 500 after a restock.

## db_create_table (2)

19. Create a table called `returns` with an auto-increment primary key `id`, `shipment_id` referencing `shipments(id)`, a `reason` varchar(200), and a `return_date` date defaulting to today.
20. Create a table called `drivers` with an auto-increment primary key `id`, a required `full_name` varchar(150), a `license_number` varchar(30), and a `carrier_id` referencing `carriers(id)`.
