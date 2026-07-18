# Case Study 4: HR & Payroll — Test Prompts (20 operations)

Schema: `departments`, `positions`, `employees`, `attendance`, `payroll`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `departments`, `positions`, `employees`, `attendance`, `payroll`.
Route split: 8 `db_readonly` / 4 `db_general` / 4 `chart` / 2 `db_mutation` / 2 `db_create_table` (balanced default).

## db_readonly (8)

1. List all employees sorted by salary, highest first.
2. Find all employees in the "Engineering" department.
3. Get the top 5 highest-paid employees.
4. Find all employees hired after 2023.
5. Get a list of employees along with their department name and position title.
6. Show each department along with the number of employees in it.
7. Find all employees who were marked absent in the attendance log.
8. Get each employee's reporting manager's name.

## db_general (4 — schema explanation / multi-step analysis)

9. Describe the `employees` table — how many columns does it have, and what does `manager_id` represent?
10. What does the `level` column in `positions` mean?
11. What's the salary trend across departments — which department pays the highest average salary, and why might that be?
12. Compare payroll cost between departments for period 2026-06 — which department has the highest total net pay?

## chart (4)

13. Show a bar chart of average salary by department.
14. Show a pie chart of employees by position level.
15. Show a bar chart of number of employees per department.
16. Show a line chart of total net pay by payroll period.

## db_mutation (2)

17. Update the salary of employee ID 5 to 45,000,000.
18. Change the attendance status of employee ID 3 on a specific date to "leave".

## db_create_table (2)

19. Create a table called `leave_requests` with an auto-increment primary key `id`, `employee_id` referencing `employees(id)`, a `start_date` date, an `end_date` date, a `reason` varchar(200), and a `status` varchar(20) defaulting to 'pending'.
20. Create a table called `training_sessions` with an auto-increment primary key `id`, a required `title` varchar(150), a `session_date` date, and a `department_id` referencing `departments(id)`.
