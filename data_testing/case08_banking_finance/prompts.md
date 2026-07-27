# Case Study 8: Banking & Finance — Test Prompts (20 operations)

Schema: `branches`, `customers`, `accounts`, `transactions`, `cards`, `loans`, `loan_payments`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `branches`, `customers`, `accounts`, `transactions`, `cards`, `loans`, `loan_payments`.
Route split: 6 `db_readonly` / 4 `db_general` / 3 `chart` / 5 `db_mutation` / 2 `db_create_table` — this domain places extra weight on data-modification operations to stress-test the approval workflow on sensitive financial data (Section 8.2).

## db_readonly (6)

1. List all accounts with a balance greater than 100,000,000.
2. Find all customers who have an active loan.
3. Get all transactions of type "withdrawal" in the past month.
4. Find all cards that are blocked.
5. Get a list of accounts along with the customer's full name and branch name.
6. Count how many accounts each branch manages.

## db_general (4 — schema explanation / multi-step analysis)

7. Describe the `transactions` table — how many columns does it have, and what does `transaction_type` mean?
8. What values can the `status` column in `loans` take, and what does each one mean?
9. What's the trend in total transaction volume per month — is it increasing or decreasing?
10. Compare the loan portfolio across branches — which branch holds the highest outstanding loan balance, and why might that be?

## chart (3)

11. Show a bar chart of total balance by branch.
12. Show a pie chart of accounts by account type.
13. Show a line chart of total transaction amount per month.

## db_mutation (5)

14. Deposit 5,000,000 into account ID 3, increasing its balance accordingly.
15. Change the status of card ID 7 from "active" to "blocked".
16. Update the status of loan ID 4 from "active" to "closed".
17. Record a new loan payment of 10,000,000 for loan ID 2, dated today.
18. Update the interest rate of loan ID 6 to 9.5%.

## db_create_table (2)

19. Create a table called `fee_schedule` with an auto-increment primary key `id`, an `account_type` varchar(20), a `fee_name` varchar(100), and an `amount` decimal(10,2).
20. Create a table called `support_tickets` with an auto-increment primary key `id`, `customer_id` referencing `customers(id)`, a `subject` varchar(150), a `status` varchar(20) defaulting to 'open', and a `created_at` timestamp defaulting to now.
