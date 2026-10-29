# Databricks notebook source
# MAGIC %md
# MAGIC # 04 — Price history as SCD Type 2
# MAGIC
# MAGIC Each crawl file is a snapshot of shop prices. `gold.price_history` keeps
# MAGIC **every price a product ever had**, as a Slowly Changing Dimension type 2:
# MAGIC
# MAGIC | url | price_eur | valid_from | valid_to | is_current |
# MAGIC |---|---|---|---|---|
# MAGIC | .../UL7-12... | 18.95 | 2026-10-28 | 2026-11-02 | false |
# MAGIC | .../UL7-12... | 17.50 | 2026-11-02 | null | true |
# MAGIC
# MAGIC Implemented with `MERGE INTO`, processing crawl batches in order: a changed
# MAGIC price *closes* the current row (sets `valid_to`) and inserts a new current
# MAGIC one; an unchanged price touches nothing. The notebook ends with a
# MAGIC simulated price change to prove the mechanics, then `RESTORE`s the table —
# MAGIC Delta time travel as the undo button, same pattern as the Cinemateca demo.

# COMMAND ----------

from pyspark.sql import functions as F

CATALOG = "ups_batteries"
HIST = f"{CATALOG}.gold.price_history"

spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {HIST} (
        url STRING, title STRING, price_eur DOUBLE,
        valid_from TIMESTAMP, valid_to TIMESTAMP, is_current BOOLEAN
    )
""")

# COMMAND ----------

def apply_snapshot(snap_df) -> None:
    """SCD2 upsert of one price snapshot into gold.price_history."""
    snap_df.createOrReplaceTempView("price_snapshot")
    # 1. close current rows whose price changed
    spark.sql(f"""
        MERGE INTO {HIST} AS t
        USING price_snapshot AS s
        ON t.url = s.url AND t.is_current = true
        WHEN MATCHED AND t.price_eur <> s.price_eur THEN
            UPDATE SET t.valid_to = s.observed_at, t.is_current = false
    """)
    # 2. insert a row for new products and for just-closed changes
    spark.sql(f"""
        MERGE INTO {HIST} AS t
        USING price_snapshot AS s
        ON t.url = s.url AND t.is_current = true
        WHEN NOT MATCHED THEN
            INSERT (url, title, price_eur, valid_from, valid_to, is_current)
            VALUES (s.url, s.title, s.price_eur, s.observed_at, NULL, true)
    """)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Replay the real crawl batches, oldest first

# COMMAND ----------

shop = spark.table(f"{CATALOG}.bronze.shop_raw").filter("record_type = 'product'")
batches = [r["_source_file"] for r in
           shop.select("_source_file").distinct()
               .orderBy("_source_file").collect()]

for batch in batches:
    snap = (
        shop.filter(F.col("_source_file") == batch)
        .filter(F.col("price_eur").isNotNull())
        .select("url", "title", "price_eur",
                F.col("scraped_at").cast("timestamp").alias("observed_at"))
        .dropDuplicates(["url"])
    )
    apply_snapshot(snap)
    hist = spark.table(HIST)
    print(f"batch {batch}: history rows={hist.count()}, "
          f"current={hist.filter('is_current').count()}, "
          f"closed={hist.filter('NOT is_current').count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Prove the mechanics: simulate a price change, then undo it

# COMMAND ----------

pre_version = spark.sql(f"DESCRIBE HISTORY {HIST}").select("version").first()[0]

# Materialize the demo row FIRST (collect), then build a literal snapshot.
# A lazy DataFrame over price_history would be re-evaluated mid-MERGE,
# after the first MERGE already changed the table — classic lazy-eval trap.
row = spark.table(HIST).filter("is_current").first()
demo_url = row["url"]
demo = spark.createDataFrame(
    [(row["url"], row["title"], row["price_eur"] + 5.00)],
    "url string, title string, price_eur double",
).withColumn("observed_at", F.current_timestamp())
apply_snapshot(demo)

print("After a simulated +5 EUR price change:")
display(spark.table(HIST).filter(F.col("url") == demo_url)
        .orderBy("valid_from"))

# COMMAND ----------

spark.sql(f"RESTORE TABLE {HIST} TO VERSION AS OF {pre_version}")
after = spark.table(HIST).filter(F.col("url") == demo_url).count()
print(f"Restored to version {pre_version} — demo rows gone, "
      f"rows for that product back to {after}.")
