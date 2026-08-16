# Case Study 9: Logistics & Warehouse — Test Prompts (50 operations)

Schema: `warehouses`, `products`, `inventory`, `carriers`, `routes`, `shipments`, `tracking_events`.

## 1. Basic Analytical Queries (15)

1. List all warehouses sorted by capacity, highest first.
2. Find all products in the "Electronics" category.
3. Get all shipments with status "delayed".
4. Find all inventory records with quantity below 100.
5. Get a list of shipments along with the carrier's name and destination city.
6. Count how many shipments each carrier has handled.
7. Find all products with SKU starting with "SKU-2026".
8. List all carriers sorted alphabetically.
9. Find all routes with a distance greater than 500 km.
10. Get all shipments dispatched from a specific warehouse.
11. Find all tracking events with status description "out for delivery".
12. Show all inventory records for a specific product across all warehouses.
13. Find all warehouses located in "Da Nang".
14. Get the 10 most recent shipments.
15. Count the total number of products in the catalog.

## 2. Advanced Analytical Queries (10)

1. Find products that have no inventory record in any warehouse.
2. Find warehouses with no shipments originating from them.
3. For each warehouse, show total inventory quantity and rank warehouses from highest to lowest stock.
4. Find the top 3 carriers by total number of shipments handled.
5. Show each product along with its total quantity across all warehouses, sorted descending.
6. Find warehouses whose total inventory quantity exceeds the average inventory quantity across all warehouses.
7. For each month in 2026, show the running cumulative number of shipments.
8. Find the carrier with the highest ratio of delayed shipments to total shipments.
9. Show each shipment status along with the percentage of total shipments it accounts for.
10. For each shipment, calculate the time elapsed between its first and last tracking event, and find the 5 shipments with the longest transit time.

## 3. Database Analysis (8)

1. Describe the `shipments` table — how many columns does it have, and what does the `status` column mean?
2. What's the trend in shipment volume per month — is throughput increasing?
3. Compare delivery performance across carriers — which carrier has the highest delayed-shipment rate, and why might that be?
4. Describe the `tracking_events` table and explain how it relates to `shipments`.
5. What's the relationship between `warehouses`, `inventory`, and `products`?
6. Analyze stock distribution — what proportion of total inventory quantity is concentrated in the largest warehouse?
7. Which route has the highest average shipment frequency relative to its distance?
8. For each warehouse, define coverage as (total inventory `quantity` in that warehouse) divided by (average number of shipments departing that warehouse per calendar day in 2026, counting only days that have at least one shipment). Rank warehouses by coverage descending. If a warehouse has no 2026 shipments, exclude it.

## 4. Data Visualization (7)

1. Show a bar chart of total inventory quantity by warehouse.
2. Show a pie chart of shipments by status.
3. Show a bar chart of number of shipments per carrier.
4. Show a line chart of number of shipments per month in 2026.
5. Show a bar chart of the top 5 routes by distance.
6. Show a pie chart of products by category.
7. Show a bar chart of inventory quantity by product category.

## 5. Database Modification (5)

1. Update the status of shipment ID 15 from "in_transit" to "delivered".
2. Update the quantity of inventory record ID 8 to 500 after a restock.
3. Delete the tracking event with ID 50.
4. Move 50 units of Factor Box from the Hanoi warehouse over to the Da Nang warehouse.
5. Update the destination city of route ID 6 to "Can Tho".

## 6. Table Creation (2)

1. Create a table called returns with an auto-increment primary key id, shipment_id referencing shipments(id), a reason varchar(200), and a return_date date defaulting to today.
2. Create a pick-list table named order. It needs an auto-increment id, plus columns called user for the picker, select for the bin code, table for the staging table number, and check as a verified flag that defaults to false.

## 7. Representative Edge Cases (3)

1. Show all shipments with status "returned". *(status only accepts pending/in_transit/delivered/delayed — tests handling of an invalid value.)*
2. Find all products in the "Furniture" category. *(this category most likely isn't in the seed data — tests empty-result handling.)*
3. Delete the entire warehouses table. *(a destructive request outside normal operation scope — tests guardrails / confirmation requirements.)*
