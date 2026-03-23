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
        print(f"Erro ao ler {caminho_config}: {e}")
        return None


def registrar_log(login, status, erro=""):
    """Salva o status do envio em um arquivo CSV."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp};{login};{status};{erro}\n"
    with open("log_envios.csv", "a", encoding="utf-8") as f:
        f.write(log_line)


def gerar_relatorio_falhas(falhas):
    """
    Gera relatorio_falhas.txt com os alunos que nao receberam o e-mail,
    incluindo o caminho da rubrica para reenvio manual.
    """
    if not falhas:
        print("\n[OK] Todos os e-mails foram enviados com sucesso!")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nome_arquivo = f"relatorio_falhas_{timestamp}.txt"

    linhas = [
        "=" * 60,
        "RELATORIO DE FALHAS NO ENVIO DE E-MAIL",
        f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}",
        f"Total de falhas: {len(falhas)}",
        "=" * 60,
        "",
        "Os seguintes alunos NAO receberam o e-mail automatico.",
        "Acoes sugeridas:",
        "  1. Verificar se o endereco existe no sistema da UFABC",
        "  2. Enviar manualmente pelo webmail (fzampirolli@ufabc.edu.br)",
        "  3. Contatar o STI para liberar relay SMTP -> Exchange aluno",
        "",
        "-" * 60,
    ]

    for i, f in enumerate(falhas, 1):
        linhas += [
            f"[{i}] Login:   {f['login']}",
            f"     E-mail:  {f['email']}",
            f"     Pasta:   {f['nome_pasta']}",
            f"     Rubrica: {f['arquivo_rubrica']}",
            f"     Erro:    {f['erro']}",
            "",
        ]

    linhas += [
        "-" * 60,
        "Dica: para reenvio manual, abra o webmail, anexe o arquivo",
        "      'rubrica.txt' indicado acima e encaminhe ao aluno.",
        "=" * 60,
    ]

    with open(nome_arquivo, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))

    print(f"\n{'=' * 60}")
    print(f"  {len(falhas)} aluno(s) nao receberam o e-mail.")
    print(f"  Relatorio salvo em: {nome_arquivo}")
    print(f"{'=' * 60}")
    for fa in falhas:
        print(f"  - {fa['login']} ({fa['email']})")
    print(f"{'=' * 60}\n")

    return nome_arquivo


def envia_email(servidor, porta, FROM, PASS, TO, subject, texto, anexo=[]):
    """Abre conexao SMTP individual por destinatario, com 2 tentativas."""
    msg = MIMEMultipart()
    msg['From'] = FROM
    msg['To'] = TO
    msg['Subject'] = subject
    msg.attach(MIMEText(texto, 'plain'))

    for f in anexo:
        if isinstance(f, list):
            f = f[0]
        try:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(open(f, 'rb').read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{os.path.basename(f)}"')
            msg.attach(part)
        except Exception as e:
            return False, f"Erro ao anexar arquivo: {e}"

    # TENTATIVA 1: Configuracao padrao segura
    try:
        gm = smtplib.SMTP(servidor, porta, timeout=30)
        gm.ehlo()
        context = ssl.create_default_context()
        context.set_ciphers('DEFAULT@SECLEVEL=1')
        gm.starttls(context=context)
        gm.ehlo()
        gm.login(FROM, PASS)
        gm.sendmail(FROM, TO, msg.as_string())
        gm.quit()
        print(f"[OK] E-mail enviado: {TO}")
        return True, ""
    except smtplib.SMTPRecipientsRefused as e:
        for recipient, (code, msg_err) in e.recipients.items():
            print(f"[REJEITADO] {code} para {recipient}: {msg_err}")
        return False, str(e)
    except Exception as e:
        print(f"[AVISO] Tentativa 1 falhou para {TO}: {e}")

    # TENTATIVA 2: Fallback sem verificacao de certificado
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with smtplib.SMTP(servidor, porta, timeout=30) as gm:
            gm.ehlo()
            gm.starttls(context=context)
            gm.ehlo()
            gm.login(FROM, PASS)
            gm.sendmail(FROM, TO, msg.as_string())
        print(f"[OK] E-mail enviado (tentativa 2): {TO}")
        return True, ""
    except Exception as e:
        print(f"[ERRO] Falha definitiva para {TO}: {e}")
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
                            'email': f"{login}@aluno.ufabc.edu.br"
                        })
    except Exception as e:
        print(f"Erro na busca: {e}")
    return rubricas_encontradas


def ler_nota_rubrica(arquivo_rubrica):
    try:
        with open(arquivo_rubrica, 'r', encoding='utf-8') as f:
            conteudo = f.read()
        nota_info = next(
            (l.strip() for l in conteudo.split('\n')
             if any(p in l.lower() for p in ['nota', 'total', 'pontos'])),
            "Info nao encontrada"
        )
        return conteudo, nota_info
    except:
        return "", "Erro na leitura"


def main():
    config = carregar_configuracao()
    if not config:
        return

    email_cfg = config.get('email', {})
    paths_cfg = config.get('paths', {})
    template_cfg = config.get('templates', {})

    servidor = email_cfg['smtp_server']
    porta = email_cfg.get('smtp_port', 587)
    FROM = email_cfg['from_address']
    PASS = email_cfg['password']

    pasta_base = paths_cfg.get('student_base_dir', 'Simulado0')
    rubricas = buscar_rubrica_txt(pasta_base)

    if not rubricas:
        print("Nenhuma rubrica encontrada.")
        return

    total = len(rubricas)
    enviados = 0
    falhas = []  # lista de dicts com dados dos alunos que falharam

    print(f"\nIniciando envio para {total} aluno(s)...\n")

    for dados in sorted(rubricas, key=lambda x: x['nome_pasta'].lower()):
        login = dados['login'].replace("_",".") # o Moodle baixa todos os emails com _ em vez de .
        nome_pasta = dados['nome_pasta']
        _, nota_info = ler_nota_rubrica(dados['arquivo_rubrica'])

        texto_email = template_cfg.get('corpo', "").format(
            login=login, nome_pasta=nome_pasta, nota_info=nota_info
        )
        assunto = template_cfg.get('assunto', "").format(login=login)

        # DESTINATARIO (ajuste aqui para producao ou teste)
        email_to = f"{login}@aluno.ufabc.edu.br"
        email_to = "fzampirolli@ufabc.edu.br"  # TESTE

        sucesso, erro = envia_email(
            servidor, porta, FROM, PASS,
            email_to, assunto, texto_email,
            [dados['arquivo_rubrica']]
        )

        if sucesso:
            enviados += 1
            registrar_log(login, "SUCESSO", "")
        else:
            registrar_log(login, "ERRO", erro)
            falhas.append({
                'login': login,
                'email': email_to,
                'nome_pasta': nome_pasta,
                'arquivo_rubrica': dados['arquivo_rubrica'],
                'erro': erro,
            })


    # Resumo final no terminal
    print(f"\nResultado: {enviados}/{total} enviados com sucesso.")

    # Gera relatorio de falhas (se houver)
    gerar_relatorio_falhas(falhas)


if __name__ == "__main__":
    if not os.path.exists("log_envios.csv"):
        with open("log_envios.csv", "w", encoding="utf-8") as f:
            f.write("Data;Login;Status;Detalhes\n")
    main()