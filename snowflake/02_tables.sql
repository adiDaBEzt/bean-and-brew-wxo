-- 02_tables.sql: core tables. Run as BB_ADMIN.
USE ROLE BB_ADMIN;
USE WAREHOUSE BB_WH;
USE SCHEMA BEAN_BREW.CORE;

CREATE OR REPLACE TABLE STORES (
  store_id STRING, name STRING, region STRING, city STRING
);

-- region is denormalised onto every table so row access policies stay simple and fast.
CREATE OR REPLACE TABLE SALES (
  order_id NUMBER, store_id STRING, region STRING, product STRING,
  qty NUMBER, amount NUMBER(10,2), ts TIMESTAMP_NTZ
);

CREATE OR REPLACE TABLE INVENTORY (
  store_id STRING, region STRING, sku STRING, item STRING,
  on_hand NUMBER, reorder_level NUMBER, updated_at TIMESTAMP_NTZ
);

CREATE OR REPLACE TABLE EMPLOYEES (
  emp_id STRING, name STRING, email STRING, phone STRING,
  store_id STRING, region STRING, role STRING, salary NUMBER(10,2), hire_date DATE
);
