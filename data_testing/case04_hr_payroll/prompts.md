# Case Study 4: HR & Payroll - Test Prompts (50 operations)

Schema: `departments`, `positions`, `employees`, `attendance`, `payroll`.

## 1. Basic Analytical Queries (15)

1. List all employees sorted by salary, highest first.
2. Find all employees in the "Engineering" department.
3. Get the top 5 highest-paid employees.
4. Find all employees hired after 2023.
5. Get a list of employees along with their department name and position title.
6. Show each department along with the number of employees in it.
7. Find all employees who were marked absent in the attendance log.
8. Get each employee's reporting manager's name.
9. Find all employees in the "Marketing" department.
10. List all positions sorted by level.
11. Find all attendance records marked "late" for a specific date.
12. Get all employees hired in 2022.
13. Show all payroll records for period "2026-05".
14. Find all departments located in "Ho Chi Minh City".
15. Count the total number of employees in the company.

## 2. Advanced Analytical Queries (12)

1. Find employees who have never had a payroll record generated.
2. Find departments with no employees assigned.
3. For each department, show total headcount and rank departments from largest to smallest.
4. Find the top 3 positions by average salary.
5. Show each employee along with their total bonus received across all payroll periods, sorted descending.
6. Find employees whose salary exceeds the average salary of their own department.
7. For each hire year, show the running cumulative headcount of employees hired up to and including that year.
8. Find the manager with the largest number of direct reports.
9. Show each position level along with the percentage of total headcount it accounts for.
10. Find employees whose attendance includes more "late" days than "present" days in a given month.
11. For each employee, find their most recent payroll record.
12. Find the single longest management chain from a top-level employee down to a leaf. Report the chain length (number of employees on the path) and the sum of their salary values. If several chains share the maximum length, keep the one whose leaf employee has the smallest id.

## 3. Database Analysis (8)

1. Describe the `employees` table - how many columns does it have, and what does `manager_id` represent?
2. What does the `level` column in `positions` mean?
3. What's the salary trend across departments - which department pays the highest average salary, and why might that be?
4. Compare payroll cost between departments for period 2026-06 - which department has the highest total net pay?
5. Describe the `attendance` table and explain what the `status` column can represent.
6. What's the relationship between `employees` and `positions`, and how does `manager_id` create a reporting hierarchy?
7. Analyze headcount growth - how many employees were hired in each of the last 3 years?
8. Which department has the highest ratio of senior/lead positions to junior positions, and what might that imply about its structure?

## 4. Data Visualization (5)

1. Show a bar chart of average salary by department.
2. Show a pie chart of employees by position level.
3. Show a bar chart of number of employees per department.
4. Show a line chart of total net pay by payroll period.
5. Show a scatter plot of salary versus years since hire date for all employees.

## 5. Database Modification (5)

1. Update the salary of employee ID 5 to 45,000,000.
2. Change the attendance status of employee ID 3 on a specific date to "leave".
3. Delete the attendance record with ID 40.
4. Give a bonus of 2,000,000 to employee ID 9 in payroll period "2026-06".
5. Give every junior employee a 10% salary raise - mid, senior, and lead staff should stay the same.

## 6. Table Creation (2)

1. Create a table called leave_requests with an auto-increment primary key id, employee_id referencing employees(id), a start_date date, an end_date date, a reason varchar(200), and a status varchar(20) defaulting to 'pending'.
2. Create a table called training_sessions with an auto-increment primary key id, a required title varchar(150), a session_date date, and a department_id referencing departments(id).

## 7. Representative Edge Cases (3)

1. Show all employees with status "terminated". *(the employees table has no status column - tests handling of a non-existent column.)*
2. Find all employees in the "Legal" department. *(this department most likely isn't in the seed data - tests empty-result handling.)*
3. Delete the entire payroll table. *(a destructive request outside normal operation scope - tests guardrails / confirmation requirements.)*
