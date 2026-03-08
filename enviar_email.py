import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import ssl
import os
import glob
import re
import yaml
from datetime import datetime

def carregar_configuracao(caminho_config='config.yaml'):
    try:
        with open(caminho_config, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"❌ Erro ao ler {caminho_config}: {e}")
        return None

def registrar_log(login, status, erro=""):
    """Salva o status do envio em um arquivo CSV."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp};{login};{status};{erro}\n"
    with open("log_envios.csv", "a", encoding="utf-8") as f:
        f.write(log_line)

def envia_email(session, FROM, TO, CC, subject, texto, anexo=[]):
    """Envia o e-mail usando uma sessão SMTP já aberta."""
    msg = MIMEMultipart()
    msg['From'] = FROM
    msg['To'] = TO
    msg['Cc'] = ', '.join(CC) if isinstance(CC, list) else CC
    msg['Subject'] = subject
    msg.attach(MIMEText(texto, 'plain'))

    for f in anexo:
        try:
            if os.path.exists(f):
                with open(f, 'rb') as file:
                    part = MIMEBase('text', 'plain')
                    part.set_payload(file.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(f)}"')
                    msg.attach(part)
        except Exception as e:
            print(f"Erro ao anexar {f}: {e}")

    try:
        recipients = [TO] + (CC if isinstance(CC, list) else [CC])
        session.sendmail(FROM, recipients, msg.as_string())
        print(f"✅ E-mail enviado: {TO}")
        return True, ""
    except Exception as e:
        print(f"❌ Erro ao enviar para {TO}: {e}")
        return False, str(e)


def extrair_login_nome(pasta_nome):
    match = re.search(r' - ([^-]+)$', pasta_nome.strip())
    return match.group(1).strip() if match else None

def buscar_rubrica_txt(pasta_base):
    rubricas_encontradas = []
    try:
        items = sorted(os.listdir(pasta_base), key=lambda x: x.lower())
        for item in items:
            caminho_completo = os.path.join(pasta_base, item)
            if os.path.isdir(caminho_completo) and ' - ' in item:
                login = extrair_login_nome(item)
                if login:
                    pattern = os.path.join(caminho_completo, '**', 'rubrica.txt')
                    arquivos = glob.glob(pattern, recursive=True)
                    if arquivos:
                        rubricas_encontradas.append({
                            'login': login,
                            'nome_pasta': item,
                            'arquivo_rubrica': arquivos[0],
                            'email': f"{login}@ufabc.edu.br"
                            #'email': f"{login}@aluno.ufabc.edu.br"
                        })
    except Exception as e:
        print(f"Erro na busca: {e}")
    return rubricas_encontradas

def ler_nota_rubrica(arquivo_rubrica):
    try:
        with open(arquivo_rubrica, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        nota_info = next((l.strip() for l in conteudo.split('\n') if any(p in l.lower() for p in ['nota', 'total', 'pontos'])), "Info não encontrada")
        return conteudo, nota_info
    except:
        return "", "Erro na leitura"

def gerar_texto_email(template_corpo, login, nome_pasta, nota_info):
    """Preenche o template do YAML com os dados do aluno."""
    return template_corpo.format(
        login=login, 
        nome_pasta=nome_pasta, 
        nota_info=nota_info
    )

def main():
    config = carregar_configuracao()
    if not config: return

    email_cfg = config.get('email', {})
    paths_cfg = config.get('paths', {})
    template_cfg = config.get('templates', {})
    
    pasta_base = paths_cfg.get('student_base_dir', 'Simulado0')
    rubricas = buscar_rubrica_txt(pasta_base)
    
    if not rubricas: return

    # Inicia Sessão SMTP única
    context = ssl.create_default_context()
    context.set_ciphers("DEFAULT@SECLEVEL=1")

    try:
        with smtplib.SMTP(email_cfg['smtp_server'], email_cfg['smtp_port']) as server:
            server.ehlo()
            server.starttls(context=context)
            server.login(email_cfg['from_address'], email_cfg['password'])

            for dados in sorted(rubricas, key=lambda x: x['nome_pasta'].lower()):
                login = dados['login']
                nome_pasta = dados['nome_pasta']
                _, nota_info = ler_nota_rubrica(dados['arquivo_rubrica'])

                texto_email = template_cfg.get('corpo', "").format(
                    login=login, nome_pasta=nome_pasta, nota_info=nota_info
                )
                assunto = template_cfg.get('assunto', "").format(login=login)

                # DESTINATÁRIO (ajuste aqui para produção ou teste)
                email_to = f"{login}@aluno.ufabc.edu.br" 
                email_to = "fzampirolli@gmail.com" # TESTE

                # Envio e Log
                sucesso, erro = envia_email(server, email_cfg['from_address'], email_to, [], assunto, texto_email, [dados['arquivo_rubrica']])
                
                status_str = "SUCESSO" if sucesso else "ERRO"
                registrar_log(login, status_str, erro)

    except Exception as e:
        print(f"❌ Erro crítico na conexão SMTP: {e}")

if __name__ == "__main__":
    # Cria cabeçalho do log se não existir
    if not os.path.exists("log_envios.csv"):
        with open("log_envios.csv", "w", encoding="utf-8") as f:
            f.write("Data;Login;Status;Detalhes\n")
    main()