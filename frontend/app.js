// ===========================================================================
// AccessiLearn frontend
// Two jobs: (1) a cursor/focus-guided voice narrator that speaks whatever
// UI element the mouse or keyboard focus lands on, and (2) calling the
// backend pipeline to turn source material into a narrated lesson.
// ===========================================================================

const API_BASE = "http://localhost:8000";

// ---------------------------------------------------------------------------
// 1. Cursor / focus guided voice narration
// ---------------------------------------------------------------------------
const VoiceGuide = (() => {
  let enabled = true;
  let lastSpoken = null;
  let hoverTimer = null;

  function speak(text) {
    if (!enabled || !text) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.rate = 1.05;
    utter.pitch = 1.0;
    window.speechSynthesis.speak(utter);
  }

  function announceElement(el) {
    if (!el) return;
    const text = el.getAttribute("data-speak") || el.getAttribute("aria-label") || el.innerText;
    if (!text || text === lastSpoken) return;
    lastSpoken = text.trim();
    speak(lastSpoken);
  }

  function handleHover(e) {
    const target = e.target.closest("[data-speak]");
    clearTimeout(hoverTimer);
    if (!target) return;
    // small debounce so fast mouse movement across many elements
    // doesn't fire a flood of overlapping speech
    hoverTimer = setTimeout(() => announceElement(target), 120);
  }

  function handleFocus(e) {
    const target = e.target.closest("[data-speak]");
    if (target) announceElement(target);
  }

  function init() {
    document.addEventListener("mousemove", handleHover);
    document.addEventListener("focusin", handleFocus);
  }

  function setEnabled(value) {
    enabled = value;
    if (!enabled) window.speechSynthesis.cancel();
  }

  function isEnabled() {
    return enabled;
  }

  return { init, setEnabled, isEnabled, speak };
})();

VoiceGuide.init();

const toggleBtn = document.getElementById("voiceGuideToggle");
const toggleState = document.getElementById("voiceGuideState");
toggleBtn.addEventListener("click", () => {
  const next = !VoiceGuide.isEnabled();
  VoiceGuide.setEnabled(next);
  toggleBtn.setAttribute("aria-pressed", String(next));
  toggleState.textContent = next ? "On" : "Off";
  announce(next ? "Cursor voice guide turned on" : "Cursor voice guide turned off");
  if (next) VoiceGuide.speak("Cursor voice guide turned on");
});

// Text size control
let fontScale = 1;
document.getElementById("textSizeToggle").addEventListener("click", () => {
  fontScale = fontScale >= 1.4 ? 1 : fontScale + 0.15;
  document.documentElement.style.setProperty("--font-scale", fontScale.toFixed(2));
  announce(`Text size set to ${Math.round(fontScale * 100)} percent`);
});

// Screen-reader live-region announcer (separate from the spoken cursor guide,
// for actual assistive tech users)
const announcer = document.getElementById("announcer");
function announce(msg) {
  announcer.textContent = "";
  requestAnimationFrame(() => (announcer.textContent = msg));
}

// ---------------------------------------------------------------------------
// 2. Tabs: choose source type
// ---------------------------------------------------------------------------
const tabs = document.querySelectorAll(".tab");
const panels = {
  textbook: document.getElementById("panel-textbook"),
  pdf: document.getElementById("panel-pdf"),
  image: document.getElementById("panel-image"),
};
let currentMode = "textbook";

tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    tabs.forEach((t) => t.setAttribute("aria-selected", "false"));
    tab.setAttribute("aria-selected", "true");
    Object.values(panels).forEach((p) => (p.hidden = true));
    currentMode = tab.dataset.mode;
    panels[currentMode].hidden = false;
    announce(`Switched to ${tab.textContent.trim()}`);
  });
});

// ---------------------------------------------------------------------------
// 3. Generate pipeline
// ---------------------------------------------------------------------------
const generateBtn = document.getElementById("generateBtn");
const statusMsg = document.getElementById("statusMsg");
const resultPanel = document.getElementById("resultPanel");
const audioPlayer = document.getElementById("audioPlayer");
const transcriptText = document.getElementById("transcriptText");
const downloadLink = document.getElementById("downloadLink");

function setStatus(msg) {
  statusMsg.textContent = msg;
  announce(msg);
}

async function extractPdfText(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/extract-pdf`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to read PDF");
  const data = await res.json();
  return data.text;
}

async function describeImage(file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/describe-image`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to describe image");
  const data = await res.json();
  return data.description;
}

async function generateScript(sourceText, title, mode) {
  const form = new FormData();
  form.append("source_text", sourceText);
  form.append("topic_title", title || "");
  form.append("mode", mode);
  const res = await fetch(`${API_BASE}/api/generate-script`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to generate script");
  const data = await res.json();
  return data.script;
}

async function generateAudio(script) {
  const form = new FormData();
  form.append("script", script);
  const res = await fetch(`${API_BASE}/api/generate-audio`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.json()).detail || "Failed to generate audio");
  const data = await res.json();
  return data.audio_url;
}

generateBtn.addEventListener("click", async () => {
  generateBtn.disabled = true;
  resultPanel.hidden = true;

  try {
    let sourceText = "";
    let mode = "textbook";
    const title = document.getElementById("titleInput").value;

    if (currentMode === "textbook") {
      sourceText = document.getElementById("textInput").value.trim();
      if (!sourceText) throw new Error("Please paste some chapter text first.");
      mode = "textbook";
    } else if (currentMode === "pdf") {
      const file = document.getElementById("pdfInput").files[0];
      if (!file) throw new Error("Please choose a PDF file first.");
      setStatus("Reading text out of your PDF...");
      sourceText = await extractPdfText(file);
      mode = "textbook";
    } else if (currentMode === "image") {
      const file = document.getElementById("imageInput").files[0];
      if (!file) throw new Error("Please choose an image file first.");
      setStatus("Looking closely at your diagram or photo...");
      sourceText = await describeImage(file);
      mode = "diagram";
    }

    setStatus("Rewriting this into a spoken, podcast-style lesson...");
    const script = await generateScript(sourceText, title, mode);

    setStatus("Recording the narration...");
    const audioUrl = await generateAudio(script);

    setStatus("Your lesson is ready.");
    audioPlayer.src = `${API_BASE}${audioUrl}`;
    downloadLink.href = `${API_BASE}${audioUrl}`;
    transcriptText.textContent = script;
    resultPanel.hidden = false;
    resultPanel.scrollIntoView({ behavior: "smooth" });
    VoiceGuide.speak("Your audio lesson is ready. Press play to listen.");
  } catch (err) {
    setStatus(`Something went wrong: ${err.message}`);
  } finally {
    generateBtn.disabled = false;
  }
});
