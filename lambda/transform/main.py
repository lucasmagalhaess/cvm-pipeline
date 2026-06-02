import boto3
import json
import os
from datetime import datetime, timezone

S3_BUCKET = os.environ.get("S3_BUCKET", "cvm-pipeline-data-lake")

def read_from_s3(key):
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=S3_BUCKET, Key=key)
    return json.loads(response["Body"].read().decode("utf-8"))

def save_to_s3(data, key):
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json"
    )
    print(f"Salvo no S3: s3://{S3_BUCKET}/{key}")

def get_trimestre(dt_refer):
    mes = int(dt_refer[5:7])
    if mes <= 3:
        return "Q1"
    elif mes <= 6:
        return "Q2"
    elif mes <= 9:
        return "Q3"
    else:
        return "Q4"

def classificar_margem(margem):
    if margem is None:
        return "sem_dados"
    elif margem >= 20:
        return "alta"
    elif margem >= 10:
        return "media"
    elif margem >= 0:
        return "baixa"
    else:
        return "prejuizo"

def transform(bronze_key):
    print(f"Lendo bronze: {bronze_key}")
    raw_data = read_from_s3(bronze_key)

    registros = raw_data.get("registros", [])
    extraction_date = raw_data.get("extraction_date")
    extraction_timestamp = raw_data.get("extraction_timestamp")

    # Agrupa por empresa e trimestre
    empresas = {}
    for r in registros:
        empresa = r["empresa"]
        dt_refer = r["dt_refer"]
        key = f"{empresa}_{dt_refer}"

        if key not in empresas:
            empresas[key] = {
                "empresa": empresa,
                "cnpj": r["cnpj"],
                "dt_refer": dt_refer,
                "trimestre": get_trimestre(dt_refer),
                "ano": dt_refer[:4],
                "moeda": r["moeda"],
                "receita_liquida": None,
                "lucro_liquido": None,
            }

        valor_reais = r["vl_conta"] * 1000
        if r["ds_conta"] == "Receita Liquida":
            empresas[key]["receita_liquida"] = valor_reais
        elif r["ds_conta"] == "Lucro Liquido":
            empresas[key]["lucro_liquido"] = valor_reais

    # Calcula métricas silver
    silver_rows = []
    for key, emp in empresas.items():
        receita = emp["receita_liquida"]
        lucro = emp["lucro_liquido"]

        margem = None
        if receita and receita > 0 and lucro is not None:
            margem = round((lucro / receita) * 100, 2)

        silver_rows.append({
            **emp,
            "margem_liquida_pct": margem,
            "classificacao_margem": classificar_margem(margem),
            "extraction_date": extraction_date,
            "extraction_timestamp": extraction_timestamp,
        })

    silver_rows.sort(key=lambda x: x["receita_liquida"] or 0, reverse=True)

    print(f"\nResultados Silver:")
    for r in silver_rows:
        print(f"  {r['empresa']} | Receita: R${r['receita_liquida']:,.0f} | Lucro: R${r['lucro_liquido']:,.0f} | Margem: {r['margem_liquida_pct']}% | {r['classificacao_margem']}")

    return silver_rows, extraction_date, extraction_timestamp

def lambda_handler(event, context):
    try:
        bronze_key = event.get("bronze_key")
        if not bronze_key:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            bronze_key = f"bronze/cvm/{today}/test.json"

        silver_rows, extraction_date, extraction_timestamp = transform(bronze_key)

        silver_key = bronze_key.replace("bronze/", "silver/")
        save_to_s3({
            "extraction_date": extraction_date,
            "extraction_timestamp": extraction_timestamp,
            "total_empresas": len(silver_rows),
            "empresas": silver_rows
        }, silver_key)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success",
                "empresas": len(silver_rows),
                "silver_key": silver_key
            })
        }

    except Exception as e:
        print(f"Erro: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "error", "message": str(e)})
        }
