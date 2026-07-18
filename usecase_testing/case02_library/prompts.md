# Case Study 2: Library Management — Test Prompts (20 operations)

Schema: `authors`, `books`, `members`, `loans`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `authors`, `books`, `members`, `loans`.
Route split: 8 `db_readonly` / 4 `db_general` / 4 `chart` / 2 `db_mutation` / 2 `db_create_table` (balanced default).

## db_readonly (8)

1. List all books sorted by published year, newest first.
2. Find all books that have more than 3 copies available.
3. Get all members who joined in 2025.
4. Find all loans that have not been returned yet.
5. Get a list of books along with their author's name.
6. Show all loans along with the member's full name and the book title.
7. Count how many books each author has written.
8. Find members who currently have an overdue loan (due date has passed and it has not been returned).

## db_general (4 — schema explanation / multi-step analysis)

9. Describe the `books` table — how many columns does it have and what does each represent?
10. What does the `membership_type` column in `members` mean?
11. What's the trend in number of loans per month this year — is borrowing activity increasing?
12. Compare borrowing activity between premium and standard members — which group borrows more, and by how much?

## chart (4)

13. Show a bar chart of number of books per author.
14. Show a pie chart of members by membership type.
15. Show a line chart of number of loans per month in 2026.
16. Show a bar chart of the top 5 most-borrowed books.

## db_mutation (2)

17. Reduce the copies available of "the book with ID 4" by 1.
18. Mark loan ID 5 as returned by setting its return date to today.

## db_create_table (2)

19. Create a table called `reservations` to let members reserve a book that is currently unavailable: an auto-increment primary key `id`, `book_id` referencing `books(id)`, `member_id` referencing `members(id)`, and a `reserved_at` timestamp defaulting to now.
20. Create a table called `fines` with an auto-increment primary key `id`, `loan_id` referencing `loans(id)`, an `amount` decimal(10,2), and a `paid` boolean defaulting to false.
