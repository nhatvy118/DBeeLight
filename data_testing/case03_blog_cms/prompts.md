# Case Study 3: Blog / CMS — Test Prompts (20 operations)

Schema: `users`, `posts`, `comments`, `tags`, `post_tags`.
Setup: run `schema.sql` first, then import `seed_data/*.xlsx` with **append to existing table** mode, in this order: `users`, `posts`, `tags`, `comments`, `post_tags`.
Route split: 8 `db_readonly` / 4 `db_general` / 4 `chart` / 2 `db_mutation` / 2 `db_create_table` (balanced default).

## db_readonly (8)

1. List all published posts sorted by publish date, newest first.
2. Find all posts written by a specific user (by username).
3. Get the top 5 most-commented posts.
4. Find all comments that are replies to another comment.
5. Get a list of posts along with the author's full name.
6. Show each tag along with the number of posts using it.
7. Find all draft posts that have never been published.
8. Get all comments on a specific post along with the commenter's username.

## db_general (4 — schema explanation / multi-step analysis)

9. Describe the `posts` table — how many columns does it have, and what does the `status` column mean?
10. What does the `parent_comment_id` column in `comments` represent?
11. What's the trend in number of posts published per month — is content output increasing?
12. Compare engagement (average comments per post) between "tech" and "travel" tagged posts — which topic gets more discussion?

## chart (4)

13. Show a bar chart of number of posts per tag.
14. Show a pie chart of posts by status (draft vs. published).
15. Show a line chart of number of posts published per month in 2025.
16. Show a bar chart of the top 5 users by number of posts written.

## db_mutation (2)

17. Change the status of post ID 3 from "draft" to "published".
18. Update the content of comment ID 10 to "Edited: thanks for the feedback!".

## db_create_table (2)

19. Create a table called `post_likes` to track which users liked which posts: an auto-increment primary key `id`, `post_id` referencing `posts(id)`, `user_id` referencing `users(id)`, and a `liked_at` timestamp defaulting to now.
20. Create a table called `newsletter_subscribers` with an auto-increment primary key `id`, a unique required `email` varchar(150), and a `subscribed_at` timestamp defaulting to now.
