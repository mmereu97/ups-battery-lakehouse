# Databricks notebook source
# MAGIC %md
# MAGIC # 02 — Silver: normalize the messy reality of battery specs
# MAGIC
# MAGIC | Table | Grain |
# MAGIC |---|---|
# MAGIC | `silver.batteries` | one row per shop product (key: `url`) |
# MAGIC | `silver.batteries_rejected` | quarantined rows + reasons |
# MAGIC | `silver.oem_equivalences` | product × equivalent OEM part number |
# MAGIC | `silver.device_compat` | UPS device × compatible product |
# MAGIC | `silver.datasheet_specs` | one row per datasheet PDF |
# MAGIC
# MAGIC Domain normalizations (the heart of this project):
# MAGIC * **Dutch numbers**: `"4.500 mAh"` = 4500 mAh = 4.5 Ah, `"4,5 Ah"` = 4.5 Ah
# MAGIC * **Dimensions** `"151 x 65 x 94 mm"` → numeric L / W / H
# MAGIC * **Terminals**: shops say T1/T2, datasheets say F1/F2 — same thing
# MAGIC   (T1 = F1 = 4.8 mm faston, T2 = F2 = 6.35 mm) → one normalized code
# MAGIC * **Packs**: a 48 V cartridge is 4 × 12 V batteries in series →
# MAGIC   `pack_units = voltage / 12`
# MAGIC * **APC RBC codes** extracted from titles (`RBC2`, `APCRBC140`, ...)
# MAGIC * **High-rate models** encode watts/cell in the part number (`HR1234W` → 34 W)

# COMMAND ----------

from pyspark.sql import functions as F

CATALOG = "ups_batteries"
shop = spark.table(f"{CATALOG}.bronze.shop_raw")

# COMMAND ----------

# MAGIC %md
# MAGIC ## silver.batteries

# COMMAND ----------

prod = shop.filter(F.col("record_type") == "product")

spec = lambda name: F.col("specs_raw").getField(name)

# Serverless runs Spark in ANSI mode: casting '' (a non-matching
# regexp_extract) raises instead of returning NULL — so blank out empties
# before every cast.
def num(col, dtype="int"):
    return F.nullif(col, F.lit("")).cast(dtype)

# -- capacity: "7 Ah" / "4,5 Ah" / "7.000 mAh" / "8.400 mAh" ------------------
cap_raw = spec("Capaciteit")
cap_num = F.regexp_replace(F.regexp_extract(cap_raw, r"([\d.,]+)", 1), r"\.", "")
capacity_ah = (
    F.when(cap_raw.rlike("(?i)mAh"),
           num(F.regexp_replace(cap_num, ",", "."), "double") / 1000)
    .otherwise(
        num(F.regexp_replace(F.regexp_extract(cap_raw, r"([\d,]+)", 1), ",", "."),
            "double"))
)

# -- terminal: specs when present, else "(... T1 terminal)" in the title;
#    normalize T-codes and F-codes to one family ------------------------------
terminal_raw = F.coalesce(
    spec("Aansluiting"), spec("Bodembevestiging"),
    F.regexp_extract(F.col("title"), r"\b([TF]\d)\s*terminal", 1),
)
terminal = F.when(terminal_raw.isin("T1", "F1"), "F1(4.8mm)") \
            .when(terminal_raw.isin("T2", "F2"), "F2(6.35mm)") \
            .otherwise(F.nullif(terminal_raw, F.lit("")))

voltage_v = num(F.regexp_extract(spec("Voltage"), r"(\d+)", 1))

batteries = prod.select(
    F.col("url"),
    F.col("title"),
    F.col("brand"),
    F.coalesce(F.col("model"), spec("Model")).alias("model"),
    voltage_v.alias("voltage_v"),
    capacity_ah.alias("capacity_ah"),
    num(F.regexp_extract(spec("Afmetingen"), r"(\d+)\s*x", 1)).alias("length_mm"),
    num(F.regexp_extract(spec("Afmetingen"), r"x\s*(\d+)\s*x", 1)).alias("width_mm"),
    num(F.regexp_extract(spec("Afmetingen"), r"x\s*(\d+)\s*mm", 1)).alias("height_mm"),
    terminal.alias("terminal"),
    F.when(F.upper(F.coalesce(spec("Batterij type"), F.col("title"))).contains("GEL"), "GEL")
     .when(F.upper(F.coalesce(spec("Batterij type"), F.lit(""))).contains("AGM"), "AGM")
     .alias("chemistry"),
    spec("Type").alias("product_type"),
    F.col("price_eur"),
    F.col("availability"),
    F.array_distinct(
        F.expr(r"regexp_extract_all(title, r'(?:APC)?RBC\s?(\d+)', 1)")
    ).alias("rbc_codes"),
    num(F.regexp_extract(F.col("title"), r"HR12(\d+)W", 1)).alias("watts_per_cell"),
    F.col("replaced_numbers"),
    F.col("datasheet_url"),
    F.col("scraped_at").cast("timestamp").alias("scraped_at"),
    F.col("_source_file"),
    F.col("_ingested_at"),
)

# pack detection: cartridges above 12 V are N x 12 V in series
batteries = (
    batteries
    .withColumn("is_pack",
                (F.col("voltage_v") > 12) | F.col("title").rlike("(?i)vervangingsset|cartridge"))
    .withColumn("pack_units",
                F.when((F.col("voltage_v") > 12) & (F.col("voltage_v") % 12 == 0),
                       (F.col("voltage_v") / 12).cast("int"))
                 .when(F.col("voltage_v") <= 12, F.lit(1)))
)

# keep only the newest observation per product (several crawl files)
from pyspark.sql.window import Window
w = Window.partitionBy("url").orderBy(F.col("scraped_at").desc())
batteries = batteries.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").drop("_rn")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Data quality: quarantine pattern

# COMMAND ----------

checks = {
    "missing_voltage": F.col("voltage_v").isNull(),
    "implausible_voltage": F.col("voltage_v").isNotNull()
        & ~F.col("voltage_v").isin(3, 6, 12, 24, 36, 48, 50, 72, 96, 120, 192, 240),
    "missing_capacity": F.col("capacity_ah").isNull(),
    "implausible_capacity": F.col("capacity_ah").isNotNull()
        & ~F.col("capacity_ah").between(0.1, 300),
    "implausible_dimensions": F.col("length_mm").isNotNull()
        & (~F.col("length_mm").between(10, 700) | ~F.col("width_mm").between(10, 400)),
    "negative_price": F.col("price_eur") < 0,
    "not_a_battery": ~F.upper(F.coalesce(F.col("product_type"), F.lit("")))
        .contains("ACCU"),
}
flagged = batteries.withColumn(
    "rejection_reasons",
    F.array_compact(F.array(*[F.when(c, F.lit(n)) for n, c in checks.items()])),
)
rejected = flagged.filter(F.size("rejection_reasons") > 0)
valid = flagged.filter(F.size("rejection_reasons") == 0).drop("rejection_reasons")

rejected.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.silver.batteries_rejected")
valid.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.silver.batteries")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Normalized one-to-many tables

# COMMAND ----------

sb = spark.table(f"{CATALOG}.silver.batteries")

oem = (
    sb.select("url", "model", F.explode("replaced_numbers").alias("oem_code"))
    .withColumn("oem_code", F.trim("oem_code"))
    .filter(F.col("oem_code") != "")
)
oem.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.silver.oem_equivalences")

compat = (
    shop.filter(F.col("record_type") == "device_compat")
    .select(
        F.col("device_title"),
        F.col("device_breadcrumb").getItem(2).alias("device_brand"),
        F.col("url").alias("device_page_url"),
        F.explode("product_urls").alias("product_url"),
        F.col("scraped_at").cast("timestamp").alias("scraped_at"),
    )
    .dropDuplicates(["device_title", "product_url"])
)
compat.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.silver.device_compat")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Datasheet specs (document-extracted)

# COMMAND ----------

ds = spark.table(f"{CATALOG}.bronze.datasheets_raw")
datasheets = ds.select(
    "file", "part_number",
    F.col("voltage_v").cast("double").alias("voltage_v"),
    F.col("capacity_ah").cast("double").alias("capacity_ah"),
    F.col("length_mm").cast("double").alias("length_mm"),
    F.col("width_mm").cast("double").alias("width_mm"),
    F.col("container_height_mm").cast("double").alias("container_height_mm"),
    F.col("total_height_mm").cast("double").alias("total_height_mm"),
    F.col("weight_kg").cast("double").alias("weight_kg"),
    "terminal",
    F.col("max_discharge_a").cast("double").alias("max_discharge_a"),
    F.col("internal_resistance_mohm").cast("double").alias("internal_resistance_mohm"),
    F.col("design_life_years").cast("double").alias("design_life_years"),
    F.col("fields_parsed").cast("int").alias("fields_parsed"),
    "_source_file", "_ingested_at",
)
datasheets.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.silver.datasheet_specs")

# COMMAND ----------

for t in ["batteries", "batteries_rejected", "oem_equivalences", "device_compat", "datasheet_specs"]:
    print(f"silver.{t:20}: {spark.table(f'{CATALOG}.silver.{t}').count():>6} rows")
display(spark.table(f"{CATALOG}.silver.batteries")
        .select("brand", "model", "voltage_v", "capacity_ah", "length_mm", "width_mm",
                "height_mm", "terminal", "chemistry", "is_pack", "pack_units",
                "rbc_codes", "price_eur").limit(10))
display(spark.table(f"{CATALOG}.silver.batteries_rejected")
        .select("title", "voltage_v", "capacity_ah", "product_type", "rejection_reasons"))
