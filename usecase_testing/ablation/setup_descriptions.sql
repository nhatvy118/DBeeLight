-- Table-level descriptions (column_name = '' means table-level)
INSERT INTO _descriptions (table_name, column_name, description) VALUES
('custs',     '', 'Registered customers (buyers) on the platform.'),
('cats',      '', 'Hierarchical product classification. par_id=NULL means root (top-level) category.'),
('prods',     '', 'Products available for sale. prc is the retail price shown to customers.'),
('sups',      '', 'Suppliers (vendors) that provide products to the platform.'),
('prod_sup',  '', 'Many-to-many link between products and their suppliers. sup_prc is the wholesale cost paid to the supplier.'),
('ords',      '', 'Customer purchase orders. ord_amt is the total revenue value of the order.'),
('ord_lines', '', 'Individual line items within an order — one row per product per order.'),
('rvws',      '', 'Customer reviews and satisfaction scores for purchased products.');

-- Column-level descriptions
INSERT INTO _descriptions (table_name, column_name, description, enum_values) VALUES
('custs', 'cust_nm', 'Customer full name.', NULL),
('custs', 'crt_ts',  'Timestamp when the customer account was created.', NULL),
('cats',  'par_id',  'Parent category ID. NULL means this is a top-level (root) category with no parent.', NULL),
('prods', 'prc',     'Retail selling price charged to the customer.', NULL),
('prods', 'inv_qty', 'Inventory quantity in stock. 0 means the product is out of stock.', NULL),
('prods', 'cat_id',  'The category this product belongs to.', NULL),
('prod_sup', 'sup_prc', 'Wholesale cost paid to the supplier. Gross margin = prods.prc - prod_sup.sup_prc.', NULL),
('ords', 'sts_cd',  'Order status code. P=pending (not yet paid), P2=paid, S=shipped, C=cancelled.', '["P","P2","S","C"]'),
('ords', 'ord_amt', 'Total monetary value of the order — represents revenue from this transaction.', NULL),
('ords', 'crt_ts',  'Timestamp when the order was placed.', NULL),
('ord_lines', 'qty',   'Number of units purchased in this line item.', NULL),
('ord_lines', 'u_prc', 'Per-unit price at which the product was sold in this order.', NULL),
('rvws', 'cust_rtg', 'Customer satisfaction score: 1=very poor to 5=excellent.', '[1,2,3,4,5]'),
('rvws', 'cmt',      'Customer written feedback comment.', NULL);
