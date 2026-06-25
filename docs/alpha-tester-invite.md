# Trevvos Forge Closed Alpha Invite

---

## English

Hi! You are invited to test **Trevvos Forge v0.1.0-alpha.1** â€” a local-first AI engineering CLI.

**What is Trevvos Forge?**

A command-line tool that helps developers understand, analyze, review, and test code using local or API-hosted LLMs (Ollama, LM Studio, OpenAI API). It runs entirely on your machine â€” no cloud, no uploads, no account required.

**Key workflows:**
- Analyze and explain code
- Generate technical proposals and implementation specs
- Review diffs before commit
- Generate unit test patches in a sandboxed flow
- Local dashboard for session browsing

**Installation (no Python or Git required):**

Download the standalone binary for your OS from the GitHub Release:

Windows x64:
```powershell
# Download trevvos-forge-v0.1.0-alpha.1-windows-x64.zip
Expand-Archive -Path trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos-forge
cd trevvos-forge
.\trevvos.exe --version
```

Linux x64:
```bash
# Download trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
tar -xzf trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos
./trevvos --version
```

Full install guide: see `docs/alpha-download-install.md` included in the archive.

**What to test first:**

```bash
# 1. Set up with your LLM provider
trevvos setup

# 2. Verify provider connectivity
trevvos doctor

# 3. Inspect a project
trevvos inspect

# 4. Analyze a file
trevvos analyze <file>

# 5. Open the dashboard
trevvos api start --open

# 6. Export a session for your report
trevvos sessions export latest
```

**Please test with a non-sensitive project** for this Alpha. The tool reads source files to build context for the LLM. Session exports may contain source code and LLM prompts.

**Please avoid:**
- Using Execution Mode commands (`plan`, `diff`, `apply`, `repair`, `work`) unless specifically guided â€” they are experimental.
- Assuming generated output is correct â€” advisory mode produces suggestions, not verified facts.

**Report feedback:**

Open a GitHub issue using the Alpha Feedback template, or send directly to the maintainer.

When something fails, please export the session and attach it:

```bash
trevvos sessions export latest
```

Review the export before sharing â€” it contains source code. Secrets in JSON artifacts are masked automatically.

**Expected test time:** 1â€“3 hours over the test window.

**Test window:** [fill in dates]

Thank you!

---

## PortuguÃªs

OlÃ¡! VocÃª estÃ¡ convidado(a) para testar o **Trevvos Forge v0.1.0-alpha.1** â€” um CLI de engenharia de software com IA local.

**O que Ã© o Trevvos Forge?**

Uma ferramenta de linha de comando que ajuda desenvolvedores a entender, analisar, revisar e testar cÃ³digo usando LLMs locais ou via API (Ollama, LM Studio, OpenAI API). Roda inteiramente na sua mÃ¡quina â€” sem cloud, sem uploads, sem conta necessÃ¡ria.

**Principais fluxos:**
- Analisar e explicar cÃ³digo
- Gerar propostas tÃ©cnicas e specs de implementaÃ§Ã£o
- Revisar diffs antes de commitar
- Gerar patches de testes unitÃ¡rios em fluxo sandboxed
- Dashboard local para navegar sessÃµes

**InstalaÃ§Ã£o (sem Python ou Git necessÃ¡rio):**

Baixe o binÃ¡rio standalone para o seu OS na GitHub Release:

Windows x64:
```powershell
# Baixar trevvos-forge-v0.1.0-alpha.1-windows-x64.zip
Expand-Archive -Path trevvos-forge-v0.1.0-alpha.1-windows-x64.zip -DestinationPath trevvos-forge
cd trevvos-forge
.\trevvos.exe --version
```

Linux x64:
```bash
# Baixar trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
tar -xzf trevvos-forge-v0.1.0-alpha.1-linux-x64.tar.gz
cd trevvos
./trevvos --version
```

Guia completo de instalaÃ§Ã£o: veja `docs/alpha-download-install.md` incluso no arquivo.

**O que testar primeiro:**

```bash
# 1. Configurar com seu provider de LLM
trevvos setup

# 2. Verificar conectividade com o provider
trevvos doctor

# 3. Inspecionar um projeto
trevvos inspect

# 4. Analisar um arquivo
trevvos analyze <arquivo>

# 5. Abrir o dashboard
trevvos api start --open

# 6. Exportar sessÃ£o para o relatÃ³rio
trevvos sessions export latest
```

**Por favor, teste com um projeto nÃ£o sensÃ­vel** neste Alpha. A ferramenta lÃª arquivos fonte para construir contexto para o LLM. Exports de sessÃ£o podem conter cÃ³digo fonte e prompts do LLM.

**Por favor, evite:**
- Usar comandos do Execution Mode (`plan`, `diff`, `apply`, `repair`, `work`) sem orientaÃ§Ã£o â€” sÃ£o experimentais.
- Assumir que o output gerado Ã© sempre correto â€” o modo advisory produz sugestÃµes, nÃ£o fatos verificados.

**Como reportar:**

Abra uma issue no GitHub usando o template Alpha Feedback, ou envie diretamente para o mantenedor.

Quando algo falhar, exporte a sessÃ£o e anexe ao relatÃ³rio:

```bash
trevvos sessions export latest
```

Revise o export antes de compartilhar â€” contÃ©m cÃ³digo fonte. Segredos em artefatos JSON sÃ£o mascarados automaticamente.

**Tempo estimado:** 1â€“3 horas no perÃ­odo de teste.

**Janela de teste:** [preencher datas]

Obrigado(a)!


