# Serverless ingestion: EventBridge (5 min) -> Lambda -> HTTPS -> pandaproxy.
# Zip built by scripts/build_lambda.sh (arm64, matches `architectures`).

variable "ingest_url" {
  type        = string
  description = "Public ingest base, e.g. https://zia-news.duckdns.org/produce"
}

variable "ingest_api_key" {
  type        = string
  sensitive   = true
  description = "Bearer key Caddy expects on /produce (from .env)"
}

variable "news_feeds" {
  type        = string
  description = "Comma-separated RSS feed URLs (from .env)"
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest_lambda" {
  name               = "news-ai-ingest-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.ingest_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_cloudwatch_log_group" "ingest_lambda" {
  name              = "/aws/lambda/news-ai-ingest"
  retention_in_days = 7
}

resource "aws_lambda_function" "ingest" {
  function_name = "news-ai-ingest"
  role          = aws_iam_role.ingest_lambda.arn
  runtime       = "python3.12"
  architectures = ["arm64"]
  handler       = "handler.lambda_handler"
  timeout       = 60
  memory_size   = 256

  filename         = "${path.module}/../../dist/lambda.zip"
  source_code_hash = filebase64sha256("${path.module}/../../dist/lambda.zip")

  environment {
    variables = {
      NEWS_FEEDS     = var.news_feeds
      PANDAPROXY_URL = var.ingest_url
      INGEST_API_KEY = var.ingest_api_key
      KAFKA_TOPIC    = "news.raw"
      LOG_LEVEL      = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingest_lambda]
}

resource "aws_cloudwatch_event_rule" "every_5_min" {
  name                = "news-ai-ingest-schedule"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "ingest" {
  rule = aws_cloudwatch_event_rule.every_5_min.name
  arn  = aws_lambda_function.ingest.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.every_5_min.arn
}

output "lambda_name" {
  value = aws_lambda_function.ingest.function_name
}
