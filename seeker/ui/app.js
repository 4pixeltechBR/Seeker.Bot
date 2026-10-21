const state = {
  chatId: null,
  live: false,
  mode: "chat",
  follow: true,
  phase: "pronto",
  approval: null,
  suggestion: null,
  bubble: null,
  recorder: null,
  chunks: [],
  stream: null,
  heard: false,
  watch: 0,
  spoken: new Set(),
  halt: false,
  radarConfirm: null,
  secret: null,
}

const $ = (id) => document.getElementById(id)

function setLive(on) {
  state.live = on
  document.getElementById("app").classList.toggle("is-live", on)
  $("send").textContent = on ? "Parar" : "Enviar"
  $("new-chat").disabled = on
}

function setMode(mode) {
  state.mode = mode
  const voice = mode === "voice"
  $("mode-chat").setAttribute("aria-pressed", String(!voice))
  $("mode-voice").setAttribute("aria-pressed", String(voice))
  $("voice").hidden = !voice
  document.querySelector(".stage").classList.toggle("voice-mode", voice)
  if (!voice) stopListen(false)
  if (voice) fetch("/api/voice/arm", { method: "POST" })
}

function setPhase(phase) {
  state.phase = phase
  const panel = $("orb")
  panel.className = "panel " + (phase === "pronto" ? "" : phase)
  const label = { pronto: "Pronto", ouvindo: "Ouvindo", pensando: "Pensando", falando: "Falando" }[phase]
  $("voice-state").textContent = label
  if (phase !== "ouvindo" && phase !== "falando") paintSilence()
}

async function load() {
  const health = await fetch("/api/health").then((res) => res.json())
  const list = $("providers")
  list.replaceChildren()
  let ready = false
  for (const provider of health.providers) {
    const item = document.createElement("li")
    item.textContent = provider.ready ? `${provider.name} pronto` : `${provider.name} sem chave`
    item.className = provider.ready ? "on" : ""
    list.append(item)
    ready = ready || provider.ready
  }
  for (const server of health.mcp || []) {
    const item = document.createElement("li")
    item.textContent = server.ok ? `${server.name}: ${server.tools} ferramentas` : `${server.name} sem ligação`
    item.className = server.ok ? "on" : ""
    list.append(item)
  }
  if (!ready) {
    $("empty").textContent = "Falta a chave de um modelo. Abra o arquivo .env nesta pasta."
  }
  const chats = await fetch("/api/chats").then((res) => res.json())
  renderChats(chats.chats)
  if (chats.chats.length) openChat(chats.chats[0].id)
  pulse()
  setInterval(pulse, 2000)
  bindSplitters()
}

function renderChats(chats) {
  const list = $("chats")
  list.replaceChildren()
  for (const chat of chats) {
    const item = document.createElement("li")
    const button = document.createElement("button")
    button.type = "button"
    button.textContent = chat.title
    button.dataset.id = chat.id
    if (chat.id === state.chatId) button.setAttribute("aria-current", "true")
    button.addEventListener("click", () => openChat(chat.id))
    item.append(button)
    list.append(item)
  }
}

async function openChat(id) {
  if (state.live) return
  state.chatId = id
  const data = await fetch("/api/chats/" + id).then((res) => res.json())
  const thread = $("thread")
  thread.replaceChildren()
  for (const message of data.messages) addBubble(message.role, message.content)
  const steps = $("steps")
  steps.replaceChildren()
  for (const event of data.events) upsertStep(event)
  $("steps-empty").hidden = steps.childElementCount > 0
  const buttons = document.querySelectorAll("#chats button")
  for (const button of buttons) {
    button.toggleAttribute("aria-current", button.dataset.id === id)
  }
  thread.scrollTop = thread.scrollHeight
}

function addBubble(role, text) {
  const turn = document.createElement("div")
  turn.className = "turn " + role
  const who = document.createElement("span")
  who.className = "who"
  who.textContent = role === "user" ? "Você" : "Seeker"
  const bubble = document.createElement("p")
  bubble.className = "bubble " + role
  bubble.textContent = text
  turn.append(who, bubble)
  $("thread").append(turn)
  return bubble
}

function upsertStep(event) {
  const steps = $("steps")
  let node = event.id ? steps.querySelector(`[data-id="${event.id}"]`) : null
  if (!node) {
    node = document.createElement("article")
    node.className = "step"
    if (event.id) node.dataset.id = event.id
    const lamp = document.createElement("i")
    const box = document.createElement("div")
    const label = document.createElement("p")
    const detail = document.createElement("pre")
    box.append(label, detail)
    node.append(lamp, box)
    steps.append(node)
  }
  node.dataset.status = event.status
  node.querySelector("p").textContent = event.label
  node.querySelector("pre").textContent = event.detail || ""
  $("steps-empty").hidden = true
  $("activity").scrollTop = $("activity").scrollHeight
}

const SECRET_KEYS = [
  ["GEMINI_API_KEY", "Gemini"],
  ["MARITACA_API_KEY", "Maritaca"],
  ["NVIDIA_API_KEY", "NVIDIA"],
  ["GROQ_API_KEY", "Groq"],
  ["MISTRAL_API_KEY", "Mistral"],
  ["OPENROUTER_API_KEY", "OpenRouter"],
  ["DEEPSEEK_API_KEY", "DeepSeek"],
  ["SILICONFLOW_API_KEY", "SiliconFlow"],
  ["HYPERBOLIC_API_KEY", "Hyperbolic"],
  ["FIREWORKS_API_KEY", "Fireworks"],
  ["SAMBANOVA_API_KEY", "SambaNova"],
  ["COHERE_API_KEY", "Cohere"],
  ["HUGGINGFACE_API_KEY", "Hugging Face"],
  ["INCEPTION_API_KEY", "Inception"],
  ["REKA_API_KEY", "Reka"],
  ["CLOUDFLARE_API_TOKEN", "Cloudflare"],
  ["ZHIPU_API_KEY", "Zhipu"],
  ["STEPFUN_API_KEY", "StepFun"],
  ["YI_API_KEY", "01.AI"],
  ["TAVILY_API_KEY", "Tavily"],
  ["EXA_API_KEY", "Exa"],
  ["JINA_API_KEY", "Jina"],
  ["DEEPGRAM_API_KEY", "Deepgram"],
  ["ASSEMBLYAI_API_KEY", "AssemblyAI"],
  ["ELEVENLABS_API_KEY", "ElevenLabs"],
  ["CARTESIA_API_KEY", "Cartesia"],
  ["IMAP_PASSWORD", "E-mail"],
  ["TELEGRAM_BOT_TOKEN", "Telegram"],
]
const SECRET_TOKEN = /(?<![A-Za-z0-9])(?:AIza[0-9A-Za-z\-_]{20,}|gsk_[A-Za-z0-9]{20,}|nvapi-[A-Za-z0-9\-_]{16,}|sk-(?:proj-)?[A-Za-z0-9]{20,}|xai-[A-Za-z0-9]{20,}|[0-9]{8,}:[A-Za-z0-9_\-]{30,})/
const SECRET_FILLER = new Set(["guarda", "guardar", "guarde", "salva", "salvar", "salve", "troca", "trocar", "troque", "chave", "chaves", "key", "api", "token", "senha", "segredo", "da", "do", "de", "a", "o", "as", "os", "um", "uma", "minha", "meu", "me", "aqui", "esta", "está", "essa", "esse", "isso", "cola", "cole", "colar", "por", "favor", "no", "na", "em", "cofre", "seguro", "nova", "novo", "ai", "gemini", "google", "groq", "nvidia", "nim", "maritaca", "sabia", "sabiá", "telegram", "email", "e-mail", "imap", "bot"])

function guessKey(text) {
  const raw = text || ""
  const folded = raw.toLowerCase()
  if (raw.includes("AIza")) return "GEMINI_API_KEY"
  if (raw.includes("gsk_")) return "GROQ_API_KEY"
  if (folded.includes("nvapi-")) return "NVIDIA_API_KEY"
  if (/[0-9]{8,}:[A-Za-z0-9_\-]{30,}/.test(raw)) return "TELEGRAM_BOT_TOKEN"
  if (folded.includes("gemini") || folded.includes("google ai")) return "GEMINI_API_KEY"
  if (folded.includes("groq")) return "GROQ_API_KEY"
  if (folded.includes("nvidia") || folded.includes("nim")) return "NVIDIA_API_KEY"
  if (folded.includes("maritaca") || folded.includes("sabia") || folded.includes("sabiá")) return "MARITACA_API_KEY"
  if (folded.includes("mistral")) return "MISTRAL_API_KEY"
  if (folded.includes("openrouter")) return "OPENROUTER_API_KEY"
  if (folded.includes("deepseek")) return "DEEPSEEK_API_KEY"
  if (folded.includes("siliconflow")) return "SILICONFLOW_API_KEY"
  if (folded.includes("hyperbolic")) return "HYPERBOLIC_API_KEY"
  if (folded.includes("fireworks")) return "FIREWORKS_API_KEY"
  if (folded.includes("sambanova")) return "SAMBANOVA_API_KEY"
  if (folded.includes("cohere")) return "COHERE_API_KEY"
  if (folded.includes("hugging")) return "HUGGINGFACE_API_KEY"
  if (folded.includes("inception") || folded.includes("mercury")) return "INCEPTION_API_KEY"
  if (folded.includes("reka")) return "REKA_API_KEY"
  if (folded.includes("cloudflare")) return "CLOUDFLARE_API_TOKEN"
  if (folded.includes("zhipu") || folded.includes("glm")) return "ZHIPU_API_KEY"
  if (folded.includes("stepfun")) return "STEPFUN_API_KEY"
  if (folded.includes("01.ai") || folded.includes("lingyi")) return "YI_API_KEY"
  if (folded.includes("tavily")) return "TAVILY_API_KEY"
  if (folded.includes("exa")) return "EXA_API_KEY"
  if (folded.includes("jina")) return "JINA_API_KEY"
  if (folded.includes("deepgram")) return "DEEPGRAM_API_KEY"
  if (folded.includes("assembly")) return "ASSEMBLYAI_API_KEY"
  if (folded.includes("eleven")) return "ELEVENLABS_API_KEY"
  if (folded.includes("cartesia")) return "CARTESIA_API_KEY"
  if (folded.includes("telegram")) return "TELEGRAM_BOT_TOKEN"
  if (folded.includes("imap") || folded.includes("senha do e-mail") || folded.includes("senha do email")) return "IMAP_PASSWORD"
  return ""
}

function labelFor(name) {
  const found = SECRET_KEYS.find((item) => item[0] === name)
  return found ? found[1] : ""
}

function keptWords(text) {
  return text.split(/\s+/).map((word) => word.replace(/^[^0-9A-Za-zÀ-ÿ]+|[^0-9A-Za-zÀ-ÿ]+$/g, "").toLowerCase()).filter((word) => word && !SECRET_FILLER.has(word))
}

function openSecret(card) {
  const name = card.name || ""
  state.secret = { id: card.id || "", name }
  $("secret-title").textContent = card.label ? "Cofre seguro — " + card.label : "Cofre seguro"
  const known = SECRET_KEYS.some((item) => item[0] === name)
  $("secret-pick").hidden = Boolean(card.id && known)
  const select = $("secret-name")
  select.replaceChildren()
  for (const [id, label] of SECRET_KEYS) {
    const option = document.createElement("option")
    option.value = id
    option.textContent = label
    if (id === name) option.selected = true
    select.append(option)
  }
  if (card.value && !$("secret-value").value) $("secret-value").value = card.value
  $("secret").hidden = false
  $("input").placeholder = "A chave fica no cartão ao lado."
  $("secret-value").focus()
}

function hideSecret() {
  state.secret = null
  $("secret-value").value = ""
  $("secret").hidden = true
  if (!state.approval) $("input").placeholder = "Diga o que você quer."
}

async function saveSecret() {
  const card = state.secret
  if (!card) return
  const name = $("secret-pick").hidden ? card.name : $("secret-name").value
  const input = $("secret-value")
  const value = input.value.trim()
  input.value = ""
  if (!name || !value) return
  const response = await fetch("/api/secrets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: card.id, name, value }),
  })
  if (!response.ok) {
    addBubble("assistant", "Não guardei. Cole a chave de novo no cartão.")
    return
  }
  hideSecret()
}

async function cancelSecret() {
  const card = state.secret
  hideSecret()
  if (!card) return
  await fetch("/api/secrets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: card.id, name: card.name, cancel: true }),
  })
}

async function sendText(text) {
  let clean = text.trim()
  if (!clean || state.live) return
  const found = clean.match(SECRET_TOKEN)
  if (found) {
    const name = guessKey(clean)
    openSecret({ id: state.secret ? state.secret.id : "", name, label: labelFor(name), value: found[0] })
    const rest = clean.replace(new RegExp(SECRET_TOKEN.source, "g"), " ").replace(/\s+/g, " ").trim()
    if (!keptWords(rest).length) {
      addBubble("assistant", "A chave ficou no cartão, fora do chat. Confirme no cofre.")
      return
    }
    clean = rest
  }
  if (!state.chatId) {
    const created = await fetch("/api/chats", { method: "POST", body: "{}" }).then((res) => res.json())
    state.chatId = created.id
    renderChats(await fetch("/api/chats").then((res) => res.json()).then((data) => data.chats))
  }
  addBubble("user", clean)
  state.bubble = addBubble("assistant", "")
  state.halt = false
  setLive(true)
  if (state.mode === "voice") setPhase("pensando")
  hideApproval()
  try {
    const response = await fetch("/api/chats/" + state.chatId + "/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: clean, voice: state.mode === "voice" }),
    })
    if (!response.ok) {
      const error = await response.json()
      state.bubble.classList.add("error")
      state.bubble.textContent = error.error || "Não consegui enviar."
      return
    }
    await readStream(response)
  } catch (error) {
    state.bubble.classList.add("error")
    state.bubble.textContent = "A ligação com o app caiu."
  } finally {
    setLive(false)
    const spoken = state.bubble ? state.bubble.textContent.trim() : ""
    const halted = state.halt
    state.bubble = null
    if (!halted && state.mode === "voice" && spoken) await speak(spoken)
    else if (state.mode === "voice") setPhase("pronto")
    if (!halted && state.mode === "voice" && $("follow").checked) startListen()
    refreshChats()
  }
}

async function readStream(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let split
    while ((split = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, split)
      buffer = buffer.slice(split + 2)
      const data = raw.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("")
      if (!data) continue
      handle(JSON.parse(data))
    }
  }
}

function handle(event) {
  if (event.type === "token" && state.bubble) {
    state.bubble.textContent += event.text
    const thread = $("thread")
    thread.scrollTop = thread.scrollHeight
  } else if (event.type === "activity") {
    upsertStep(event)
  } else if (event.type === "notice") {
    upsertStep({ id: "", label: event.text, status: "info", detail: "" })
  } else if (event.type === "error" && state.bubble && !state.bubble.textContent) {
    state.bubble.classList.add("error")
    state.bubble.textContent = event.text
  } else if (event.type === "secret") {
    if ($("secret").hidden || !$("secret-value").value) openSecret(event)
  } else if (event.type === "approval") {
    state.approval = event.id
    $("approval-command").textContent = event.command
    $("approval").hidden = false
    $("input").placeholder = "Responda sim para autorizar, ou não para recusar."
    $("input").focus()
  } else if (event.type === "title") {
    refreshChats()
  }
}

function hideApproval() {
  state.approval = null
  $("approval").hidden = true
  $("input").placeholder = "Diga o que você quer."
}

function chatDecision(text) {
  const cleaned = text.trim().toLowerCase().replace(/[!?.。,;:]+/g, "").replace(/\s+/g, " ")
  const yes = ["sim", "sim pode", "pode", "pode sim", "pode rodar", "roda", "rode", "autorizo", "autorizado", "manda", "confirma", "confirmo", "ok", "yes", "claro"]
  const no = ["nao", "não", "cancela", "recuso", "nao pode", "não pode", "no", "deixa", "para"]
  if (yes.includes(cleaned)) return true
  if (no.includes(cleaned)) return false
  return null
}

async function decide(allow) {
  if (!state.approval) return
  const id = state.approval
  hideApproval()
  await fetch("/api/approvals/" + id, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ allow }),
  })
}

async function pulse() {
  const data = await fetch("/api/pulse").then((res) => res.json())
  renderTasks([...(data.tasks || []), ...(data.routines || [])])
  renderRadar(data.radar || [])
  const pendingSecret = (data.secrets || [])[0]
  if (pendingSecret && $("secret").hidden) openSecret(pendingSecret)
  refreshTerm()
  const suggestion = data.suggestions[0]
  if (suggestion) {
    state.suggestion = suggestion
    $("suggest-text").textContent = suggestion.text
    $("suggest").hidden = false
  } else {
    state.suggestion = null
    $("suggest").hidden = true
  }
  const fresh = data.notices.filter((notice) => !state.spoken.has(notice.id))
  if (!fresh.length) return
  for (const notice of fresh) state.spoken.add(notice.id)
  await fetch("/api/notices/ack", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids: fresh.map((notice) => notice.id) }),
  })
  upsertStep({ id: "", label: fresh[fresh.length - 1].text, status: "info", detail: "" })
  if (state.mode === "voice" && !state.live) speak(fresh.map((notice) => notice.text).join(". "))
}

async function refreshTerm() {
  const data = await fetch("/api/terminal").then((res) => res.json())
  const log = $("term-log")
  if (!log) return
  log.textContent = data.text || "O terminal está pronto."
  $("term-cwd").textContent = data.cwd || ""
  log.scrollTop = log.scrollHeight
}

function renderRadar(cards) {
  const list = $("radar")
  if (!list) return
  list.replaceChildren()
  for (const card of cards) {
    const item = document.createElement("li")
    item.className = "radar-card"
    const line = document.createElement("p")
    const pending = state.radarConfirm && state.radarConfirm.id === card.id
    line.textContent = pending ? state.radarConfirm.text : card.line
    const actions = document.createElement("div")
    actions.className = "radar-actions"
    if (pending) {
      actions.append(radarButton("Sim", () => radarAct(card.id, "sim")), radarButton("Não", () => radarAct(card.id, "nao")))
    } else {
      for (const action of card.actions || []) actions.append(radarButton(actionLabel(action), () => radarAct(card.id, action)))
    }
    item.append(line, actions)
    list.append(item)
  }
}

function actionLabel(action) {
  return { concluir: "Concluir", arquivar: "Arquivar", rascunho: "Rascunho", remarcar: "Remarcar" }[action] || action
}

function radarButton(label, run) {
  const button = document.createElement("button")
  button.type = "button"
  button.textContent = label
  button.addEventListener("click", run)
  return button
}

async function radarAct(id, action) {
  const data = await fetch("/api/radar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, action }),
  }).then((res) => res.json())
  if (data.confirm) state.radarConfirm = { id, text: data.confirm }
  else {
    state.radarConfirm = null
    if (data.text) addBubble("assistant", data.text)
  }
  pulse()
}

function renderTasks(tasks) {
  const list = $("tasks")
  list.replaceChildren()
  if (!tasks.length) {
    const item = document.createElement("li")
    item.textContent = "Nada marcado."
    list.append(item)
    return
  }
  for (const task of tasks.slice(0, 6)) {
    const item = document.createElement("li")
    const title = document.createElement("strong")
    title.textContent = task.title
    item.append(title, document.createTextNode(task.when))
    if (task.overdue) item.className = "late"
    list.append(item)
  }
}

async function refreshChats() {
  const data = await fetch("/api/chats").then((res) => res.json())
  renderChats(data.chats)
}

const player = new Audio()

function speak(text) {
  return playSpeech("/api/voice/speak", { text }, text)
}

function playSpeech(url, body, fallbackText) {
  return new Promise((resolve) => {
    setPhase("falando")
    const finish = () => {
      setPhase("pronto")
      resolve()
    }
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(async (response) => {
        if (!response.ok || !response.headers.get("content-type")?.includes("audio")) {
          if (fallbackText) await windowsSpeak(fallbackText)
          else {
            const payload = await response.json().catch(() => ({}))
            addBubble("error", payload.error || "A voz não saiu.")
            finish()
          }
          if (fallbackText) finish()
          return
        }
        const blob = await response.blob()
        player.onended = () => {
          stopPlayMeter()
          finish()
        }
        armPlayer()
        player.src = URL.createObjectURL(blob)
        startPlayMeter()
        player.play().catch(async () => {
          if (fallbackText) await windowsSpeak(fallbackText)
          finish()
        })
      })
      .catch(async () => {
        if (fallbackText) await windowsSpeak(fallbackText)
        finish()
      })
  })
}

function windowsSpeak(text) {
  return new Promise((resolve) => {
    const synth = window.speechSynthesis
    if (!synth || !text) {
      setPhase("pronto")
      resolve()
      return
    }
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = "pt-BR"
    const voice = synth.getVoices().find((item) => item.lang.toLowerCase().startsWith("pt"))
    if (voice) utterance.voice = voice
    utterance.onend = () => {
      setPhase("pronto")
      resolve()
    }
    utterance.onerror = () => {
      setPhase("pronto")
      resolve()
    }
    synth.cancel()
    synth.speak(utterance)
  })
}

async function loadVoiceForm() {
  const profile = await fetch("/api/voice/profile").then((res) => res.json())
  $("voice-prompt").value = profile.prompt || ""
  $("voice-style").value = profile.style || ""
  $("voice-gender").value = profile.gender || "male"
}

async function startListen() {
  if (state.phase === "ouvindo" || state.live) return
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  } catch (error) {
    addBubble("error", "O microfone não abriu. No Windows, permita o microfone para este app.")
    return
  }
  state.chunks = []
  state.heard = false
  const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm"
  state.recorder = new MediaRecorder(state.stream, { mimeType: mime })
  state.recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size) state.chunks.push(event.data)
  })
  state.recorder.addEventListener("stop", uploadAudio)
  state.recorder.start()
  setPhase("ouvindo")
  watchSilence()
}

function watchSilence() {
  clearInterval(state.watch)
  const context = new AudioContext()
  const source = context.createMediaStreamSource(state.stream)
  const analyser = context.createAnalyser()
  analyser.fftSize = 1024
  source.connect(analyser)
  const data = new Uint8Array(analyser.fftSize)
  const freq = new Uint8Array(analyser.frequencyBinCount)
  let quiet = 0
  let elapsed = 0
  state.watch = setInterval(() => {
    if (state.phase !== "ouvindo") {
      clearInterval(state.watch)
      context.close()
      return
    }
    analyser.getByteTimeDomainData(data)
    analyser.getByteFrequencyData(freq)
    paintBins(freq)
    let sum = 0
    for (const value of data) {
      const sample = (value - 128) / 128
      sum += sample * sample
    }
    const level = Math.sqrt(sum / data.length)
    elapsed += 100
    if (level > 0.025) {
      state.heard = true
      quiet = 0
    } else if (state.heard) {
      quiet += 100
    }
    const follow = $("follow").checked
    if (elapsed > 30000 || (follow && state.heard && quiet > 1200) || (follow && !state.heard && elapsed > 6000)) {
      clearInterval(state.watch)
      context.close()
      stopListen(state.heard)
    }
  }, 100)
}

function stopListen(send = true) {
  clearInterval(state.watch)
  if (!send) state.chunks = []
  const recorder = state.recorder
  state.recorder = null
  if (recorder && recorder.state !== "inactive") recorder.stop()
  else if (state.stream) releaseMic()
  if (state.phase === "ouvindo") setPhase("pronto")
}

function releaseMic() {
  for (const track of state.stream?.getTracks() || []) track.stop()
  state.stream = null
}

async function uploadAudio() {
  releaseMic()
  const chunks = state.chunks
  state.chunks = []
  if (!chunks.length || !state.heard) {
    setPhase("pronto")
    return
  }
  setPhase("pensando")
  const blob = new Blob(chunks, { type: chunks[0].type || "audio/webm" })
  const audio = await blobToBase64(blob)
  const response = await fetch("/api/voice", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ audio_base64: audio, mime: blob.type || "audio/webm" }),
  })
  const payload = await response.json()
  if (!response.ok) {
    addBubble("error", payload.error || "Não transcrevi.")
    setPhase("pronto")
    return
  }
  await sendText(payload.text)
}

function blobToBase64(blob) {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "")
    reader.readAsDataURL(blob)
  })
}

$("composer").addEventListener("submit", (event) => {
  event.preventDefault()
  const pending = $("input").value
  const choice = state.approval ? chatDecision(pending) : null
  if (choice !== null) {
    $("input").value = ""
    decide(choice)
    return
  }
  if (!$("secret").hidden && pending.trim()) {
    const pasted = pending.match(SECRET_TOKEN)
    $("input").value = ""
    if (pasted) $("secret-value").value = pasted[0]
    $("secret-value").focus()
    return
  }
  if (state.live) {
    state.halt = true
    fetch("/api/stop", { method: "POST", body: "{}" })
    return
  }
  const text = $("input").value
  $("input").value = ""
  sendText(text)
})

$("input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault()
    $("composer").requestSubmit()
  }
})

$("new-chat").addEventListener("click", async () => {
  if (state.live) return
  const created = await fetch("/api/chats", { method: "POST", body: "{}" }).then((res) => res.json())
  await refreshChats()
  openChat(created.id)
  $("input").focus()
})

$("mode-chat").addEventListener("click", () => setMode("chat"))
$("mode-voice").addEventListener("click", () => {
  setMode("voice")
  loadVoiceForm()
})
$("term-form").addEventListener("submit", async (event) => {
  event.preventDefault()
  const command = $("term-input").value.trim()
  if (!command) return
  $("term-input").value = ""
  await fetch("/api/terminal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  })
  refreshTerm()
})
$("voice-form").addEventListener("submit", (event) => {
  event.preventDefault()
  if (state.live) return
  playSpeech("/api/voice/profile", {
    prompt: $("voice-prompt").value,
    style: $("voice-style").value,
    gender: $("voice-gender").value,
  }, "")
})
$("orb").addEventListener("click", () => {
  if (state.live) {
    state.halt = true
    fetch("/api/stop", { method: "POST", body: "{}" })
    player.pause()
    window.speechSynthesis?.cancel()
    return
  }
  if (state.phase === "ouvindo") stopListen(true)
  else if (state.phase === "falando") {
    window.speechSynthesis.cancel()
    setPhase("pronto")
  } else startListen()
})
$("deny").addEventListener("click", () => decide(false))

function bindSplitters() {
  const wide = window.matchMedia("(min-width: 981px)")
  const app = $("app")
  state.railW = Number(localStorage.getItem("seeker-rail")) || 248
  state.activityW = Number(localStorage.getItem("seeker-activity")) || 320

  function layout() {
    const railSplit = $("split-rail")
    const activitySplit = $("split-activity")
    if (!wide.matches) {
      app.style.gridTemplateColumns = ""
      railSplit.hidden = true
      activitySplit.hidden = true
      return
    }
    const width = app.clientWidth
    const rail = Math.min(Math.max(state.railW, 180), width - 520)
    const activity = Math.min(Math.max(state.activityW, 220), width - rail - 280)
    state.railW = rail
    state.activityW = activity
    app.style.gridTemplateColumns = rail + "px minmax(0, 1fr) " + activity + "px"
    railSplit.hidden = false
    activitySplit.hidden = false
    railSplit.style.left = rail + "px"
    activitySplit.style.left = (width - activity) + "px"
  }

  function drag(splitter, apply) {
    splitter.addEventListener("pointerdown", (event) => {
      if (!wide.matches) return
      event.preventDefault()
      splitter.setPointerCapture(event.pointerId)
      splitter.classList.add("is-on")
      const startX = event.clientX
      const startRail = state.railW
      const startActivity = state.activityW
      function move(ev) {
        apply(ev.clientX - startX, startRail, startActivity)
        layout()
      }
      function end() {
        splitter.classList.remove("is-on")
        splitter.removeEventListener("pointermove", move)
        splitter.removeEventListener("pointerup", end)
        localStorage.setItem("seeker-rail", String(state.railW))
        localStorage.setItem("seeker-activity", String(state.activityW))
      }
      splitter.addEventListener("pointermove", move)
      splitter.addEventListener("pointerup", end)
    })
  }

  drag($("split-rail"), (dx, startRail) => {
    state.railW = startRail + dx
  })
  drag($("split-activity"), (dx, _startRail, startActivity) => {
    state.activityW = startActivity - dx
  })
  wide.addEventListener("change", layout)
  window.addEventListener("resize", layout)
  layout()
}
function paintBins(bins) {
  let sum = 0
  for (const value of bins) sum += value
  const level = Math.min(1, sum / bins.length / 70)
  const levelText = level.toFixed(3)
  for (const avatar of document.querySelectorAll(".avatar")) avatar.style.setProperty("--voice", levelText)
}

function paintSilence() {
  for (const avatar of document.querySelectorAll(".avatar")) avatar.style.setProperty("--voice", "0")
}

function armPlayer() {
  if (state.playAnalyser) return
  const context = new AudioContext()
  const source = context.createMediaElementSource(player)
  const analyser = context.createAnalyser()
  analyser.fftSize = 256
  source.connect(analyser)
  analyser.connect(context.destination)
  state.playAnalyser = analyser
  state.playContext = context
}

function startPlayMeter() {
  stopPlayMeter()
  const bins = new Uint8Array(state.playAnalyser.frequencyBinCount)
  state.playContext.resume()
  state.playWatch = setInterval(() => {
    state.playAnalyser.getByteFrequencyData(bins)
    paintBins(bins)
  }, 80)
}

function stopPlayMeter() {
  clearInterval(state.playWatch)
  paintSilence()
}

function inkFor(color) {
  const hex = color.replace("#", "")
  const value = parseInt(hex, 16)
  const red = (value >> 16) & 255
  const green = (value >> 8) & 255
  const blue = value & 255
  return (red * 299 + green * 587 + blue * 114) / 1000 > 150 ? "#1c1915" : "#f3efe6"
}

function applyLook() {
  const theme = localStorage.getItem("seeker-theme") || "atual"
  document.documentElement.dataset.theme = theme === "atual" ? "" : theme
  const accent = localStorage.getItem("seeker-accent") || "#e0a23a"
  const balloon = localStorage.getItem("seeker-balloon") || "#e0a23a"
  document.documentElement.style.setProperty("--lamp", accent)
  document.documentElement.style.setProperty("--balloon", balloon)
  document.documentElement.style.setProperty("--balloon-ink", inkFor(balloon))
  document.documentElement.style.setProperty("--lamp-ink", inkFor(accent))
}

function bindSettings() {
  const dialog = $("settings")
  $("open-settings").addEventListener("click", async () => {
    const data = await fetch("/api/settings").then((res) => res.json())
    const keys = $("settings-keys")
    keys.replaceChildren()
    for (const item of data.keys) {
      const label = document.createElement("label")
      label.textContent = item.set ? item.label + " preenchida" : item.label + " vazia"
      const input = document.createElement("input")
      input.type = "password"
      input.autocomplete = "off"
      input.placeholder = "Nova chave"
      input.dataset.key = item.id
      label.append(input)
      keys.append(label)
    }
    const models = $("settings-models")
    models.replaceChildren()
    for (const item of data.models) {
      const label = document.createElement("label")
      label.textContent = item.name
      const input = document.createElement("input")
      input.type = "text"
      input.value = item.model
      input.dataset.model = item.name
      label.append(input)
      models.append(label)
    }
    $("accent").value = localStorage.getItem("seeker-accent") || "#e0a23a"
    $("balloon").value = localStorage.getItem("seeker-balloon") || "#e0a23a"
    dialog.showModal()
  })
  for (const button of document.querySelectorAll("[data-theme]")) {
    button.addEventListener("click", () => {
      localStorage.setItem("seeker-theme", button.dataset.theme)
      applyLook()
    })
  }
  $("accent").addEventListener("input", () => {
    localStorage.setItem("seeker-accent", $("accent").value)
    applyLook()
  })
  $("balloon").addEventListener("input", () => {
    localStorage.setItem("seeker-balloon", $("balloon").value)
    applyLook()
  })
  $("settings-close").addEventListener("click", () => dialog.close())
  $("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault()
    const keys = {}
    for (const input of $("settings-keys").querySelectorAll("input")) {
      if (input.value.trim()) keys[input.dataset.key] = input.value.trim()
    }
    const models = {}
    for (const input of $("settings-models").querySelectorAll("input")) {
      models[input.dataset.model] = input.value.trim()
    }
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keys, models }),
    })
    dialog.close()
    load()
  })
}

$("suggest-yes").addEventListener("click", async () => {
  const suggestion = state.suggestion
  if (!suggestion) return
  await fetch("/api/suggestions/" + suggestion.id + "/accept", { method: "POST", body: "{}" })
  $("suggest").hidden = true
  sendText("Sim. " + suggestion.text)
})
$("suggest-no").addEventListener("click", async () => {
  const suggestion = state.suggestion
  if (!suggestion) return
  await fetch("/api/suggestions/" + suggestion.id + "/dismiss", { method: "POST", body: "{}" })
  $("suggest").hidden = true
})

document.addEventListener("keydown", (event) => {
  if (state.mode !== "voice" || event.key !== " " || event.target === $("input")) return
  event.preventDefault()
  if (state.phase === "ouvindo") stopListen(true)
  else if (!state.live) startListen()
})

if (window.speechSynthesis) {
  window.speechSynthesis.getVoices()
  window.speechSynthesis.addEventListener("voiceschanged", () => window.speechSynthesis.getVoices())
}
function bindSecret() {
  $("secret-save").addEventListener("click", () => saveSecret())
  $("secret-cancel").addEventListener("click", () => cancelSecret())
  $("secret-value").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault()
      saveSecret()
    }
  })
}

applyLook()
bindSettings()
bindSecret()
load()
