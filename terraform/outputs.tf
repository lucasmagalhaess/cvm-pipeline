output "bucket_name" {
  value = aws_s3_bucket.data_lake.bucket
}

output "glue_database" {
  value = aws_glue_catalog_database.cvm.name
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda_role.arn
}

output "glue_role_arn" {
  value = aws_iam_role.glue_role.arn
}
