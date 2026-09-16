/* 美音音频播放器：任一时刻只播放一段；切换或离开页面即停止。 */
(() => {
  "use strict";
  const status = document.querySelector("#audio-status");
  const rate = document.querySelector("#audio-rate");
  const stop = document.querySelector("#audio-stop");
  if (!status || !rate || !stop) return;
  let player = null;
  let activeButton = null;
  let generation = 0;

  function message(text, error = false) {
    status.textContent = text;
    status.classList.toggle("error", error);
  }
  function finish() {
    if (activeButton) {
      activeButton.classList.remove("playing");
      activeButton.removeAttribute("aria-pressed");
    }
    activeButton = null;
  }
  function cancel() {
    generation++;
    if(window.speechSynthesis)window.speechSynthesis.cancel();
    if (player) {
      player.pause();
      player.removeAttribute("src");
      player.load();
      player = null;
    }
    finish();
  }
  function currentRate() {
    const value = Number(rate.value);
    return Number.isFinite(value) && value >= 0.5 && value <= 2 ? value : 1;
  }
  try {
    const saved = localStorage.getItem("vocabulary-us-rate");
    if (Array.from(rate.options).some(option => option.value === saved)) rate.value = saved;
  } catch (_) { /* 本地文件可能禁用存储，仍可正常朗读。 */ }
  rate.addEventListener("change", () => {
    if (player) player.playbackRate = currentRate();
    try { localStorage.setItem("vocabulary-us-rate", rate.value); } catch (_) {}
  });
  stop.addEventListener("click", () => { cancel(); message("已停止"); });
  // 捕获阶段拦截，避免点例句播放按钮时同时展开或关闭详情。
  document.addEventListener("click", event => {
    const button = event.target.closest && event.target.closest("button[data-audio],button[data-speech-text]");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    cancel();
    const token = generation;
    activeButton = button;
    button.classList.add("playing");
    button.setAttribute("aria-pressed", "true");
    if(button.dataset.speechText){
      const synth=window.speechSynthesis;
      const speak=()=>{
        if(token!==generation)return;
        const voice=synth?.getVoices().find(v=>v.localService&&/^en[-_]US$/i.test(v.lang));
        if(!voice){cancel();message('当前浏览器没有可用的本地美音语音。请在系统中安装英语（美国）语音后重试；原有离线音频仍可播放。',true);return;}
        const utterance=new SpeechSynthesisUtterance(button.dataset.speechText.replace(/__\d+__/g,' blank '));
        utterance.voice=voice;utterance.lang='en-US';utterance.rate=currentRate();
        utterance.onstart=()=>{if(token===generation)message('正在朗读'+button.dataset.label+' · 本地美音');};
        utterance.onend=()=>{if(token===generation){finish();message('朗读结束');}};
        utterance.onerror=()=>{if(token===generation){cancel();message('本地美音朗读失败，请检查系统语音设置。',true);}};
        synth.speak(utterance);
      };
      if(synth&&!synth.getVoices().length){message('正在加载本地语音…');let done=false;const ready=()=>{if(done)return;done=true;synth.removeEventListener('voiceschanged',ready);speak();};synth.addEventListener('voiceschanged',ready);setTimeout(ready,1500);}else speak();
      return;
    }
    player = new Audio(button.dataset.audio);
    player.playbackRate = currentRate();
    player.preservesPitch = true;
    const current = player;
    message("正在加载美音" + button.dataset.label + "…");
    const fail = () => {
      if (token !== generation) return;
      cancel();
      message("音频未能播放。请确认项目内 output/audio 文件夹完整；新增词条后运行 python main.py --audio。", true);
    };
    current.addEventListener("playing", () => {
      if (token === generation) message("正在朗读" + button.dataset.label + " · 美音");
    });
    current.addEventListener("ended", () => {
      if (token !== generation) return;
      finish();
      player = null;
      message("朗读结束");
    });
    current.addEventListener("error", fail);
    try {
      const pending = current.play();
      if (pending && typeof pending.catch === "function") pending.catch(fail);
    } catch (_) { fail(); }
  }, true);
  window.VocabAudio={stop:()=>{cancel();message("已停止");}};
  window.addEventListener("pagehide", cancel);
})();
