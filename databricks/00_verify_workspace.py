# Databricks notebook source
# MAGIC %md
# MAGIC # Delivery project: workspace execution check
# MAGIC Run this small read-only cell using the workspace's available serverless compute.
# MAGIC A visible result of `1` is required before recording cloud execution as verified.
# MAGIC No data is uploaded, no table is created, and no paid cluster is configured.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT 1 AS workspace_query_ok;
