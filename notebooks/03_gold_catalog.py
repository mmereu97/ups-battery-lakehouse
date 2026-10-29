# Databricks notebook source
# MAGIC %md
# MAGIC # 03 — Gold: the compatibility product
# MAGIC
# MAGIC This layer answers the question that started the project: *"my UPS needs
# MAGIC a new battery — what actually fits?"*
# MAGIC
# MAGIC | Table | Content |
# MAGIC |---|---|
# MAGIC | `gold.battery_catalog` | shop data enriched with PDF datasheet specs |
# MAGIC | `gold.equivalence_groups` | batteries interchangeable by electrical spec |
# MAGIC | `gold.oem_lookup` | OEM part number → purchasable products |
# MAGIC | `gold.device_lookup` | UPS model → compatible batteries with price |
# MAGIC
# MAGIC Ends with **validation**: the replacement-search rule is asserted against
# MAGIC a real case from the owner's own UPS fleet (see docs/VALIDATION_CASES.md):
# MAGIC a naive V+Ah match suggests 65 mm-wide batteries for a bay that is 51 mm
# MAGIC wide. The dimension rule ("candidate must be ≤ original, never bigger")
# MAGIC must exclude them.

# COMMAND ----------

from pyspark.sql import functions as F

CATALOG = "ups_batteries"
sb = spark.table(f"{CATALOG}.silver.batteries")
ds = spark.table(f"{CATALOG}.silver.datasheet_specs")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Catalog enriched with datasheet specs
# MAGIC Shop pages don't publish discharge current, internal resistance or design
# MAGIC life — the PDFs do. Joined on part number.

# COMMAND ----------

ds_match = ds.select(
    F.upper("part_number").alias("pn"),
    F.col("weight_kg"),
    F.col("max_discharge_a"),
    F.col("internal_resistance_mohm"),
    F.col("design_life_years"),
    F.col("total_height_mm").alias("ds_total_height_mm"),
).dropDuplicates(["pn"])

catalog = (
    sb.join(ds_match, F.upper(sb.model) == ds_match.pn, "left")
    .drop("pn")
)
catalog.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.gold.battery_catalog")
n_enriched = catalog.filter("max_discharge_a IS NOT NULL").count()
print(f"catalog rows: {catalog.count()}, enriched from datasheets: {n_enriched}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Equivalence groups (single batteries, not packs)
# MAGIC Same voltage + capacity (±5%) puts batteries in one electrical family;
# MAGIC the OEM cross-reference lists confirm it independently.

# COMMAND ----------

singles = sb.filter((F.col("is_pack") == False) & F.col("capacity_ah").isNotNull())

groups = (
    singles
    .withColumn("capacity_bucket", F.round(F.col("capacity_ah")).cast("int"))
    .groupBy("voltage_v", "capacity_bucket")
    .agg(
        F.count("*").alias("members"),
        F.collect_list(F.struct("brand", "model", "width_mm", "terminal", "price_eur"))
         .alias("batteries"),
        F.round(F.min("price_eur"), 2).alias("cheapest_eur"),
        F.round(F.max("price_eur"), 2).alias("priciest_eur"),
    )
    .filter(F.col("members") >= 1)
    .orderBy("voltage_v", "capacity_bucket")
)
groups.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.gold.equivalence_groups")
display(spark.table(f"{CATALOG}.gold.equivalence_groups").filter("members >= 2"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## OEM lookup: "my dead battery says NP7-12 — what do I buy?"

# COMMAND ----------

oem = spark.table(f"{CATALOG}.silver.oem_equivalences")
oem_lookup = (
    oem.select("url", "oem_code")   # drop oem.model: it would clash with sb.model
    .join(sb.select("url", "brand", "model", "voltage_v", "capacity_ah",
                    "price_eur", "availability"), "url")
    .select("oem_code", "brand", "model", "voltage_v", "capacity_ah",
            "price_eur", "availability", "url")
)
oem_lookup.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.gold.oem_lookup")
print("Example — replacements sold for OEM code 'NP7-12':")
display(spark.table(f"{CATALOG}.gold.oem_lookup").filter("oem_code = 'NP7-12'"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Device lookup: UPS model → batteries, with price

# COMMAND ----------

compat = spark.table(f"{CATALOG}.silver.device_compat")
device_lookup = (
    compat.join(sb.withColumnRenamed("url", "product_url"), "product_url")
    .select("device_brand", "device_title", "brand", "model", "title",
            "voltage_v", "capacity_ah", "pack_units", "price_eur", "product_url")
    .orderBy("device_brand", "device_title")
)
device_lookup.write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(f"{CATALOG}.gold.device_lookup")
print(f"device_lookup: {device_lookup.count()} device-battery pairs, "
      f"{device_lookup.select('device_title').distinct().count()} devices")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Replacement search + VALIDATION
# MAGIC The rule that makes this useful: a candidate must match voltage, meet the
# MAGIC minimum capacity, and **physically fit** — every dimension ≤ the bay size
# MAGIC (+2 mm tolerance). "Close enough but bigger" does not fit in a UPS.

# COMMAND ----------

def find_replacements(voltage_v, min_capacity_ah, bay_length_mm, bay_width_mm,
                      bay_height_mm, tolerance_mm=2):
    return (
        spark.table(f"{CATALOG}.gold.battery_catalog")
        .filter(
            (F.col("is_pack") == False)
            & (F.col("voltage_v") == voltage_v)
            & (F.col("capacity_ah") >= min_capacity_ah)
            & F.col("length_mm").isNotNull()
            & (F.col("length_mm") <= bay_length_mm + tolerance_mm)
            & (F.col("width_mm") <= bay_width_mm + tolerance_mm)
            & (F.col("height_mm") <= bay_height_mm + tolerance_mm)
        )
        .select("brand", "model", "voltage_v", "capacity_ah",
                "length_mm", "width_mm", "height_mm", "terminal", "price_eur")
        .orderBy("price_eur")
    )

# Real case: APC Back-UPS 500VA — original battery is 151 x 51 x 94 mm.
case = find_replacements(12, 5.0, 151, 51, 94)
print("Candidates that truly fit the 51 mm bay:")
display(case)

# The trap the owner actually hit: standard 12V 7Ah batteries are 65 mm wide.
# A naive V+Ah search would suggest them; the dimension rule must not.
assert case.filter(F.col("width_mm") > 53).count() == 0, \
    "VALIDATION FAILED: a battery wider than the bay was proposed!"
naive = spark.table(f"{CATALOG}.gold.battery_catalog").filter(
    (F.col("is_pack") == False) & (F.col("voltage_v") == 12)
    & (F.col("capacity_ah") >= 5) & (F.col("width_mm") > 53)
).count()
print(f"VALIDATION PASSED — the naive V+Ah match would have offered "
      f"{naive} batteries that physically do not fit; the rule excluded all of them.")
