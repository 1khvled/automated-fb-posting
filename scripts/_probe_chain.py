import os, sys, importlib.util, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from dotenv import load_dotenv

PROBE = "Write one short sentence: the market opened higher today."


def chain(repo):
    load_dotenv(Path(repo) / ".env", override=False)
    spec = importlib.util.spec_from_file_location("bot", Path(repo) / "post_bot.py")
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)
    return bot, os.environ


for repo in (r"C:\Users\Abdelli\Documents\ethan-cole-fb-bot",
             r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot"):
    bot, env = chain(repo)
    print("=" * 66)
    print(Path(repo).name)
    print("  gemini pool:", len(bot._gemini_keys()),
          "| groq:", bool(env.get("GROQ_API_KEY", "").strip()),
          "| nvidia:", bool(env.get("NVIDIA_API_KEY", "").strip()),
          "| openrouter:", bool(env.get("OPENROUTER_API_KEY", "").strip()))
    tests = [("gemini", "gemini-3.5-flash")]
    if hasattr(bot, "gen_groq"):
        tests.append(("groq", "openai/gpt-oss-20b"))
    if hasattr(bot, "gen_nvidia"):
        tests.append(("nvidia", "openai/gpt-oss-20b"))
    if hasattr(bot, "gen_openrouter"):
        tests.append(("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"))
    for name, model in tests:
        fn = getattr(bot, f"gen_{name}", None)
        if not fn:
            print(f"  {name:<11} not in this repo")
            continue
        t0 = time.time()
        try:
            out = fn(model, "Reply with the sentence only.", PROBE)
            print(f"  {name:<11} OK   ({time.time()-t0:4.1f}s) -> {out[:60]!r}")
        except Exception as e:  # noqa: BLE001
            print(f"  {name:<11} FAIL ({time.time()-t0:4.1f}s) -> {str(e)[:150]}")
