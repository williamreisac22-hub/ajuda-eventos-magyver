# Ajuda Eventos Magyver — versão definitiva

Pacote completo de uma aplicação web local com backend Python + SQLite.

## Recursos
- Login e cadastro com senha armazenada por hash PBKDF2.
- Eventos: criação, edição, exclusão, cliente, data, horário, endereço, pessoas, confirmação e serviço interno/externo.
- Clientes e ficha do cliente.
- Calendário.
- Financeiro e pagamentos: adiantado, durante e após.
- PIX: chave do empresário, geração do payload PIX e QR Code.
- Equipamentos/Checklist.
- Gastronomia.
- Orçamentos.
- Contratos.
- Configurações e perfil.
- Lembretes por e-mail 1 dia antes, via SMTP configurado pelo usuário.
- Emblema Magyver incluído e usado no login, cabeçalho e identificação fixa.

## Inicialização
Windows: execute `start_windows.bat`.
Linux/macOS: execute `./start_linux_mac.sh`.
Depois abra `http://127.0.0.1:8080`.

A primeira execução instala a única dependência Python (`qrcode`) e cria `data/magyver.db`.

## PIX
O QR Code é gerado localmente a partir da chave cadastrada e do valor informado, usando o padrão EMV/BR Code do Pix. Para receber pagamentos reais, a chave precisa ser uma chave Pix válida da empresa.

## E-mail
Para envio real, preencha o SMTP nas Configurações e use o botão Testar e-mail. O lembrete automático verifica eventos do dia seguinte a cada 5 minutos enquanto o servidor estiver ligado.

## Produção
Para colocar na internet, use HTTPS, um domínio, serviço de hospedagem e gestão de segredos/SMTP apropriada. Não coloque senhas SMTP em repositório público.
