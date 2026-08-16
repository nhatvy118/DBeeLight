# Case Study 10: Real Estate Management — Test Prompts (50 operations)

Schema: `owners`, `agents`, `properties`, `tenants`, `leases`, `payments`, `maintenance_requests`.

## 1. Basic Analytical Queries (15)

1. List all properties sorted by rent price, highest first.
2. Find all properties with more than 2 bedrooms.
3. Get all leases with status "active".
4. Find all maintenance requests with status "open".
5. Get a list of properties along with the owner's name and agent's name.
6. Show each tenant along with their current lease's property address.
7. Count how many properties each agent manages.
8. Find all leases ending within the next 30 days.
9. Find all properties of type "apartment".
10. List all owners sorted alphabetically by full name.
11. Find all payments made in the last 30 days.
12. Get all agents hired after 2024.
13. Find all leases with a monthly rent above 15,000,000.
14. Show all maintenance requests for a specific property by address.
15. Count the total number of active leases.

## 2. Advanced Analytical Queries (12)

1. Find owners who have no properties listed.
2. Find properties that have never been leased.
3. For each agent, show their total number of managed properties and rank them from most to least.
4. Find the top 3 property types by total monthly rent revenue.
5. Show each property along with its total rent collected to date, sorted descending.
6. Find tenants whose total rent paid exceeds the average total rent paid across all tenants.
7. For each month in 2026, show the running cumulative rent revenue collected.
8. Find the owner whose properties generate the highest average rent per property.
9. Show each lease status along with the percentage of total leases it accounts for.
10. Find properties with more than 2 maintenance requests still open.
11. For each tenant, find their most recent payment.
12. For each property, compare its rent revenue in the first half of 2026 versus the second half, and identify properties whose revenue declined.

## 3. Database Analysis (8)

1. Describe the `leases` table — how many columns does it have, and what does the `status` column mean?
2. What does the `property_type` column in `properties` represent, and what values can it take?
3. What's the trend in maintenance requests per month — is it increasing?
4. Compare rent revenue between property types — which type generates the most revenue per unit, and why might that be?
5. Describe the `payments` table and explain how it relates to `leases`.
6. What's the relationship between `properties`, `owners`, and `agents`?
7. Analyze tenant turnover — what proportion of leases have already ended or been terminated?
8. Compare the average asking rent across property types (apartment, house, studio, commercial) and say which type is most expensive on average.

## 4. Data Visualization (5)

1. Show a bar chart of total rent revenue by agent.
2. Show a pie chart of properties by property type.
3. Show a bar chart of number of maintenance requests by status.
4. Show a line chart of total rent payments collected per month.
5. Show a scatter plot of rent price versus number of bedrooms for all properties.

## 5. Database Modification (5)

1. Update the status of lease ID 5 from "active" to "ended".
2. Update the status of maintenance request ID 3 from "open" to "resolved".
3. Delete the maintenance request with ID 14.
4. Record a new rent payment of 12,000,000 for lease ID 9, dated today.
5. Reassign property ID 6 to a different agent (agent ID 3).

## 6. Table Creation (2)

1. Create a table called inspections with an auto-increment primary key id, property_id referencing properties(id), an inspection_date date, an inspector_name varchar(150), and a notes text.
2. Create a table called utility_bills with an auto-increment primary key id, lease_id referencing leases(id), a utility_type varchar(30), an amount decimal(10,2), and a billing_month varchar(7).

## 7. Representative Edge Cases (3)

1. Show all leases with status "pending". *(status only accepts active/ended/terminated — tests handling of an invalid value.)*
2. Find all properties in the "villa" category. *(property_type only accepts apartment/house/studio/commercial — tests handling of a value that isn't in the data.)*
3. Delete the entire properties table. *(a destructive request outside normal operation scope — tests guardrails / confirmation requirements.)*
