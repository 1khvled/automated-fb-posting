import os, sys, importlib.util
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

REPO = Path(sys.argv[1] if len(sys.argv) > 1
            else r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot")
load_dotenv(REPO / ".env", override=False)

spec = importlib.util.spec_from_file_location("bot", REPO / "post_bot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

print("keys present:",
      "gemini_pool=%d" % len(bot._gemini_keys()),
      "groq=%s" % bool(os.getenv("GROQ_API_KEY", "").strip()),
      "nvidia=%s" % bool(os.getenv("NVIDIA_API_KEY", "").strip()),
      "openrouter=%s" % bool(os.getenv("OPENROUTER_API_KEY", "").strip()))

probe = ("Summarise in one line: the Federal Reserve held rates steady. "
         "The committee said inflation is cooling but not yet at target.")

for name, fn in (("gemini", bot.gen_gemini), ("openrouter", bot.gen_openrouter),
                  ("groq", bot.gen_groq), ("nvidia", bot.gen_nvidia)):
    key_env = {"gemini": "GEMINI_API_KEYS", "openrouter": "OPENROUTER_API_KEY",
               "groq": "GROQ_API_KEY", "nvidia": "NVIDIA_API_KEY"}[name]
    if not os.getenv(key_env, "").strip():
        print(f"  {name:<11} (no key)")
        continue
    model = {"gemini": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
             "openrouter": "google/gemma-3-27b-it:free",
             "groq": "openai/gpt-oss-20b", "nvidia": "openai/gpt-oss-20b"}[name]
    try:
        out = fn(model, "Reply with the text only.", probe)
        print(f"  {name:<11} OK  -> {out[:90]}")
    except Exception as e:  # noqa: BLE001
        print(f"  {name:<11} FAIL -> {str(e)[:220]}")
