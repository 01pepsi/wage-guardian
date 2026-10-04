"""
Gemini 연결 공통 모듈 (llm.py)
- API 키는 .streamlit/secrets.toml 의 GEMINI_API_KEY 에서 읽는다 (코드에 직접 쓰지 않는다)
- 모델이 없거나(404) 사용량 초과(429)면 다음 후보 모델로 자동 전환한다
"""
import os
import re
import time
import tomllib
from pathlib import Path
from google import genai

SECRETS_PATH = Path(__file__).parent / ".streamlit" / "secrets.toml"
MODEL_CANDIDATES = ["gemini-flash-latest", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-flash-lite-latest"]


def _read_secret(name):
    if os.environ.get(name):
        return os.environ[name]
    if SECRETS_PATH.exists():
        with open(SECRETS_PATH, "rb") as f:
            return tomllib.load(f).get(name)
    return None


_client = None


def get_client():
    global _client
    if _client is None:
        key = _read_secret("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY가 없어요. .streamlit/secrets.toml 파일을 확인하세요.")
        _client = genai.Client(api_key=key)
    return _client


# 대기 안내를 화면에 띄우고 싶을 때 바꿔 끼우는 함수 (CLI는 print, 웹은 st.toast 등)
WAIT_NOTIFY = lambda seconds: print(f"⏳ 무료 사용량(분당 한도) 초과 → {seconds}초 기다렸다가 다시 시도해요...")


def _retry_seconds(msg):
    m = re.search(r"retry in ([\d.]+)s", msg) or re.search(r"retryDelay'?:\s*'(\d+)s", msg)
    return min(int(float(m.group(1))) + 2, 65) if m else 30


def generate(contents, config=None, models=None, max_waits=3):
    """후보 모델을 차례로 시도. 성공한 (응답, 모델이름)을 돌려준다.
    - 분당 한도 초과(429 PerMinute): 안내 후 기다렸다가 같은 모델로 재시도
    - 모델 없음(404)·일일 한도 초과·서버 혼잡(503): 다음 후보 모델로 전환"""
    client = get_client()
    preferred = _read_secret("GEMINI_MODEL")
    candidates = ([preferred] if preferred and not models else []) + (models or MODEL_CANDIDATES)
    last_error = None
    for model in dict.fromkeys(candidates):  # 중복 제거, 순서 유지
        waits = 0
        while True:
            try:
                resp = client.models.generate_content(model=model, contents=contents, config=config)
                return resp, model
            except Exception as e:
                msg = str(e)
                last_error = e
                per_minute = ("429" in msg or "RESOURCE_EXHAUSTED" in msg) and "PerDay" not in msg
                if per_minute and waits < max_waits:
                    seconds = _retry_seconds(msg)
                    WAIT_NOTIFY(seconds)
                    time.sleep(seconds)
                    waits += 1
                    continue
                if any(c in msg for c in ("404", "NOT_FOUND", "429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")):
                    break  # 다음 모델로
                raise
    raise RuntimeError(f"사용 가능한 Gemini 모델이 없어요. 마지막 오류: {last_error}")
