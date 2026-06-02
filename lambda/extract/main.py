import boto3
import requests
import zipfile
import io
import csv
import json
import os
from datetime import datetime, timezone

S3_BUCKET = os.environ.get("S3_BUCKET", "cvm-pipeline-data-lake")

# CNPJs das principais empresas da B3
EMPRESAS = {
    "00.000.000/0001-91": "Banco do Brasil",
    "33.000.167/0001-01": "Petrobras",
    "33.592.510/0001-54": "Vale",
    "60.746.948/0001-12": "Itaú Unibanco",
    "60.038.016/0001-58": "Bradesco",
    "00.348.700/0001-00": "WEG",
    "07.526.557/0001-00": "Magazine Luiza",
    "07.237.373/0001-20": "Ambev",
}

def download_and_extract(ano):
    url = f"https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS/itr_cia_aberta_{ano}.zip"
    print(f"Baixando dados da CVM para {ano}...")
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(response.content))

def parse_dre(zip_file, ano):
    filename = f"itr_cia_aberta_DRE_con_{ano}.csv"
    print(f"Processando {filename}...")
    
    with zip_file.open(filename) as f:
        content = f.read().decode("latin-1")
    
    reader = csv.DictReader(io.StringIO(content), delimiter=";")
    registros = []
    
    contas_interesse = {
        "3.01": "Receita Liquida",
        "3.11": "Lucro Liquido",
        "3.05": "EBIT",
        "3.09": "EBITDA",
    }
    
    for row in reader:
        cnpj = row.get("CNPJ_CIA", "").strip()
        cd_conta = row.get("CD_CONTA", "").strip()
        ordem = row.get("ORDEM_EXERC", "").strip()
        
        if cnpj in EMPRESAS and cd_conta in contas_interesse and ordem == "ÚLTIMO":
            registros.append({
                "cnpj": cnpj,
                "empresa": EMPRESAS[cnpj],
                "dt_refer": row.get("DT_REFER", "").strip(),
                "dt_ini_exerc": row.get("DT_INI_EXERC", "").strip(),
                "dt_fim_exerc": row.get("DT_FIM_EXERC", "").strip(),
                "cd_conta": cd_conta,
                "ds_conta": contas_interesse[cd_conta],
                "vl_conta": float(row.get("VL_CONTA", 0) or 0),
                "escala_moeda": row.get("ESCALA_MOEDA", "").strip(),
                "moeda": row.get("MOEDA", "").strip(),
            })
    
    return registros

def save_to_s3(data, key):
    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(data, ensure_ascii=False, indent=2),
        ContentType="application/json"
    )
    print(f"Salvo no S3: s3://{S3_BUCKET}/{key}")

def lambda_handler(event, context):
    try:
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S")
        ano = now.year

        print(f"Iniciando extracao CVM {ano}...")
        zip_file = download_and_extract(ano)
        registros = parse_dre(zip_file, ano)
        print(f"Registros encontrados: {len(registros)}")

        payload = {
            "extraction_date": today,
            "extraction_timestamp": timestamp,
            "ano": ano,
            "total_registros": len(registros),
            "registros": registros
        }

        key = f"bronze/cvm/{today}/dre_{timestamp.replace(':', '-')}.json"
        save_to_s3(payload, key)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "success",
                "registros": len(registros),
                "file": key
            })
        }

    except Exception as e:
        print(f"Erro: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "error", "message": str(e)})
        }
