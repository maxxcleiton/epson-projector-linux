# Epson Projeção Linux

🌐 **Language / Idioma:** [English](README.md) | **Português (Brasil)**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![GTK 3](https://img.shields.io/badge/GUI-GTK%203-green.svg)](https://www.gtk.org/)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey.svg)]()
[![Release](https://img.shields.io/github/v/release/maxxcleiton/epson-projector-linux)](https://github.com/maxxcleiton/epson-projector-linux/releases)

Aplicativo nativo para Linux (Ubuntu, Debian, Pop!_OS, Linux Mint, Fedora) para controle, gerenciamento e espelhamento de tela sem fio/rede para projetores Epson, **sem necessidade de Wine, Java ou emuladores**.

---

## 🎯 Motivação

O software oficial da Epson (*EasyMP Network Projection* / *iProjection*) não possui suporte nativo moderno e estável para distribuições Linux contemporâneas. Tentativas de executá-lo via Wine frequentemente falham devido a dependências de drivers de vídeo virtuais do Windows e chamadas de rede proprietárias.

Este projeto reimplementa de forma nativa e enxuta os protocolos de comunicação da Epson (**ESC/VP.net** e **EasyMP Network Projection**), permitindo que qualquer usuário Linux controle e espelhe sua tela no projetor através da rede local (Wi-Fi ou Ethernet) com alto desempenho, baixa latência e consumo mínimo de CPU.

### 🔬 Engenharia Reversa (REA)

Como a Epson não disponibiliza documentação pública ou especificações abertas sobre o protocolo de transporte de vídeo EasyMP e seus cabeçalhos binários, esta solução foi concebida por meio de **Engenharia Reversa (Reverse Engineering / REA)**. Através da análise e dissecação do tráfego de pacotes de rede TCP/IP e inspeção das rotinas de comunicação cliente-projetor, foi possível decodificar os frames de controle `EEMP0100` (porta 3620) e o fluxo segmentado de quadros JPEG (porta 3621), resultando em uma implementação 100% livre de bibliotecas proprietárias.

---

## ✨ Funcionalidades

- **Espelhamento de Tela em Tempo Real**: Captura e transmissão via TCP (portas 3620/3621) com redimensionamento bicubic letterbox e compressão JPEG otimizada.
- **Renderização do Cursor do Mouse**: Captura em tempo real do cursor do mouse via X11 (`libXfixes`), com mesclagem alfa de alta fidelidade para que o apresentador e a plateia vejam o ponteiro com nitidez.
- **Controle de Energia (Power ON / Standby)**: Ligue e desligue projetores diretamente pela interface com um clique via protocolo ESC/VP.net (porta 3629).
- **Detecção Inteligente de Projetor em Uso**:
  - Exibe se o projetor está **Livre**, **Em Uso (Ocupado)**, **Ligando (Aquecendo)** ou **Desligado**.
  - Alerta antes de conectar se outro computador já estiver projetando e permite assumir a sessão (*takeover*).
  - Notifica claramente o apresentador anterior caso sua projeção tenha sido assumida por outro colega ou se o projetor foi desligado.
- **Barra de Controle Flutuante (Presenter Toolbar)**: Janela discreta que fica sempre no topo durante a apresentação com botão de pausa e encerramento rápido da transmissão.
- **Sem Interferência de Áudio**: Negociação limpa do canal de stream que evita ruídos ou sequestro indesejado de dispositivos de áudio ALSA/PulseAudio.
- **Descoberta Automática na Rede**: Varredura inteligente de sub-rede para encontrar projetores Epson ativos e cadastro manual de IPs com persistência em JSON (`~/.config/epson-projector/projectors.json`).

---

## ⚠️ Compatibilidade e Modelos Testados

> [!NOTE]
> **Aviso sobre modelos e validação:**
> Este software foi concebido, desenvolvido e testado com o projetor Epson corporativo 3LCD (padrão XGA 1024x768 com módulo de rede sem fio EasyMP / ESC/VP.net) disponível em nosso ambiente.
> 
> Até o momento, **ele não foi testado em outros modelos ou séries da Epson** (como modelos WXGA 1280x800, Full HD 1080p ou projetores laser/home cinema).
> 
> Como a Epson padroniza os protocolos **EasyMP** (portas 3620/3621) e **ESC/VP.net** (porta 3629) na maioria de seus projetores de rede, a expectativa é que funcione na maioria dos modelos compatíveis. Se você testar em um modelo diferente, **seu feedback é muito bem-vindo**! Sinta-se à vontade para abrir uma *Issue* relatando seu modelo e resultados.

---

## 🏗️ Arquitetura dos Protocolos

O aplicativo comunica-se diretamente com o firmware do projetor através de três canais TCP:

```
+--------------------------------------------------------------------+
|                       Computador Linux                             |
|                                                                    |
|  [ Interface GTK 3 ] <---> [ Captura de Tela + Mouse (XFixes) ]    |
+-----------+----------------------+--------------------+------------+
            |                      |                    |
   TCP 3629 |             TCP 3620 |           TCP 3621 |
(ESC/VP.net)|         (EasyMP Ctrl)|     (EasyMP Stream)|
            v                      v                    v
+--------------------------------------------------------------------+
|                        Projetor Epson                              |
|                                                                    |
|  - Liga/Desliga           - Handshake          - Decodificador     |
|  - Leitura de Status      - Resolução            JPEG Hardware     |
|  - Horas de Lâmpada       - Takeover           - Buffer de Frame   |
+--------------------------------------------------------------------+
```

1. **TCP 3629 (ESC/VP.net)**: Protocolo de texto/controle para ligar (`PWR ON`), desligar (`PWR OFF`), consultar estado de energia (`PWR?`) e obter número de série e informações do equipamento.
2. **TCP 3620 (EasyMP Control)**: Negociação de sessão, resolução geométrica da tela e controle de takeover.
3. **TCP 3621 (EasyMP Video Stream)**: Transmissão segmentada de quadros JPEG em alta taxa de atualização.

---

## 📡 Dica Importante sobre Wi-Fi (Canais 1 a 11 vs 12 e 13)

Muitos projetores Epson utilizam módulos de rede sem fio USB (como os dongles *ELPAP07* ou *ELPAP10*) com firmware definido para o domínio regulatório **US1 (Estados Unidos)**.

- **O Problema**: No Brasil e na Europa, redes 2.4 GHz podem utilizar os canais **1 até 13**. Roteadores configurados com canal automático frequentemente escolhem os canais **12 ou 13**. Dispositivos com placa US1 **não enxergam** esses canais e o projetor ficará inacessível na rede sem fio.
- **A Solução**: No seu Roteador ou Ponto de Acesso (Access Point), fixe o canal da rede 2.4 GHz em um canal entre **1 e 11** (recomenda-se **1, 6 ou 11** para evitar sobreposição).

---

## 🚀 Instalação e Uso

### Opção 1: Baixar o Pacote `.deb` Pré-compilado (Mais Fácil)

Baixe a versão mais recente diretamente na [página de Releases](https://github.com/maxxcleiton/epson-projector-linux/releases) e instale:

```bash
sudo dpkg -i epson-projector-linux_*_all.deb
sudo apt-get install -f
```

### Opção 2: Compilar e Gerar o Pacote `.deb` Você Mesmo

O repositório inclui o script `build_deb.sh` para compilar o pacote localmente:

```bash
# 1. Clone o repositório
git clone https://github.com/maxxcleiton/epson-projector-linux.git
cd epson-projector-linux

# 2. Torne o script executável e gere o pacote
chmod +x build_deb.sh
./build_deb.sh

# 3. Instale o pacote gerado no sistema
sudo dpkg -i epson-projector-linux_*_all.deb
sudo apt-get install -f
```

#### 📦 O que o processo de empacotamento faz?
- Monta a estrutura padrão FHS em `build_pkg/`:
  - `/usr/share/epson-projector/src/`: Módulos Python.
  - `/usr/share/epson-projector/assets/`: Ícones e recursos visuais.
  - `/usr/bin/epson-projector`: Executável no PATH.
  - `/usr/share/applications/epson-projector.desktop`: Atalho do menu.
  - `/usr/share/icons/hicolor/64x64/apps/`: Ícone do sistema.
- Executa o script de pós-instalação (`postinst`) que distribui o atalho automaticamente na **Área de Trabalho** de todos os usuários cadastrados.

### Opção 3: Executar Diretamente do Código-Fonte (Sem Instalação)

```bash
# 1. Instale as dependências do sistema
sudo apt update
sudo apt install -y python3 python3-gi gir1.2-gtk-3.0 gir1.2-gdkpixbuf-2.0 python3-pil libx11-6 libxfixes3

# 2. Verifique a sintaxe (opcional)
python3 -m py_compile src/*.py

# 3. Execute diretamente
chmod +x run.sh
./run.sh
```

---

## ⚙️ Configuração dos Projetores

As configurações ficam salvas em `~/.config/epson-projector/projectors.json`.
Você pode adicionar projetores tanto pela interface gráfica (clicando no botão `+ Adicionar`) quanto editando o arquivo JSON manualmente:

```json
{
  "projectors": [
    {
      "id": "proj-01",
      "name": "Sala de Reunião Principal",
      "ip": "192.168.1.100",
      "mac": "",
      "port_escvp": 3629,
      "port_easymp": 3620,
      "port_stream": 3621
    }
  ],
  "fps": 20,
  "quality": 90
}
```

---

## 📜 Histórico de Versões (Changelog)

### **v1.3.6**
- **Status Transitório "Iniciando... (Aguarde)"**: Ao ligar o projetor pelo aplicativo, a interface exibe imediatamente o status "Iniciando..." com indicador azul vibrante. Isso evita que o reinício temporário da placa de rede interna do projetor durante a ignição da lâmpada mostre falsamente "Desconectado" antes do aquecimento.
- **Edição e Remoção de Projetores**: Adicionado botão de edição (e atalho por duplo-clique na lista) para alterar o nome e IP dos projetores cadastrados diretamente pela interface gráfica, além de botão para exclusão de projetores obsoletos.

### **v1.3.5**
- **Correção Crítica no Cursor do Mouse (64-bit LP64)**: Corrigido o bug de alinhamento de memória na extração de pixels da `libXfixes`. Em arquiteturas x86_64, os pixels do cursor utilizam `unsigned long` (8 bytes), enquanto os dados de cor ocupam 4 bytes. O ajuste de stride eliminou o padrão serrilhado/pente, gerando uma seta perfeitamente lisa e nítida.

### **v1.3.4**
- **Suporte a Cursor do Mouse na Projeção**: Integração nativa com `libXfixes` e `libX11` via `ctypes` para capturar a posição e formato do cursor do mouse do sistema operacional e mesclá-lo sobre a imagem capturada em tempo real.

### **v1.3.3**
- **Melhorias Visuais e Contraste na Interface**: Ajuste na paleta de cores para evitar confusão entre o estado "Em uso" e o item selecionado na lista (realce em tons neutros/cinza grafite).

### **v1.3.2**
- **Eliminação de Tremulação (Flicker) no Reload**: Otimização do loop de atualização periódica da interface GTK. A lista de projetores agora atualiza os rótulos e estados das linhas existentes sem reconstruir o widget, mantendo a seleção estável sem piscar.

### **v1.3.1**
- **Discriminação de Desconexão**: Diferenciação clara entre desconexão por encerramento/desligamento do projetor e desconexão decorrente de *takeover* por outro usuário na rede local.

### **v1.3.0**
- **Detecção de Ocupação e Gestão de Conflito (Takeover)**:
  - Verificação de ocupação via porta EasyMP antes de iniciar a sessão.
  - Exibição do status "Em uso" na lista principal.
  - Janela de confirmação para assumir o projetor quando ocupado.
  - Tratamento da perda de sessão quando outro computador assume a projeção.

### **v1.2.5**
- **Ajuste de Áudio e Varredura de Rede**: Configuração de canal nulo de áudio para evitar interferências sonoras e implementação de varredura assíncrona de sub-rede.

### **v1.2.0**
- **Barra Flutuante de Apresentação**: Implementação de janela flutuante Always-on-Top com controles rápidos de pausa e desconexão durante o espelhamento de tela.

### **v1.1.0**
- **Interface Gráfica Nativa GTK 3**: Criação do painel visual com lista de projetores cadastrados, status de lâmpada e botões de Ligar/Desligar via ESC/VP.net.

### **v1.0.0**
- **Lançamento Inicial**: Implementação base dos protocolos ESC/VP.net (TCP 3629) e streaming EasyMP (TCP 3620/3621) em Python puro.

---

## 🤝 Contribuições

Contribuições são muito bem-vindas! Sinta-se à vontade para abrir uma *Issue* para relatar bugs ou sugerir melhorias, ou enviar um *Pull Request*.

## 📄 Licença

Este projeto está licenciado sob a licença **MIT** - veja o arquivo [LICENSE](LICENSE) para mais detalhes.
