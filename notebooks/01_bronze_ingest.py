# Databricks notebook source
# MAGIC %md
# MAGIC # 01 — Bronze: incremental ingestion with COPY INTO
# MAGIC
# MAGIC The scraper lands one timestamped JSONL file per run in the Volume:
# MAGIC
# MAGIC ```
# MAGIC /Volumes/ups_batteries/bronze/raw/products/    accu123_<ts>.jsonl   (products + device_compat edges)
# MAGIC /Volumes/ups_batteries/bronze/raw/datasheets/  datasheets_<ts>.jsonl (PDF-extracted specs)
# MAGIC ```
# MAGIC
# MAGIC **`COPY INTO`** is the incremental-ingestion primitive here: it remembers
# MAGIC which files it already loaded, so re-running this notebook ingests only
# MAGIC *new* files and loading the same file twice is impossible (idempotence
# MAGIC at file level). Upload a new crawl file, run the job again, and only the
# MAGIC increment lands — no bookkeeping code required.

# COMMAND ----------

CATALOG = "ups_batteries"
PRODUCTS_PATH = f"/Volumes/{CATALOG}/bronze/raw/products"
DATASHEETS_PATH = f"/Volumes/{CATALOG}/bronze/raw/datasheets"

# COMMAND ----------

# Schemaless table creation: COPY INTO + mergeSchema infers and evolves the
# schema from the incoming JSON files.
#
# The shop's spec labels contain spaces ("Batterij type", "Extra info") and
# arrive as nested struct fields. Delta rejects such names unless COLUMN
# MAPPING is enabled, which stores physical column ids separately from the
# display names — so the raw labels can be kept exactly as scraped.
spark.sql(f"CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.shop_raw")
spark.sql(f"""
    ALTER TABLE {CATALOG}.bronze.shop_raw SET TBLPROPERTIES (
        'delta.columnMapping.mode' = 'name',
        'delta.minReaderVersion' = '2',
        'delta.minWriterVersion' = '5'
    )
""")
result = spark.sql(f"""
    COPY INTO {CATALOG}.bronze.shop_raw
    FROM (
        SELECT *, current_timestamp() AS _ingested_at,
               _metadata.file_name AS _source_file
        FROM '{PRODUCTS_PATH}'
    )
    FILEFORMAT = JSON
    FORMAT_OPTIONS ('inferSchema' = 'true')
    COPY_OPTIONS ('mergeSchema' = 'true')
""")
display(result)  # num_inserted_rows > 0 on first run, 0 on re-run

# COMMAND ----------

spark.sql(f"CREATE TABLE IF NOT EXISTS {CATALOG}.bronze.datasheets_raw")
result = spark.sql(f"""
    COPY INTO {CATALOG}.bronze.datasheets_raw
    FROM (
        SELECT *, current_timestamp() AS _ingested_at,
               _metadata.file_name AS _source_file
        FROM '{DATASHEETS_PATH}'
    )
    FILEFORMAT = JSON
    FORMAT_OPTIONS ('inferSchema' = 'true')
    COPY_OPTIONS ('mergeSchema' = 'true')
""")
display(result)

# COMMAND ----------

shop = spark.table(f"{CATALOG}.bronze.shop_raw")
ds = spark.table(f"{CATALOG}.bronze.datasheets_raw")
print(f"bronze.shop_raw       : {shop.count():>5} rows "
      f"({shop.select('_source_file').distinct().count()} source files)")
print(f"bronze.datasheets_raw : {ds.count():>5} rows")
display(shop.groupBy("record_type", "_source_file").count())
